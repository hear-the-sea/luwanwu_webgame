from __future__ import annotations

from trade.templatetags import trade_filters


def test_format_countdown_handles_expired_and_short_windows():
    assert trade_filters.format_countdown(0) == "已过期"
    assert trade_filters.format_countdown(59) == "59秒"


def test_format_countdown_formats_minutes_hours_and_days():
    assert trade_filters.format_countdown(125) == "2分5秒"
    assert trade_filters.format_countdown(3 * 3600 + 5 * 60) == "3小时5分"
    assert trade_filters.format_countdown(2 * 86400 + 4 * 3600) == "2天4小时"
