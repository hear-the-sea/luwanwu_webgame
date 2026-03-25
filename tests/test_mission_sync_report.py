"""
Compatibility entrypoint for mission sync report tests.

The original file exceeded the audit size threshold. Tests now live in
`tests/mission_sync_report/` submodules while this path remains stable for
existing pytest commands and CI references.
"""

from tests.mission_sync_report.defense_validation import *  # noqa: F401,F403
from tests.mission_sync_report.offense_drop_table import *  # noqa: F401,F403
