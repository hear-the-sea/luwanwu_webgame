"""
Compatibility entrypoint for mission view tests.

The original file exceeded the audit size threshold. Tests now live in
`tests/mission_views/` submodules while this path remains stable for existing
pytest commands and CI references.
"""

from tests.mission_views.accept_mission import *  # noqa: F401,F403
from tests.mission_views.mission_cards import *  # noqa: F401,F403
from tests.mission_views.retreat_actions import *  # noqa: F401,F403
from tests.mission_views.task_board import *  # noqa: F401,F403
