"""
门客招募系统服务
"""

from __future__ import annotations

import logging
import random
from datetime import timedelta
from typing import TYPE_CHECKING, Dict, Iterable, List, Optional, Sequence, Tuple

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from core.config import RECRUITMENT
from core.exceptions import GuestNotIdleError, InsufficientStockError, InvalidAllocationError
from core.utils.time_scale import scale_duration

if TYPE_CHECKING:
    from gameplay.models import Manor

from ..models import (
    DEFENSE_TO_HP_MULTIPLIER,
    MAX_GUEST_SKILL_SLOTS,
    MIN_HP_FLOOR,
    Guest,
    GuestRarity,
    GuestRecruitment,
    GuestSkill,
    GuestStatus,
    GuestTemplate,
    RecruitmentCandidate,
    RecruitmentPool,
    RecruitmentRecord,
)
from ..query_utils import guest_template_rarity_rank_case
from ..utils.name_generator import generate_random_name
from ..utils.recruitment_variance import apply_recruitment_variance
from . import recruitment_batch as _recruitment_batch
from . import recruitment_candidates as _recruitment_candidates
from . import recruitment_finalize_helpers as _recruitment_finalize_helpers
from . import recruitment_flow as _recruitment_flow
from . import recruitment_templates as _recruitment_templates

logger = logging.getLogger(__name__)

_build_candidate_batch = _recruitment_candidates.build_candidate_batch
_build_guest_from_candidate = _recruitment_finalize_helpers.build_guest_from_candidate
_clear_manor_candidates = _recruitment_flow.clear_manor_candidates
_create_recruitment_record = _recruitment_finalize_helpers.create_recruitment_record
_delete_processed_candidates = _recruitment_finalize_helpers.delete_processed_candidates
_ensure_guest_capacity_available = _recruitment_finalize_helpers.ensure_guest_capacity_available
_ensure_retainer_capacity_available = _recruitment_finalize_helpers.ensure_retainer_capacity_available
_increment_retainer_count_locked = _recruitment_finalize_helpers.increment_retainer_count_locked
_load_candidate_generation_context = _recruitment_candidates.load_candidate_generation_context
_load_locked_retainer_candidate = _recruitment_finalize_helpers.load_locked_retainer_candidate
_persist_candidate_batch = _recruitment_candidates.persist_candidate_batch
_remaining_guest_capacity = _recruitment_finalize_helpers.remaining_guest_capacity
_resolve_candidate_draw_count = _recruitment_candidates.resolve_candidate_draw_count
_save_guest_objects = _recruitment_finalize_helpers.save_guest_objects
_split_candidates_by_capacity = _recruitment_finalize_helpers.split_candidates_by_capacity
_spend_recruitment_cost_if_needed = _recruitment_flow.spend_recruitment_cost_if_needed
_validate_recruitment_start_allowed = _recruitment_flow.validate_recruitment_start_allowed
_validate_retainer_candidate_identity = _recruitment_finalize_helpers.validate_retainer_candidate_identity
_build_rarity_search_order = _recruitment_templates._build_rarity_search_order
_choose_template_by_rarity = _recruitment_templates._choose_template_by_rarity
_choose_template_by_rarity_cached = _recruitment_templates._choose_template_by_rarity_cached
_filter_templates = _recruitment_templates._filter_templates
_get_hermit_templates = _recruitment_templates._get_hermit_templates
_get_recruitable_templates_by_rarity = _recruitment_templates._get_recruitable_templates_by_rarity
_resolve_entry_template = _recruitment_templates._resolve_entry_template
_resolve_recruitment_cost = _recruitment_flow.resolve_recruitment_cost
_resolve_recruitment_seed = _recruitment_flow.resolve_recruitment_seed
choose_template_from_entries = _recruitment_templates.choose_template_from_entries
clear_template_cache = _recruitment_templates.clear_template_cache

# 不可重复招募的稀有度（绿色及以上）
NON_REPEATABLE_RARITIES = frozenset(
    {
        GuestRarity.GREEN,
        GuestRarity.BLUE,
        GuestRarity.RED,
        GuestRarity.PURPLE,
        GuestRarity.ORANGE,
    }
)

