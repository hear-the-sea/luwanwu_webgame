"""
门客工资支付服务

性能优化说明：
- 使用 bulk_check_salary_paid() 替代循环调用 check_salary_paid()
- 一次查询获取所有已支付记录，避免 N+1 问题
"""

from datetime import date
from typing import Dict, List, Set

from django.db import transaction
from django.utils import timezone

from core.exceptions import (
    GuestOwnershipError,
    InsufficientResourceError,
    NoGuestsError,
    SalaryAlreadyPaidError,
)
from gameplay.models import Manor
from guests.models import Guest, RARITY_SALARY, SalaryPayment


def get_guest_salary(guest: Guest) -> int:
    """
    获取门客的工资金额

    Args:
        guest: 门客实例

    Returns:
        工资金额
    """
    return RARITY_SALARY.get(guest.rarity, 1000)


def check_salary_paid(guest: Guest, for_date: date = None) -> bool:
    """
    检查门客是否已支付今日工资

    注意：此函数会产生一次数据库查询。如果需要批量检查，
    请使用 bulk_check_salary_paid() 以避免 N+1 问题。

    Args:
        guest: 门客实例
        for_date: 检查日期，默认为今天

    Returns:
        是否已支付
    """
    if for_date is None:
        for_date = timezone.now().date()

    return SalaryPayment.objects.filter(
        guest=guest,
        for_date=for_date
    ).exists()


def bulk_check_salary_paid(guest_ids: List[int], for_date: date = None) -> Set[int]:
    """
    批量检查门客是否已支付工资（优化 N+1 查询）

    Args:
        guest_ids: 门客ID列表
        for_date: 检查日期，默认为今天

    Returns:
        已支付工资的门客ID集合
    """
    if for_date is None:
        for_date = timezone.now().date()

    if not guest_ids:
        return set()

    paid_guest_ids = SalaryPayment.objects.filter(
        guest_id__in=guest_ids,
        for_date=for_date
    ).values_list("guest_id", flat=True)

    return set(paid_guest_ids)


@transaction.atomic
def pay_guest_salary(manor: Manor, guest: Guest, for_date: date = None) -> SalaryPayment:
    """
    支付单个门客的工资

    Args:
        manor: 庄园
        guest: 门客
        for_date: 支付日期，默认为今天

    Returns:
        工资支付记录

    Raises:
        ValueError: 验证失败时抛出异常
    """
    if for_date is None:
        for_date = timezone.now().date()

    # 验证门客属于该庄园
    if guest.manor != manor:
        raise GuestOwnershipError(guest)

    # 检查是否已支付
    if check_salary_paid(guest, for_date):
        raise SalaryAlreadyPaidError(guest)

    # 计算工资
    salary_amount = get_guest_salary(guest)

    # 验证银两是否足够
    if manor.silver < salary_amount:
        raise InsufficientResourceError("silver", salary_amount, manor.silver)

    # 扣除银两
    manor.silver -= salary_amount
    manor.save(update_fields=["silver"])

    # 创建支付记录
    payment = SalaryPayment.objects.create(
        manor=manor,
        guest=guest,
        amount=salary_amount,
        for_date=for_date
    )

    return payment


@transaction.atomic
def pay_all_salaries(manor: Manor, for_date: date = None) -> Dict:
    """
    一键支付所有门客工资

    Args:
        manor: 庄园
        for_date: 支付日期，默认为今天

    Returns:
        支付结果字典

    Raises:
        ValueError: 验证失败时抛出异常
    """
    if for_date is None:
        for_date = timezone.now().date()

    # 获取所有门客
    guests = list(Guest.objects.filter(manor=manor).select_related("template"))

    if not guests:
        raise NoGuestsError()

    # 批量查询已支付记录（优化 N+1）
    guest_ids = [g.id for g in guests]
    paid_ids = bulk_check_salary_paid(guest_ids, for_date)

    # 筛选未支付工资的门客
    unpaid_guests = [g for g in guests if g.id not in paid_ids]

    if not unpaid_guests:
        raise SalaryAlreadyPaidError()

    # 计算总工资
    total_salary = sum(get_guest_salary(guest) for guest in unpaid_guests)

    # 验证银两是否足够
    if manor.silver < total_salary:
        raise InsufficientResourceError("silver", total_salary, manor.silver)

    # 批量支付
    payments = []
    for guest in unpaid_guests:
        salary_amount = get_guest_salary(guest)
        payment = SalaryPayment(
            manor=manor,
            guest=guest,
            amount=salary_amount,
            for_date=for_date
        )
        payments.append(payment)

    # 批量创建记录
    SalaryPayment.objects.bulk_create(payments)

    # 扣除总银两
    manor.silver -= total_salary
    manor.save(update_fields=["silver"])

    return {
        "paid_count": len(unpaid_guests),
        "total_amount": total_salary,
        "guest_names": [guest.display_name for guest in unpaid_guests]
    }


def get_unpaid_guests(manor: Manor, for_date: date = None) -> List[Guest]:
    """
    获取未支付工资的门客列表

    Args:
        manor: 庄园
        for_date: 检查日期，默认为今天

    Returns:
        未支付工资的门客列表
    """
    if for_date is None:
        for_date = timezone.now().date()

    guests = list(Guest.objects.filter(manor=manor).select_related("template"))

    if not guests:
        return []

    # 批量查询已支付记录（优化 N+1）
    guest_ids = [g.id for g in guests]
    paid_ids = bulk_check_salary_paid(guest_ids, for_date)

    # 筛选未支付工资的门客
    return [g for g in guests if g.id not in paid_ids]
