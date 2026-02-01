from __future__ import annotations

from datetime import timedelta
from typing import Dict, List

from django.db import transaction
from django.utils import timezone

from core.exceptions import (
    GuestNotIdleError,
    GuestNotRequirementError,
    WorkLimitExceededError,
    WorkNotCompletedError,
    WorkNotInProgressError,
    WorkRewardClaimedError,
)
from core.utils.time_scale import scale_duration
from gameplay.models import Manor, ResourceEvent, ResourceType, WorkAssignment, WorkTemplate
from guests.models import Guest, GuestStatus


MAX_CONCURRENT_WORKERS = 3  # 最多同时打工人数


def get_available_works_for_guest(guest: Guest) -> List[WorkTemplate]:
    """获取门客可接受的工作列表"""
    return list(
        WorkTemplate.objects.filter(
            required_level__lte=guest.level,
            required_force__lte=guest.force,
            required_intellect__lte=guest.intellect,
        ).order_by("tier", "display_order")
    )


def assign_guest_to_work(guest: Guest, work_template: WorkTemplate) -> WorkAssignment:
    """派遣门客打工"""
    # 检查门客状态（初步检查，事务内会再次验证）
    if guest.status != GuestStatus.IDLE:
        raise GuestNotIdleError(guest)

    # 检查门客是否满足工作要求
    if guest.level < work_template.required_level:
        raise GuestNotRequirementError(
            guest, "level", work_template.required_level, guest.level
        )
    if guest.force < work_template.required_force:
        raise GuestNotRequirementError(
            guest, "force", work_template.required_force, guest.force
        )
    if guest.intellect < work_template.required_intellect:
        raise GuestNotRequirementError(
            guest, "intellect", work_template.required_intellect, guest.intellect
        )

    # 使用事务确保原子性
    with transaction.atomic():
        # 锁定门客，防止并发问题
        guest = Guest.objects.select_for_update().get(pk=guest.pk)

        # 再次检查状态
        if guest.status != GuestStatus.IDLE:
            raise GuestNotIdleError(guest)

        # 在事务内检查打工人数限制，防止并发超限
        current_working = WorkAssignment.objects.filter(
            manor=guest.manor,
            status=WorkAssignment.Status.WORKING
        ).count()
        if current_working >= MAX_CONCURRENT_WORKERS:
            raise WorkLimitExceededError(MAX_CONCURRENT_WORKERS)

        # 计算完成时间
        now = timezone.now()
        complete_at = now + timedelta(seconds=scale_duration(work_template.work_duration, minimum=1))

        # 创建打工记录
        assignment = WorkAssignment.objects.create(
            manor=guest.manor,
            guest=guest,
            work_template=work_template,
            status=WorkAssignment.Status.WORKING,
            complete_at=complete_at,
        )

        # 更新门客状态
        guest.status = GuestStatus.WORKING
        guest.save(update_fields=["status"])

    return assignment


def complete_work_assignments() -> int:
    """
    完成所有到期的打工任务
    由定时任务调用
    返回完成的任务数量

    性能优化：使用批量更新替代逐条更新，减少数据库查询
    """
    now = timezone.now()

    with transaction.atomic():
        # 查找所有到期的打工任务
        assignments = list(WorkAssignment.objects.filter(
            status=WorkAssignment.Status.WORKING,
            complete_at__lte=now
        ).select_related("guest"))

        if not assignments:
            return 0

        # 收集需要更新的门客ID
        guest_ids = [a.guest_id for a in assignments]
        assignment_ids = [a.id for a in assignments]

        # 批量更新任务状态（1次查询）
        WorkAssignment.objects.filter(id__in=assignment_ids).update(
            status=WorkAssignment.Status.COMPLETED,
            finished_at=now
        )

        # 批量更新门客状态（1次查询）
        Guest.objects.filter(id__in=guest_ids).update(status=GuestStatus.IDLE)

        return len(assignments)


def recall_guest_from_work(assignment: WorkAssignment) -> bool:
    """
    召回打工中的门客
    不发放任何报酬
    """
    if assignment.status != WorkAssignment.Status.WORKING:
        raise WorkNotInProgressError()

    with transaction.atomic():
        # 更新任务状态
        assignment.status = WorkAssignment.Status.RECALLED
        assignment.finished_at = timezone.now()
        assignment.save(update_fields=["status", "finished_at"])

        # 更新门客状态
        assignment.guest.status = GuestStatus.IDLE
        assignment.guest.save(update_fields=["status"])

    return True


def claim_work_reward(assignment: WorkAssignment) -> Dict[str, int]:
    """
    领取打工报酬
    返回获得的资源
    """
    # 检查任务状态
    if assignment.status != WorkAssignment.Status.COMPLETED:
        raise WorkNotCompletedError()

    if assignment.reward_claimed:
        raise WorkRewardClaimedError()

    reward_silver = assignment.work_template.reward_silver

    with transaction.atomic():
        # 增加庄园银两
        manor = Manor.objects.select_for_update().get(pk=assignment.manor.pk)
        manor.silver += reward_silver
        manor.save(update_fields=["silver"])

        # 记录资源流水
        ResourceEvent.objects.create(
            manor=manor,
            resource_type=ResourceType.SILVER,
            delta=reward_silver,
            reason=ResourceEvent.Reason.WORK_REWARD,
            note=f"{assignment.guest.display_name} 在 {assignment.work_template.name} 打工获得报酬"
        )

        # 标记为已领取
        assignment.reward_claimed = True
        assignment.save(update_fields=["reward_claimed"])

    return {"silver": reward_silver}


def refresh_work_assignments(manor: Manor) -> None:
    """
    刷新打工状态
    自动完成到期的任务

    性能优化：使用批量更新替代逐条更新
    """
    now = timezone.now()

    with transaction.atomic():
        # 查找该庄园所有到期的打工任务
        assignments = list(WorkAssignment.objects.filter(
            manor=manor,
            status=WorkAssignment.Status.WORKING,
            complete_at__lte=now
        ))

        if not assignments:
            return

        # 收集需要更新的ID
        guest_ids = [a.guest_id for a in assignments]
        assignment_ids = [a.id for a in assignments]

        # 批量更新任务状态（1次查询）
        WorkAssignment.objects.filter(id__in=assignment_ids).update(
            status=WorkAssignment.Status.COMPLETED,
            finished_at=now
        )

        # 批量更新门客状态（1次查询）
        Guest.objects.filter(id__in=guest_ids).update(status=GuestStatus.IDLE)