CORE_POOL_TIERS = (
    RecruitmentPool.Tier.CUNMU,
    RecruitmentPool.Tier.XIANGSHI,
    RecruitmentPool.Tier.HUISHI,
    RecruitmentPool.Tier.DIANSHI,
)


def _invalidate_recruitment_hall_cache(manor_id: int | None) -> None:
    if not manor_id:
        return
    try:
        from gameplay.services.utils.cache import invalidate_recruitment_hall_cache

        invalidate_recruitment_hall_cache(int(manor_id))
    except Exception:
        logger.debug("Failed to invalidate recruitment hall cache for manor_id=%s", manor_id, exc_info=True)


def get_excluded_template_ids(manor: Manor) -> set[int]:
    """
    获取玩家不能再招募的门客模板ID。

    排除规则：
    - 绿色及以上稀有度：已拥有则排除
    - 黑色隐士：已拥有则排除
    - 黑色/灰色普通：可重复招募，不排除

    Args:
        manor: 庄园对象

    Returns:
        需要排除的模板ID集合
    """
    # 直接使用 values_list 获取需要的字段，无需 select_related
    owned_templates = manor.guests.values_list("template_id", "template__rarity", "template__is_hermit")

    excluded = set()
    for template_id, rarity, is_hermit in owned_templates:
        # 绿色及以上稀有度排除
        if rarity in NON_REPEATABLE_RARITIES:
            excluded.add(template_id)
        # 黑色隐士也排除
        elif rarity == GuestRarity.BLACK and is_hermit:
            excluded.add(template_id)

    return excluded


def list_pools(core_only: bool = False, *, include_entries: bool = True) -> Iterable[RecruitmentPool]:
    """列出所有招募卡池，按级别从高到低排序（殿试->村募）"""
    qs = RecruitmentPool.objects.all()
    if include_entries:
        qs = qs.prefetch_related("entries__template")
    if core_only:
        qs = qs.filter(tier__in=CORE_POOL_TIERS)

    # 定义排序优先级：殿试 > 会试 > 乡试 > 村募
    tier_priority = {
        RecruitmentPool.Tier.DIANSHI: 0,
        RecruitmentPool.Tier.HUISHI: 1,
        RecruitmentPool.Tier.XIANGSHI: 2,
        RecruitmentPool.Tier.CUNMU: 3,
    }

    pools = list(qs)
    pools.sort(key=lambda p: tier_priority.get(p.tier, 99))
    return pools


def get_pool_recruitment_duration_seconds(pool: RecruitmentPool) -> int:
    """获取卡池招募倒计时秒数（仅使用 YAML/数据库配置并应用全局时间倍率）。"""
    base_seconds = int(getattr(pool, "cooldown_seconds", 0) or 0)
    if base_seconds <= 0:
        return 0
    return scale_duration(base_seconds, minimum=1)


def _get_pool_daily_draw_limit() -> int:
    """获取单卡池每日招募上限。"""
    value = int(getattr(RECRUITMENT, "DAILY_POOL_DRAW_LIMIT", 300) or 300)
    return max(1, value)


def _count_pool_draws_today(manor_id: int, pool_id: int, *, now=None) -> int:
    """
    统计指定庄园在“今日”对指定卡池已发起的招募次数。

    仅统计 pending/completed，失败记录不计入上限。
    """
    current_time = now or timezone.now()
    local_now = timezone.localtime(current_time)
    day_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    valid_statuses = (GuestRecruitment.Status.PENDING, GuestRecruitment.Status.COMPLETED)
    return GuestRecruitment.objects.filter(
        manor_id=manor_id,
        pool_id=pool_id,
        status__in=valid_statuses,
        started_at__gte=day_start,
        started_at__lt=day_end,
    ).count()


def has_active_guest_recruitment(manor: Manor) -> bool:
    """是否存在进行中的门客招募。"""
    return manor.guest_recruitments.filter(status=GuestRecruitment.Status.PENDING).exists()


def get_active_guest_recruitment(manor: Manor) -> GuestRecruitment | None:
    """获取最早完成的一条进行中门客招募。"""
    return (
        manor.guest_recruitments.filter(status=GuestRecruitment.Status.PENDING)
        .select_related("pool")
        .order_by("complete_at")
        .first()
    )


