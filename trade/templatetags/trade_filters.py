"""
Trade app custom template filters
"""

from django import template

register = template.Library()


@register.filter
def format_countdown(seconds):
    """
    格式化倒计时显示

    Args:
        seconds: 剩余秒数

    Returns:
        格式化的时间字符串
    """
    if not seconds or seconds <= 0:
        return "已过期"

    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    if days > 0:
        return f"{days}天{hours}小时"
    elif hours > 0:
        return f"{hours}小时{minutes}分"
    elif minutes > 0:
        return f"{minutes}分{secs}秒"
    else:
        return f"{secs}秒"
