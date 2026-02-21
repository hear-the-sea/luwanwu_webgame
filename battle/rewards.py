from __future__ import annotations

from typing import Callable, Dict

from django.db import transaction


def grant_battle_rewards(
    manor,
    drops: Dict[str, int],
    opponent_label: str,
    auto_reward: bool = True,
    drop_handler: Callable[[Dict[str, int]], None] | None = None,
) -> None:
    """
    Grant battle rewards either via custom handler or the default resource grant.
    """
    if not drops:
        return
    if drop_handler:
        drop_handler(drops)
        return
    if not auto_reward:
        return
    if _in_atomic_block():
        _grant_resources_locked(manor, drops, opponent_label)
    else:
        _grant_resources(manor, drops, opponent_label)


def dispatch_battle_message(manor, opponent_label: str, report) -> None:
    """
    Send battle report notification to the manor owner.
    """
    _create_message(manor, opponent_label, report)


def _grant_resources(manor, drops: Dict[str, int], opponent_label: str) -> None:
    from gameplay.models import ResourceEvent
    from gameplay.services.resources import grant_resources

    grant_resources(manor, drops, f"{opponent_label} 战利品", ResourceEvent.Reason.BATTLE_REWARD)


def _grant_resources_locked(manor, drops: Dict[str, int], opponent_label: str) -> None:
    from gameplay.models import Manor, ResourceEvent
    from gameplay.services.resources import grant_resources_locked

    locked_manor = Manor.objects.select_for_update().get(pk=manor.pk)
    grant_resources_locked(locked_manor, drops, f"{opponent_label} 战利品", ResourceEvent.Reason.BATTLE_REWARD)


def _in_atomic_block() -> bool:
    try:
        return bool(transaction.get_connection().in_atomic_block)
    except Exception:
        return False


def _create_message(manor, opponent_label: str, report) -> None:
    from gameplay.services.utils.messages import create_message

    create_message(
        manor=manor,
        kind="battle",
        title=f"{opponent_label} 战报",
        body="",
        battle_report=report,
    )