def available_guests(manor: Manor) -> Sequence[Guest]:
    """获取庄园所有可用门客"""
    return (
        manor.guests.select_related("template")
        .prefetch_related("gear_items__template")
        .annotate(_template_rarity_rank=guest_template_rarity_rank_case("template__rarity"))
        .order_by("-_template_rarity_rank", "-level")
    )


def list_candidates(manor: Manor) -> QuerySet[RecruitmentCandidate]:
    """列出庄园的招募候选门客"""
    return manor.candidates.only("id", "display_name", "rarity", "rarity_revealed", "created_at").order_by("created_at")


def grant_template_skills(guest: Guest) -> None:
    """为门客授予模板预设技能"""
    initial_skills = list(guest.template.initial_skills.all())
    if not initial_skills:
        return
    existing_skill_ids = set(guest.guest_skills.values_list("skill_id", flat=True))
    capacity_left = MAX_GUEST_SKILL_SLOTS - len(existing_skill_ids)
    if capacity_left <= 0:
        return

    skills_to_create = []
    for skill in initial_skills:
        if skill.id in existing_skill_ids:
            continue
        if len(skills_to_create) >= capacity_left:
            break
        skills_to_create.append(
            GuestSkill(
                guest=guest,
                skill=skill,
                source=GuestSkill.Source.TEMPLATE,
            )
        )

    if skills_to_create:
        GuestSkill.objects.bulk_create(skills_to_create)


def create_guest_from_template(
    *,
    manor: Manor,
    template: GuestTemplate,
    rarity: Optional[str] = None,
    archetype: Optional[str] = None,
    custom_name: str = "",
    rng: Optional[random.Random] = None,
    grant_skills: bool = True,
    save: bool = True,
) -> Guest:
    """
    按模板创建门客（含属性波动、初始HP与技能）。

    Args:
        manor: 所属庄园
        template: 门客模板
        rarity: 用于属性波动的稀有度（默认使用模板稀有度）
        archetype: 用于属性波动的流派（默认使用模板流派）
        custom_name: 自定义名称（黑/灰门客使用）
        rng: 随机数生成器
        grant_skills: 是否授予模板技能（需要已保存）
        save: 是否直接保存到数据库
    """
    rng = rng or random.Random()
    effective_rarity = rarity or template.rarity
    effective_archetype = archetype or template.archetype

    gender_choice = template.default_gender
    if not gender_choice or gender_choice == "unknown":
        gender_choice = rng.choice(["male", "female"])
    morality_value = template.default_morality or rng.randint(30, 100)

    template_attrs = {
        "force": template.base_attack,
        "intellect": template.base_intellect,
        "defense": template.base_defense,
        "agility": template.base_agility,
        "luck": template.base_luck,
    }
    varied_attrs = apply_recruitment_variance(
        template_attrs,
        rarity=effective_rarity,
        archetype=effective_archetype,
        rng=rng,
    )

    # 预计算初始 HP（与 Guest.max_hp property 保持一致）
    initial_hp = max(
        MIN_HP_FLOOR,
        template.base_hp + varied_attrs["defense"] * DEFENSE_TO_HP_MULTIPLIER,
    )

    guest = Guest(
        manor=manor,
        template=template,
        custom_name=custom_name,
        force=varied_attrs["force"],
        intellect=varied_attrs["intellect"],
        defense_stat=varied_attrs["defense"],
        agility=varied_attrs["agility"],
        luck=varied_attrs["luck"],
        # 记录初始属性（用于计算升级成长）
        initial_force=varied_attrs["force"],
        initial_intellect=varied_attrs["intellect"],
        initial_defense=varied_attrs["defense"],
        initial_agility=varied_attrs["agility"],
        loyalty=60,
        gender=gender_choice,
        morality=morality_value,
        current_hp=initial_hp,
    )

    if save:
        guest.save()
        if grant_skills:
            grant_template_skills(guest)

    return guest


def reveal_candidate_rarity(manor: Manor) -> int:
    """
    使用放大镜显示所有候选门客的稀有度。

    Args:
        manor: 庄园对象

    Returns:
        被显示的候选门客数量
    """
    candidates = manor.candidates.filter(rarity_revealed=False)
    count = candidates.update(rarity_revealed=True)
    if count > 0:
        _invalidate_recruitment_hall_cache(getattr(manor, "id", None))
    return count


