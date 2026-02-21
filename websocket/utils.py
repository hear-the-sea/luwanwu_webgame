"""
WebSocket 工具函数
"""

from typing import Any, Dict, List


def filter_payload(payload: Dict[str, Any], allowed_fields: List[str]) -> Dict[str, Any]:
    """
    过滤 payload，只保留白名单字段且值不为 None 的项

    Args:
        payload: 原始 payload 字典
        allowed_fields: 允许的字段列表

    Returns:
        过滤后的 payload 字典
    """
    safe_payload = {field: payload.get(field) for field in allowed_fields}
    return {k: v for k, v in safe_payload.items() if v is not None}
