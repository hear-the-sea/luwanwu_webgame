"""
消息系统视图
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from ..constants import UIConstants
from ..models import ResourceType
from ..services import (
    claim_message_attachments,
    delete_all_messages,
    delete_messages,
    ensure_manor,
    list_messages,
    mark_all_messages_read,
    mark_messages_read,
    refresh_manor_state,
    unread_message_count,
)


class MessageListView(LoginRequiredMixin, TemplateView):
    """消息列表页面"""

    template_name = "gameplay/messages.html"
    MESSAGES_PER_PAGE = UIConstants.MESSAGES_PER_PAGE

    def get_context_data(self, **kwargs):
        """
        Render the message center where players manage battle/system messages.

        Adds the unread count to the template so the UI can display a
        contextual hint ("当前有 X 条未读通知").
        """
        context = super().get_context_data(**kwargs)
        manor = ensure_manor(self.request.user)
        refresh_manor_state(manor)
        context["manor"] = manor

        all_messages = list_messages(manor)
        paginator = Paginator(all_messages, self.MESSAGES_PER_PAGE)
        page_number = self.request.GET.get("page", 1)
        page_obj = paginator.get_page(page_number)

        context["message_list"] = page_obj
        context["page_obj"] = page_obj
        context["unread_count"] = unread_message_count(manor)
        return context


@login_required
def view_message(request: HttpRequest, pk: int) -> HttpResponse:
    """
    显示消息详情页面

    对于战报消息，跳转到战报详情页；
    对于其他类型消息，显示完整的消息内容和附件信息。

    支持JSON请求：当请求头包含 Accept: application/json 或 X-Requested-With: XMLHttpRequest 时，
    返回JSON格式的响应，包含消息状态和最新的未读消息计数。
    """
    manor = ensure_manor(request.user)
    message = get_object_or_404(
        manor.messages.select_related("battle_report"),
        pk=pk,
    )

    # 检测是否为JSON/AJAX请求
    is_json_request = (
        "application/json" in request.headers.get("Accept", "").lower()
        or request.headers.get("X-Requested-With") == "XMLHttpRequest"
    )

    # 标记为已读（只有在消息未读时才执行）
    was_unread = not message.is_read
    if was_unread:
        mark_messages_read(manor, [message.pk])
        message.refresh_from_db()

    # 对于JSON请求，返回结构化的响应数据
    if is_json_request:
        response_data = {
            "success": True,
            "message_id": message.pk,
            "was_unread": was_unread,
            "unread_count": unread_message_count(manor),
        }

        if message.battle_report_id:
            response_data["redirect_url"] = reverse(
                "battle:report_detail",
                kwargs={"pk": message.battle_report_id}
            )

        return JsonResponse(response_data)

    # 战报消息跳转到战报详情
    if message.battle_report_id:
        return redirect("battle:report_detail", pk=message.battle_report_id)

    # 准备附件详细信息
    attachment_details = {
        'resources': [],
        'items': []
    }

    if message.has_attachments:
        attachments = message.attachments or {}
        if message.is_claimed:
            claimed = attachments.get("claimed")
            if isinstance(claimed, dict):
                attachments = claimed

        # 资源详情
        resources = attachments.get("resources", {})
        resource_labels = dict(ResourceType.choices)
        for key, amount in resources.items():
            attachment_details['resources'].append({
                'key': key,
                'name': resource_labels.get(key, key),
                'amount': amount
            })

        # 道具详情（批量预加载物品模板，避免N+1查询）
        items = attachments.get("items", {})
        item_keys = list(items.keys())
        if item_keys:
            from ..utils.template_loader import get_item_templates_by_keys
            item_templates_map = get_item_templates_by_keys(item_keys)
        else:
            item_templates_map = {}
        for item_key, quantity in items.items():
            item_template = item_templates_map.get(item_key)
            if item_template:
                attachment_details['items'].append({
                    'key': item_key,
                    'name': item_template.name,
                    'icon': item_template.icon,
                    'image': item_template.image,
                    'quantity': quantity
                })
            else:
                attachment_details['items'].append({
                    'key': item_key,
                    'name': item_key,
                    'icon': None,
                    'image': None,
                    'quantity': quantity
                })

    context = {
        'message': message,
        'attachment_details': attachment_details,
    }

    return render(request, 'gameplay/message_detail.html', context)


@login_required
@require_POST
def delete_messages_view(request: HttpRequest) -> HttpResponse:
    """Delete only the messages that have been selected via checkboxes."""
    manor = ensure_manor(request.user)
    ids = request.POST.getlist("message_ids")
    if ids:
        delete_messages(manor, ids)
        messages.success(request, f"已删除 {len(ids)} 条消息")
    else:
        messages.info(request, "请先选择需要删除的消息")
    return redirect("gameplay:messages")


@login_required
@require_POST
def delete_all_messages_view(request: HttpRequest) -> HttpResponse:
    """Handle the 'one click clear' button."""
    manor = ensure_manor(request.user)
    delete_all_messages(manor)
    messages.info(request, "所有消息已清空")
    return redirect("gameplay:messages")


@login_required
@require_POST
def mark_messages_read_view(request: HttpRequest) -> HttpResponse:
    """Mark the selected messages as read without deleting them."""
    manor = ensure_manor(request.user)
    ids = request.POST.getlist("message_ids")
    if ids:
        mark_messages_read(manor, ids)
        messages.success(request, f"已标记 {len(ids)} 条消息为已读")
    else:
        messages.info(request, "请先选择需要标记的消息")
    return redirect("gameplay:messages")


@login_required
@require_POST
def mark_all_messages_read_view(request: HttpRequest) -> HttpResponse:
    """Mark every stored message as read."""
    manor = ensure_manor(request.user)
    mark_all_messages_read(manor)
    messages.success(request, "已全部标记为已读")
    return redirect("gameplay:messages")


@login_required
@require_POST
def claim_attachment_view(request: HttpRequest, pk: int) -> HttpResponse:
    """
    领取消息附件。

    将附件中的资源和道具发放到玩家账户。
    """
    manor = ensure_manor(request.user)
    message = get_object_or_404(
        manor.messages,
        pk=pk,
    )

    try:
        claimed_summary = claim_message_attachments(message)

        # 格式化领取摘要
        resource_labels = dict(ResourceType.choices)
        parts = []

        # 收集所有物品 key，批量查询
        item_keys_to_lookup = [
            key[5:] for key in claimed_summary.keys() if key.startswith("item_")
        ]
        if item_keys_to_lookup:
            from ..utils.template_loader import get_item_templates_by_keys
            item_templates_map = get_item_templates_by_keys(item_keys_to_lookup)
        else:
            item_templates_map = {}

        for key, value in claimed_summary.items():
            if key.startswith("item_"):
                item_key = key[5:]  # 移除 "item_" 前缀
                item_template = item_templates_map.get(item_key)
                if item_template:
                    parts.append(f"{item_template.name}×{value}")
            else:
                label = resource_labels.get(key, key)
                parts.append(f"{label}×{value}")

        summary_text = "、".join(parts) if parts else "附件"
        messages.success(request, f"附件领取成功：{summary_text}")
    except ValueError as exc:
        messages.error(request, str(exc))

    # Check the referer to decide where to redirect
    referer = request.META.get('HTTP_REFERER', '')
    if 'messages/' in referer and 'view' not in referer:
        return redirect("gameplay:messages")
    else:
        return redirect("gameplay:view_message", pk=pk)
