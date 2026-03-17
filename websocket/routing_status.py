from __future__ import annotations

_WEBSOCKET_ROUTING_OK = True
_WEBSOCKET_ROUTING_ERROR = ""


def set_websocket_routing_status(*, ok: bool, error: str = "") -> None:
    global _WEBSOCKET_ROUTING_OK
    global _WEBSOCKET_ROUTING_ERROR

    _WEBSOCKET_ROUTING_OK = bool(ok)
    _WEBSOCKET_ROUTING_ERROR = str(error or "")


def get_websocket_routing_status() -> tuple[bool, str]:
    return _WEBSOCKET_ROUTING_OK, _WEBSOCKET_ROUTING_ERROR
