from __future__ import annotations

import configparser
from pathlib import Path


def test_pytest_testpaths_include_app_local_test_directories():
    config = configparser.ConfigParser()
    config.read(Path(__file__).resolve().parents[1] / "pytest.ini")

    testpaths = {line.strip() for line in config["pytest"]["testpaths"].splitlines() if line.strip()}

    assert {"tests", "guests/tests"}.issubset(testpaths)
