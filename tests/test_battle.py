"""
Compatibility entrypoint for battle tests.

The original file exceeded the audit size threshold. Tests now live in
`tests/battle/` submodules while this path remains stable for existing pytest
commands and CI references.
"""

from tests.battle.defender_helpers import *  # noqa: F401,F403
from tests.battle.deployment_recovery import *  # noqa: F401,F403
from tests.battle.simulate_report import *  # noqa: F401,F403
from tests.battle.snapshot_validation import *  # noqa: F401,F403
