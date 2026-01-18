# Refactor Notes

This document tracks recent maintainability-oriented refactors and the conventions to follow going forward.

## 1) Large File Splits (Backwards Compatible)

### gameplay models
- `gameplay/models.py` was split into a package under `gameplay/models/`.
- Import compatibility is preserved via `gameplay/models/__init__.py` re-exports (existing imports like `from gameplay.models import Manor` still work).

### inventory services
- `gameplay/services/inventory.py` was split into `gameplay/services/inventory/`:
  - `core.py`: CRUD + locking helpers
  - `use.py`: item-use business logic
  - `__init__.py`: re-exports for compatibility and exposes package-level `random` for tests

### raid combat services
- `gameplay/services/raid/combat.py` was split into `gameplay/services/raid/combat/`:
  - `travel.py`, `battle.py`, `loot.py`, `runs.py`
  - `gameplay/services/raid/combat/__init__.py` preserves the original public surface and keeps `random` + `LOOT_*` constants at module level for test monkeypatching.

## 2) Shared Constants

To remove duplicated constant definitions:
- `common/constants/time.py`: `TimeConstants` (shared)
- `common/constants/resources.py`: `ResourceType` / `ResourceTypes` (shared)

Compatibility:
- `gameplay/constants.py` and `guests/constants.py` re-export `TimeConstants`.
- `gameplay/models/manor.py` imports `ResourceType` from `common.constants.resources`, so `gameplay.models.ResourceType` remains consistent.

## 3) Shared Utilities

Cross-app pure helpers live under `common/utils/`:
- `common/utils/loot.py`: `resolve_drop_rewards` (used by both battle/gameplay)
- `common/utils/celery.py`: `safe_apply_async` (best-effort task dispatch wrapper)

Compatibility:
- `gameplay/utils/loot_generator.py` remains as a thin wrapper, so existing imports keep working.

## 4) Import Cycle Guardrail

Run `python scripts/check_import_cycles.py` to detect **top-level** (module import-time) cycles across project packages.

## 5) Verification Commands

- Lint: `python -m ruff check`
- Django checks: `python manage.py check`
- Import cycles: `python scripts/check_import_cycles.py`
- Tests: `pytest`

