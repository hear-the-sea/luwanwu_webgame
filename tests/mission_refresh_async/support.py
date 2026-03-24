from __future__ import annotations

import builtins
from types import SimpleNamespace


class DueRunsManager:
    def __init__(self, ids):
        self.ids = ids

    def filter(self, **_kwargs):
        return self

    def values_list(self, *_args, **_kwargs):
        return list(self.ids)


class RunObjects:
    def __init__(self, runs):
        self._runs = list(runs)
        self._selected = list(runs)

    def select_related(self, *_args, **_kwargs):
        return self

    def prefetch_related(self, *_args, **_kwargs):
        return self

    def filter(self, **kwargs):
        selected_ids = kwargs.get("id__in")
        if selected_ids is None:
            self._selected = list(self._runs)
        else:
            selected_set = set(selected_ids)
            self._selected = [run for run in self._runs if run.id in selected_set]
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def __iter__(self):
        return iter(self._selected)


def build_mission_run_cls(runs):
    class _Status:
        ACTIVE = "active"

    return type("_MissionRun", (), {"Status": _Status, "objects": RunObjects(runs)})


def patch_import(monkeypatch, handler):
    original_import = builtins.__import__

    def _raising_import(name, globals=None, locals=None, fromlist=(), level=0):
        result = handler(name, globals, locals, fromlist, level, original_import)
        if result is _IMPORT_SENTINEL:
            return original_import(name, globals, locals, fromlist, level)
        return result

    monkeypatch.setattr(builtins, "__import__", _raising_import)


def missing_module_error(name: str, *, target: str | None = None) -> ModuleNotFoundError:
    error = ModuleNotFoundError(f"No module named '{name}'")
    error.name = target or name
    return error


def mission_run(run_id: int, **kwargs):
    return SimpleNamespace(id=run_id, **kwargs)


_IMPORT_SENTINEL = object()
