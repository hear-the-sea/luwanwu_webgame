"""
Compatibility entrypoint for gameplay service tests.

The original file exceeded the audit size threshold. Tests now live in
`tests/gameplay/` submodules while this path remains stable for existing
pytest commands and CI references.
"""

from tests.gameplay.manor_refresh import *  # noqa: F401,F403
from tests.gameplay.mission_flow import *  # noqa: F401,F403
from tests.gameplay.mission_loadout_validation import *  # noqa: F401,F403
from tests.gameplay.resources_upgrade import *  # noqa: F401,F403
