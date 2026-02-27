"""帮会门客池视图。"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from core.utils import safe_int
from core.utils.rate_limit import rate_limit_redirect

from ..decorators import require_guild_manager, require_guild_member
from ..services import hero_pool as hero_pool_service


def _safe_slot_index(raw_value):
    slot = safe_int(raw_value, default=None)
    if slot is None:
        return None
    return int(slot)


@login_required
@require_guild_member
def hero_pool_page(request):
    member = request.guild_member
    context = hero_pool_service.get_hero_pool_page_context(member)
    return render(request, "guilds/hero_pool.html", context)


@login_required
@require_guild_member
@require_POST
@rate_limit_redirect("guild_hero_pool_submit", limit=20, window_seconds=60)
def hero_pool_submit(request):
    member = request.guild_member
    slot_index = _safe_slot_index(request.POST.get("slot_index"))
    guest_id = safe_int(request.POST.get("guest_id"), default=None)

    if slot_index is None or guest_id is None:
        messages.error(request, "参数错误")
        return redirect("guilds:hero_pool")

    try:
        result = hero_pool_service.submit_hero_pool_entry(member, guest_id=guest_id, slot_index=slot_index)
        action_text = "替换" if result.replaced else "设置"
        message = f"已{action_text}槽位 {result.entry.slot_index} 门客"
        if result.lineup_removed_count > 0:
            message += f"（原出战位已自动下阵 {result.lineup_removed_count} 项）"
        messages.success(request, message)
    except ValueError as exc:
        messages.error(request, str(exc))

    return redirect("guilds:hero_pool")


@login_required
@require_guild_member
@require_POST
@rate_limit_redirect("guild_hero_pool_remove", limit=20, window_seconds=60)
def hero_pool_remove(request):
    member = request.guild_member
    slot_index = _safe_slot_index(request.POST.get("slot_index"))
    if slot_index is None:
        messages.error(request, "参数错误")
        return redirect("guilds:hero_pool")

    try:
        result = hero_pool_service.remove_hero_pool_entry(member, slot_index=slot_index)
        message = f"已清空槽位 {result.slot_index}"
        if result.lineup_removed_count > 0:
            message += f"（自动下阵 {result.lineup_removed_count} 项）"
        messages.success(request, message)
    except ValueError as exc:
        messages.error(request, str(exc))

    return redirect("guilds:hero_pool")


@login_required
@require_guild_manager
@require_POST
@rate_limit_redirect("guild_lineup_add", limit=30, window_seconds=60)
def lineup_add(request):
    member = request.guild_member
    pool_entry_id = safe_int(request.POST.get("pool_entry_id"), default=None)
    if pool_entry_id is None:
        messages.error(request, "参数错误")
        return redirect("guilds:hero_pool")

    try:
        result = hero_pool_service.add_lineup_entry(
            guild=member.guild,
            operator=request.user,
            pool_entry_id=pool_entry_id,
        )
        messages.success(request, f"已加入出战名单（位置 {result.lineup_entry.slot_index}）")
    except ValueError as exc:
        messages.error(request, str(exc))

    return redirect("guilds:hero_pool")


@login_required
@require_guild_manager
@require_POST
@rate_limit_redirect("guild_lineup_remove", limit=30, window_seconds=60)
def lineup_remove(request):
    member = request.guild_member
    lineup_entry_id = safe_int(request.POST.get("lineup_entry_id"), default=None)
    if lineup_entry_id is None:
        messages.error(request, "参数错误")
        return redirect("guilds:hero_pool")

    try:
        hero_pool_service.remove_lineup_entry(
            guild=member.guild,
            operator=request.user,
            lineup_entry_id=lineup_entry_id,
        )
        messages.success(request, "已移出出战名单")
    except ValueError as exc:
        messages.error(request, str(exc))

    return redirect("guilds:hero_pool")
