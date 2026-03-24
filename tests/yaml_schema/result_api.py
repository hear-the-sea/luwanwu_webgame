from __future__ import annotations

from core.utils.yaml_schema import ValidationResult


class TestValidationResultAPI:
    def test_empty_result_is_valid(self):
        result = ValidationResult()
        assert result.is_valid
        assert len(result.errors) == 0

    def test_add_makes_invalid(self):
        result = ValidationResult()
        result.add("file.yaml", "path", "something wrong")
        assert not result.is_valid
        assert len(result.errors) == 1

    def test_merge(self):
        first = ValidationResult()
        first.add("a.yaml", "x", "err1")
        second = ValidationResult()
        second.add("b.yaml", "y", "err2")
        first.merge(second)
        assert len(first.errors) == 2

    def test_error_str(self):
        result = ValidationResult()
        result.add("test.yaml", "items[0]", "bad value")
        assert "[test.yaml] items[0]: bad value" in str(result.errors[0])