@transaction.atomic
def use_magnifying_glass_for_candidates(manor: Manor, item_id: int) -> int:
    """
    使用放大镜显示所有未显现候选门客稀有度（原子化版本）。

    关键保证：
    - 稀有度显现与道具扣减在同一事务中完成
    - 任一步失败都会整体回滚，避免“显现成功但扣道具失败”导致可重复白嫖
    - 锁顺序统一为 Manor -> InventoryItem -> RecruitmentCandidate
    """
    from gameplay.models import InventoryItem
    from gameplay.models import Manor as ManorModel
    from gameplay.services.inventory.core import consume_inventory_item_locked

    ManorModel.objects.select_for_update().get(pk=manor.pk)

    locked_item = (
        InventoryItem.objects.select_for_update()
        .select_related("template")
        .filter(
            pk=item_id,
            manor=manor,
            template__key="fangdajing",
            storage_location=InventoryItem.StorageLocation.WAREHOUSE,
        )
        .first()
    )
    if not locked_item:
        raise ValueError("道具不存在或不属于您的庄园")
    if locked_item.quantity <= 0:
        raise InsufficientStockError(locked_item.template.name, 1, locked_item.quantity)

    count = manor.candidates.filter(rarity_revealed=False).update(rarity_revealed=True)
    if count <= 0:
        return 0

    consume_inventory_item_locked(locked_item, 1)
    _invalidate_recruitment_hall_cache(getattr(manor, "id", None))
    return int(count)


@transaction.atomic
def recruit_guest(manor: Manor, pool: RecruitmentPool, seed: int | None = None) -> List[RecruitmentCandidate]:
    """
    从指定卡池招募门客。

    如果卡池未配置 entries，会从所有 recruitable=True 的模板中按稀有度随机选择。

    Args:
        manor: 庄园对象
        pool: 招募卡池
        seed: 随机数种子（可选）

    Returns:
        招募得到的候选门客列表
    """
    cost = _resolve_recruitment_cost(pool)
    if cost:
        from gameplay.models import ResourceEvent
        from gameplay.services.resources import spend_resources

        # 并发安全修复：先检查资源是否足够再删除候选
        # 避免资源不足时候选已被删除的问题
        spend_resources(
            manor,
            cost,
            note=f"卡池：{pool.name}",
            reason=ResourceEvent.Reason.RECRUIT_COST,
        )

    # 资源扣除成功后再清空候选门客并生成候选（防止玩家绕过前端确认）
    return _build_recruitment_candidates(
        manor,
        pool,
        seed=seed,
        total_draw_count=_resolve_candidate_draw_count(pool=pool, manor=manor, total_draw_count=None),
        clear_existing=True,
    )


def _build_recruitment_candidates(
    manor: Manor,
    pool: RecruitmentPool,
    *,
    seed: int | None = None,
    total_draw_count: int | None = None,
    clear_existing: bool = True,
) -> List[RecruitmentCandidate]:
    """
    生成候选门客（不处理资源扣除）。

    Args:
        manor: 庄园对象
        pool: 招募卡池
        seed: 随机种子
        total_draw_count: 候选数量，不传则按“基础+酒馆加成”
        clear_existing: 是否清空已有候选
    """
    if clear_existing:
        _clear_manor_candidates(manor)

    context = _load_candidate_generation_context(
        manor=manor,
        pool=pool,
        seed=seed,
        total_draw_count=total_draw_count,
        get_recruitable_templates_by_rarity=_get_recruitable_templates_by_rarity,
        get_hermit_templates=_get_hermit_templates,
        get_excluded_template_ids=get_excluded_template_ids,
    )
    candidates_to_create = _build_candidate_batch(
        manor=manor,
        pool=pool,
        pool_entries=context["pool_entries"],
        resolved_draw_count=context["resolved_draw_count"],
        excluded_ids=context["excluded_ids"],
        rng=context["rng"],
        choose_template_from_entries=choose_template_from_entries,
        templates_by_rarity=context["templates_by_rarity"],
        hermit_templates=context["hermit_templates"],
        generate_random_name=generate_random_name,
        non_repeatable_rarities=NON_REPEATABLE_RARITIES,
    )

    return _persist_candidate_batch(
        recruitment_candidate_model=RecruitmentCandidate,
        manor=manor,
        candidates_to_create=candidates_to_create,
        invalidate_cache=_invalidate_recruitment_hall_cache,
    )


