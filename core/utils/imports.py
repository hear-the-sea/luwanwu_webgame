from __future__ import annotations


def is_missing_target_import(exc: ImportError, target_module: str) -> bool:
    """
    Return True only when *exc* indicates that *target_module* itself is missing.

    This treats a missing parent package as equivalent to the target being
    unavailable, but does not swallow nested dependency import failures from
    inside the target module.
    """
    missing_name = getattr(exc, "name", None)
    if not missing_name:
        return False
    if missing_name == target_module:
        return True
    return target_module.startswith(f"{missing_name}.")
