"""
声望系统服务模块

玩家每累计花费1000两白银在建筑或技术上，增长1点声望。
"""
from __future__ import annotations

from django.db import transaction

from ..models import Manor

# 每增加1点声望需要花费的银两
PRESTIGE_SILVER_THRESHOLD = 1000


def add_prestige_silver(manor: Manor, silver_spent: int) -> int:
    """
    累计花费银两并计算声望增长。

    Args:
        manor: 庄园实例
        silver_spent: 本次花费的银两数量

    Returns:
        本次获得的声望点数
    """
    if silver_spent <= 0:
        return 0

    with transaction.atomic():
        locked_manor = Manor.objects.select_for_update().get(pk=manor.pk)

        before_spent = locked_manor.prestige_silver_spent
        before_spending_prestige = before_spent // PRESTIGE_SILVER_THRESHOLD

        # 历史上 prestige 字段可能包含 PVP 声望，这里将其视为“PVP附加声望”
        # spending 声望始终由累计消费推导，不应被PVP输赢影响。
        current_pvp_prestige = max(0, locked_manor.prestige - before_spending_prestige)

        locked_manor.prestige_silver_spent = before_spent + silver_spent
        after_spending_prestige = locked_manor.prestige_silver_spent // PRESTIGE_SILVER_THRESHOLD

        locked_manor.prestige = after_spending_prestige + current_pvp_prestige
        locked_manor.save(update_fields=["prestige_silver_spent", "prestige"])

        # 刷新调用方传入的 manor 对象，保持上层使用的一致性
        manor.refresh_from_db(fields=["prestige_silver_spent", "prestige"])

        gained = after_spending_prestige - before_spending_prestige
        return max(0, gained)


def get_prestige_progress(manor: Manor) -> dict:
    """
    获取声望进度信息。

    Args:
        manor: 庄园实例

    Returns:
        {
            "prestige": 当前声望,
            "silver_spent": 累计花费银两,
            "progress": 当前进度（0-999），
            "threshold": 每点声望所需银两,
        }
    """
    return {
        "prestige": manor.prestige,
        "silver_spent": manor.prestige_silver_spent,
        "progress": manor.prestige_silver_spent % PRESTIGE_SILVER_THRESHOLD,
        "threshold": PRESTIGE_SILVER_THRESHOLD,
    }