def _schedule_guest_recruitment_completion(recruitment: GuestRecruitment, eta_seconds: int) -> None:
    """调度门客招募完成任务。"""
    _recruitment_flow.schedule_guest_recruitment_completion(recruitment, eta_seconds, logger=logger)


def _mark_recruitment_failed_locked(recruitment: GuestRecruitment, *, current_time, reason: str) -> None:
    _recruitment_flow.mark_recruitment_failed_locked(
        recruitment,
        current_time=current_time,
        reason=reason,
        invalidate_cache=_invalidate_recruitment_hall_cache,
    )


def _mark_recruitment_completed_locked(
    recruitment: GuestRecruitment,
    *,
    current_time,
    result_count: int,
) -> None:
    _recruitment_flow.mark_recruitment_completed_locked(
        recruitment,
        current_time=current_time,
        result_count=result_count,
        invalidate_cache=_invalidate_recruitment_hall_cache,
    )


def _send_recruitment_completion_notification(
    *,
    manor: Manor,
    pool: RecruitmentPool,
    candidate_count: int,
    recruitment_id: int | None = None,
) -> None:
    _recruitment_flow.send_recruitment_completion_notification(
        manor=manor,
        pool=pool,
        candidate_count=candidate_count,
        logger=logger,
        recruitment_id=recruitment_id,
    )


@transaction.atomic
def start_guest_recruitment(manor: Manor, pool: RecruitmentPool, seed: int | None = None) -> GuestRecruitment:
    """
    启动异步门客招募：立即扣资源，进入倒计时，完成后生成候选。
    """
    from gameplay.models import Manor as ManorModel
    from gameplay.models import ResourceEvent
    from gameplay.services.resources import spend_resources

    locked_manor = ManorModel.objects.select_for_update().get(pk=manor.pk)

    current_time = timezone.now()
    _validate_recruitment_start_allowed(
        locked_manor=locked_manor,
        pool=pool,
        current_time=current_time,
        has_active_guest_recruitment=has_active_guest_recruitment,
        daily_limit=_get_pool_daily_draw_limit(),
        count_pool_draws_today=_count_pool_draws_today,
    )

    resolved_seed = _resolve_recruitment_seed(seed)
    draw_count = _resolve_candidate_draw_count(pool=pool, manor=locked_manor, total_draw_count=None)
    duration_seconds = get_pool_recruitment_duration_seconds(pool)
    cost = _resolve_recruitment_cost(pool)

    _spend_recruitment_cost_if_needed(
        manor=locked_manor,
        cost=cost,
        pool_name=pool.name,
        spend_resources=spend_resources,
        recruit_cost_reason=ResourceEvent.Reason.RECRUIT_COST,
    )

    _clear_manor_candidates(locked_manor)

    recruitment = _recruitment_flow.create_pending_recruitment(
        recruitment_model=GuestRecruitment,
        manor=locked_manor,
        pool=pool,
        current_time=current_time,
        cost=cost,
        draw_count=draw_count,
        duration_seconds=duration_seconds,
        seed=resolved_seed,
    )
    _schedule_guest_recruitment_completion(recruitment, duration_seconds)
    _invalidate_recruitment_hall_cache(getattr(locked_manor, "id", None))
    return recruitment


