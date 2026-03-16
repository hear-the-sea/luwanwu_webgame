from __future__ import annotations

from io import StringIO

import pytest
from django.conf import settings
from django.core.management import call_command

from core.utils.yaml_schema import get_supported_yaml_configs


@pytest.mark.django_db
def test_validate_yaml_configs_reports_all_supported_files():
    """All 22 YAML configs are now covered; no skipped files expected."""
    stdout = StringIO()

    call_command(
        "validate_yaml_configs",
        data_dir=str(settings.BASE_DIR / "data"),
        dry_run=True,
        stdout=stdout,
    )

    output = stdout.getvalue()
    assert "Validated" in output
    assert "supported YAML config file" in output
    # No files should be skipped once all 22 configs have schema coverage
    assert "Skipped YAML files without schema coverage" not in output


def test_validate_yaml_configs_strict_coverage_fails_for_unsupported_files(tmp_path):
    for filename in get_supported_yaml_configs():
        (tmp_path / filename).write_text("{}", encoding="utf-8")
    (tmp_path / "unsupported.yaml").write_text("key: value\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="1"):
        call_command("validate_yaml_configs", data_dir=str(tmp_path), strict_coverage=True)
