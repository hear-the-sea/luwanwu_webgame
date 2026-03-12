from __future__ import annotations

from django.db.models import F
from django.utils import timezone


def send_purchase_notifications(
    *,
    buyer,
    listing,
    tax_amount: int,
    seller_received: int,
    safe_create_message,
    safe_notify_user,
) -> tuple[bool, bool]:
    buyer_mail_sent = safe_create_message(
        manor=buyer,
        kind="system",
        title="【交易成功】您购买的物品已送达",
        body=(
            f"恭喜！您成功购买了 {listing.item_template.name} x{listing.quantity}，"
            f"花费 {listing.total_price:,} 银两。\n\n"
            f"物品已直接存入您的仓库，请前往查看。\n\n"
            f"交易详情：\n"
            f"- 物品：{listing.item_template.name}\n"
            f"- 数量：{listing.quantity}\n"
            f"- 单价：{listing.unit_price:,} 银两\n"
            f"- 总价：{listing.total_price:,} 银两\n"
            f"- 卖家：{listing.seller.user.username}\n"
            f"- 成交时间：{listing.sold_at.strftime('%Y-%m-%d %H:%M:%S')}"
        ),
    )

    seller_mail_sent = False
    if listing.seller_id:
        seller_mail_sent = safe_create_message(
            manor=listing.seller,
            kind="system",
            title="【交易成功】您的物品已售出",
            body=(
                f"恭喜！您上架的 {listing.item_template.name} x{listing.quantity} 已成功售出！\n\n"
                f"银两已直接存入您的账户。\n\n"
                f"交易详情：\n"
                f"- 物品：{listing.item_template.name}\n"
                f"- 数量：{listing.quantity}\n"
                f"- 成交价：{listing.total_price:,} 银两\n"
                f"- 税费（10%）：{tax_amount:,} 银两\n"
                f"- 实际到账：{seller_received:,} 银两\n"
                f"- 买家：{buyer.user.username}\n"
                f"- 成交时间：{listing.sold_at.strftime('%Y-%m-%d %H:%M:%S')}"
            ),
        )

        safe_notify_user(
            listing.seller.user_id,
            {
                "kind": "market_sold",
                "title": "【交易成功】您的物品已售出",
                "item_name": listing.item_template.name,
                "item_key": listing.item_template.key,
                "quantity": listing.quantity,
                "silver_received": seller_received,
            },
            log_context="market sold notification",
        )

    return buyer_mail_sent, seller_mail_sent


def restore_cancelled_listing_inventory(*, inventory_item_model, manor, listing) -> None:
    inventory_item = (
        inventory_item_model.objects.select_for_update()
        .filter(
            manor=manor,
            template=listing.item_template,
            storage_location=inventory_item_model.StorageLocation.WAREHOUSE,
        )
        .first()
    )

    if inventory_item:
        inventory_item_model.objects.filter(pk=inventory_item.pk).update(
            quantity=F("quantity") + listing.quantity,
            updated_at=timezone.now(),
        )
        return

    inventory_item_model.objects.create(
        manor=manor,
        template=listing.item_template,
        storage_location=inventory_item_model.StorageLocation.WAREHOUSE,
        quantity=listing.quantity,
    )


def build_cancel_listing_result(*, listing) -> dict[str, object]:
    return {
        "item_name": listing.item_template.name,
        "quantity": listing.quantity,
    }
