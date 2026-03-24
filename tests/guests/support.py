from __future__ import annotations

import builtins

from gameplay.services.manor.core import ensure_manor
from guests.models import RecruitmentPool


def create_manor(django_user_model, *, username: str, silver: int | None = None, grain: int | None = None):
    user = django_user_model.objects.create_user(username=username, password="pass123")
    manor = ensure_manor(user)
    update_fields = []
    if silver is not None and manor.silver != silver:
        manor.silver = silver
        update_fields.append("silver")
    if grain is not None and manor.grain != grain:
        manor.grain = grain
        update_fields.append("grain")
    if update_fields:
        manor.save(update_fields=update_fields)
    return manor


def get_pool(key: str = "cunmu") -> RecruitmentPool:
    return RecruitmentPool.objects.get(key=key)


def patch_import(monkeypatch, handler):
    original_import = builtins.__import__

    def _raising_import(name, globals=None, locals=None, fromlist=(), level=0):
        return handler(name, globals, locals, fromlist, level, original_import)

    monkeypatch.setattr(builtins, "__import__", _raising_import)


def missing_module_error(name: str, *, target: str | None = None) -> ModuleNotFoundError:
    error = ModuleNotFoundError(f"No module named '{name}'")
    error.name = target or name
    return error
