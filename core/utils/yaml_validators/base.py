"""Base validation types and generic field-level validator helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Validation result types
# ---------------------------------------------------------------------------


@dataclass
class ValidationError:
    """A single validation error with file context."""

    file: str
    path: str
    message: str

    def __str__(self) -> str:
        return f"[{self.file}] {self.path}: {self.message}"


@dataclass
class ValidationResult:
    """Aggregated validation result for one or more config files."""

    errors: list[ValidationError] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    def add(self, file: str, path: str, message: str) -> None:
        self.errors.append(ValidationError(file=file, path=path, message=message))

    def merge(self, other: ValidationResult) -> None:
        self.errors.extend(other.errors)


# ---------------------------------------------------------------------------
# Generic field-level validators
# ---------------------------------------------------------------------------


def _check_required_fields(
    entry: dict,
    required: list[str],
    *,
    result: ValidationResult,
    file: str,
    path: str,
) -> bool:
    """Return True if all required fields are present and non-None."""
    ok = True
    for field_name in required:
        if field_name not in entry or entry[field_name] is None:
            result.add(file, path, f"missing required field '{field_name}'")
            ok = False
    return ok


def _check_type(
    value: Any,
    expected_type: type | tuple[type, ...],
    *,
    result: ValidationResult,
    file: str,
    path: str,
    field_name: str,
) -> bool:
    if not isinstance(value, expected_type):
        actual = type(value).__name__
        expected = (
            expected_type.__name__ if isinstance(expected_type, type) else " | ".join(t.__name__ for t in expected_type)
        )
        result.add(file, path, f"field '{field_name}' expected {expected}, got {actual}")
        return False
    return True


def _check_in(
    value: Any,
    allowed: set | list | tuple,
    *,
    result: ValidationResult,
    file: str,
    path: str,
    field_name: str,
) -> bool:
    if value not in allowed:
        result.add(file, path, f"field '{field_name}' value '{value}' not in allowed set {sorted(allowed)}")
        return False
    return True


def _check_positive(
    value: Any,
    *,
    result: ValidationResult,
    file: str,
    path: str,
    field_name: str,
    allow_zero: bool = True,
) -> bool:
    if not isinstance(value, (int, float)):
        return True  # type check handles this separately
    lower = 0 if allow_zero else 1
    if value < lower:
        result.add(file, path, f"field '{field_name}' must be >= {lower}, got {value}")
        return False
    return True


def _check_unique_keys(
    items: list[dict],
    key_field: str,
    *,
    result: ValidationResult,
    file: str,
    context: str,
) -> None:
    """Ensure key_field values are unique across the list."""
    seen: dict[str, int] = {}
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        key = item.get(key_field)
        if key is None:
            continue
        if key in seen:
            result.add(
                file,
                f"{context}[{idx}]",
                f"duplicate {key_field} '{key}' (first seen at index {seen[key]})",
            )
        else:
            seen[key] = idx
