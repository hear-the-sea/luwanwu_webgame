from __future__ import annotations

import ipaddress
from typing import Iterable

from django.conf import settings
from django.http import HttpRequest


def _is_trusted_proxy(remote_addr: str, trusted_proxy_ips: Iterable[str]) -> bool:
    if not remote_addr:
        return False

    try:
        remote_ip = ipaddress.ip_address(remote_addr)
    except ValueError:
        return False

    for raw in trusted_proxy_ips:
        item = (raw or "").strip()
        if not item:
            continue
        try:
            if "/" in item:
                network = ipaddress.ip_network(item, strict=False)
                if remote_ip in network:
                    return True
            else:
                if remote_ip == ipaddress.ip_address(item):
                    return True
        except ValueError:
            continue

    return False


def get_client_ip(request: HttpRequest, *, trust_proxy: bool = False) -> str:
    """
    Get client IP with optional trusted-proxy support.

    When trust_proxy=True, X-Forwarded-For is used only if REMOTE_ADDR belongs
    to TRUSTED_PROXY_IPS.
    """
    remote_addr = request.META.get("REMOTE_ADDR", "")
    if not remote_addr:
        return "unknown"

    if not trust_proxy:
        return remote_addr

    trusted_proxy_ips = getattr(settings, "TRUSTED_PROXY_IPS", [])
    if not _is_trusted_proxy(remote_addr, trusted_proxy_ips):
        return remote_addr

    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if not x_forwarded_for:
        return remote_addr

    for part in x_forwarded_for.split(","):
        candidate = part.strip()
        if not candidate:
            continue
        try:
            ipaddress.ip_address(candidate)
            return candidate
        except ValueError:
            continue

    return remote_addr
