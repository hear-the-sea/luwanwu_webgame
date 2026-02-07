from __future__ import annotations

GOLD_BAR_ITEM_KEY = "gold_bar"

AUCTION_CREATE_LOCK_KEY = "trade:auction:create_round:lock"
AUCTION_CREATE_LOCK_TIMEOUT = 30

AUCTION_SETTLE_LOCK_KEY = "trade:auction:settle_round:lock"
AUCTION_SETTLE_LOCK_TIMEOUT = 300

# 拍卖位排序字段白名单（防止 order_by 注入）
ALLOWED_AUCTION_ORDER_BY = {
    "current_price",
    "-current_price",
    "starting_price",
    "-starting_price",
    "min_increment",
    "-min_increment",
    "bid_count",
    "-bid_count",
    "created_at",
    "-created_at",
}