def finalize_guest_recruitment(
    recruitment: GuestRecruitment,
    *,
    now=None,
    send_notification: bool = False,
) -> bool:
    """
    完成门客招募：生成候选并更新队列状态。
    """
    recruitment_id = getattr(recruitment, "pk", None)
    if not recruitment_id:
        return False

    current_time = now or timezone.now()
    manor: Manor | None = None
    pool: RecruitmentPool | None = None
    candidate_count = 0

    with transaction.atomic():
        from gameplay.models import Manor as ManorModel

        locked = (
            GuestRecruitment.objects.select_for_update()
            .select_related("manor", "manor__user", "pool")
            .filter(pk=recruitment_id)
            .first()
        )
        if not locked or locked.status != GuestRecruitment.Status.PENDING:
            return False
        if locked.complete_at > current_time:
            return False
        if not locked.pool_id:
            _mark_recruitment_failed_locked(locked, current_time=current_time, reason="招募卡池不存在")
            return False
        ManorModel.objects.select_for_update().filter(pk=locked.manor_id).exists()

        try:
            candidates = _build_recruitment_candidates(
                locked.manor,
                locked.pool,
                seed=locked.seed,
                total_draw_count=locked.draw_count,
                clear_existing=True,
            )
        except Exception as exc:
            logger.exception("Failed to finalize guest recruitment %s: %s", locked.id, exc)
            _mark_recruitment_failed_locked(locked, current_time=current_time, reason=str(exc))
            return False

        _mark_recruitment_completed_locked(locked, current_time=current_time, result_count=len(candidates))
        manor = locked.manor
        pool = locked.pool
        candidate_count = len(candidates)

    if send_notification and pool and manor is not None:
        _send_recruitment_completion_notification(
            manor=manor,
            pool=pool,
            candidate_count=candidate_count,
            recruitment_id=recruitment_id,
        )
    return True


def refresh_guest_recruitments(manor: Manor, limit: int = 20) -> int:
    """兜底刷新门客招募状态（用于 worker 中断场景）。"""
    now = timezone.now()
    completed = 0
    recruitments = (
        manor.guest_recruitments.filter(status=GuestRecruitment.Status.PENDING, complete_at__lte=now)
        .select_related("pool", "manor", "manor__user")
        .order_by("complete_at")[:limit]
    )
    for recruitment in recruitments:
        if finalize_guest_recruitment(recruitment, now=now, send_notification=True):
            completed += 1
    return completed


@transaction.atomic
def finalize_candidate(candidate: RecruitmentCandidate) -> Guest:
    """
    确认招募候选门客，将其转为正式门客。

    Args:
        candidate: 候选门客对象

    Returns:
        创建的门客对象

    Raises:
        ValueError: 庄园容量已满时抛出
    """
    from gameplay.models import Manor

    manor = Manor.objects.select_for_update().get(pk=candidate.manor_id)
    _ensure_guest_capacity_available(manor)
    guest = _build_guest_from_candidate(
        candidate=candidate,
        manor=manor,
        rng=random.Random(),
        create_guest_func=create_guest_from_template,
        should_use_candidate_custom_name=_recruitment_batch.should_use_candidate_custom_name,
    )
    _create_recruitment_record(
        recruitment_record_model=RecruitmentRecord,
        manor=manor,
        candidate=candidate,
        guest=guest,
    )
    candidate.delete()
    _invalidate_recruitment_hall_cache(getattr(manor, "id", None))
    return guest


_preload_templates = _recruitment_batch.preload_templates


def _prepare_guest_objects(
    candidates: List[RecruitmentCandidate],
    template_map: Dict[int, GuestTemplate],
    manor,
    rng: random.Random,
) -> tuple[List[Guest], List[GuestTemplate], List[int]]:
    return _recruitment_batch.prepare_guest_objects(
        candidates,
        template_map,
        manor,
        rng,
        create_guest_func=create_guest_from_template,
    )


@transaction.atomic
def bulk_finalize_candidates(
    candidates: List[RecruitmentCandidate],
) -> Tuple[List[Guest], List[RecruitmentCandidate]]:
    """
    批量确认招募候选门客，将其转为正式门客。

    优化策略：
    1. 使用辅助函数预加载模板数据
    2. 使用辅助函数准备门客对象
    3. 减少事务内的复杂逻辑，提升并发性能

    Args:
        candidates: 候选门客对象列表

    Returns:
        (成功招募的门客列表, 因容量不足而失败的候选列表)
    """
    if not candidates:
        return [], []

    from gameplay.models import Manor

    manor = Manor.objects.select_for_update().get(pk=candidates[0].manor_id)
    available_slots = _remaining_guest_capacity(manor)
    if available_slots <= 0:
        return [], candidates

    to_process, failed = _split_candidates_by_capacity(candidates, available_slots=available_slots)

    # 预加载模板并准备门客对象
    rng = random.Random()
    template_ids = {candidate.template_id for candidate in to_process}
    template_map = _preload_templates(template_ids)

    guests_to_create, templates_for_guests, candidate_ids_to_delete = _prepare_guest_objects(
        to_process, template_map, manor, rng
    )

    # 批量写入数据库
    created_guests = _save_guest_objects(guests_to_create)

    records_to_create = _recruitment_batch.build_recruitment_records(
        manor=manor,
        candidates=to_process,
        created_guests=created_guests,
    )
    RecruitmentRecord.objects.bulk_create(records_to_create)

    all_skills_to_create = _recruitment_batch.build_template_skill_rows(
        created_guests=created_guests,
        templates_for_guests=templates_for_guests,
        max_guest_skill_slots=MAX_GUEST_SKILL_SLOTS,
    )
    if all_skills_to_create:
        GuestSkill.objects.bulk_create(all_skills_to_create)

    _delete_processed_candidates(
        recruitment_candidate_model=RecruitmentCandidate,
        candidate_ids_to_delete=candidate_ids_to_delete,
    )
    _invalidate_recruitment_hall_cache(getattr(manor, "id", None))

    return created_guests, failed


