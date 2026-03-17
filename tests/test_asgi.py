from __future__ import annotations

import builtins
import importlib
import sys
import warnings

import pytest
from django.test import override_settings

from websocket.routing_status import get_websocket_routing_status


@pytest.mark.django_db
@override_settings(DEBUG=True)
def test_asgi_warns_when_websocket_routing_import_fails(monkeypatch):
    original_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "websocket" and "routing" in fromlist:
            raise ImportError("routing boom")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    sys.modules.pop("config.asgi", None)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        importlib.import_module("config.asgi")

    assert any("WebSocket routing disabled: routing boom" in str(item.message) for item in caught)
    assert get_websocket_routing_status() == (False, "routing boom")

    monkeypatch.setattr(builtins, "__import__", original_import)
    sys.modules.pop("config.asgi", None)
    importlib.import_module("config.asgi")