@transaction.atomic
def convert_candidate_to_retainer(candidate: RecruitmentCandidate) -> None:
    """
    将候选门客转为家丁。

    Args:
        candidate: 候选门客对象

    Raises:
        ValueError: 家丁房容量已满时抛出
    """
    candidate_id, manor_id = _validate_retainer_candidate_identity(candidate)

    from gameplay.models import Manor

    # 锁顺序统一为 Manor -> RecruitmentCandidate，避免与其他招募流程死锁
    manor = Manor.objects.select_for_update().get(pk=manor_id)
    locked_candidate = _load_locked_retainer_candidate(
        recruitment_candidate_model=RecruitmentCandidate,
        candidate_id=candidate_id,
        manor_id=manor_id,
    )
    if locked_candidate is None:
        raise ValueError("候选门客不存在或已处理")

    _ensure_retainer_capacity_available(manor)
    _increment_retainer_count_locked(manor)
    locked_candidate.delete()
    _invalidate_recruitment_hall_cache(getattr(manor, "id", None))


def allocate_attribute_points(guest: Guest, attribute: str, points: int) -> Guest:
    """
    为门客分配属性点到指定属性。

    Args:
        guest: 门客对象
        attribute: 属性名称（force/intellect/defense/agility）
        points: 要分配的点数

    Returns:
        更新后的门客对象

    Raises:
        ValueError: 参数不合法时抛出
    """
    if not getattr(guest, "pk", None):
        raise ValueError("门客不存在")

    with transaction.atomic():
        locked_guest = Guest.objects.select_for_update().filter(pk=guest.pk).first()
        if not locked_guest:
            raise ValueError("门客不存在")
        if locked_guest.status != GuestStatus.IDLE:
            raise GuestNotIdleError(locked_guest)

        # 安全修复：验证点数范围
        if points <= 0:
            raise InvalidAllocationError("zero_points")
        if locked_guest.attribute_points < points:
            raise InvalidAllocationError("insufficient")

        # 属性字段映射
        attr_map = {
            "force": "force",
            "intellect": "intellect",
            "defense": "defense_stat",
            "agility": "agility",
        }
        # 已分配点数字段映射
        allocated_map = {
            "force": "allocated_force",
            "intellect": "allocated_intellect",
            "defense": "allocated_defense",
            "agility": "allocated_agility",
        }

        target = attr_map.get(attribute)
        allocated_field = allocated_map.get(attribute)
        if not target or not allocated_field:
            raise InvalidAllocationError("unknown_attribute")

        # 安全修复：检查属性上限，防止溢出
        MAX_ATTRIBUTE_VALUE = 9999  # 属性值安全上限
        current_value = getattr(locked_guest, target)
        if current_value + points > MAX_ATTRIBUTE_VALUE:
            raise InvalidAllocationError("attribute_overflow")

        locked_guest.attribute_points -= points
        updated_fields = ["attribute_points"]

        # 增加属性值
        setattr(locked_guest, target, getattr(locked_guest, target) + points)
        updated_fields.append(target)

        # 记录已分配点数
        setattr(locked_guest, allocated_field, getattr(locked_guest, allocated_field) + points)
        updated_fields.append(allocated_field)

        unique_fields = list(dict.fromkeys(updated_fields))
        locked_guest.save(update_fields=unique_fields)
    return locked_guest
