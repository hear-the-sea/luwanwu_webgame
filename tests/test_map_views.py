"""
Compatibility entrypoint for map view tests.

The original file exceeded the audit size threshold. Tests now live in
`tests/map_views/` submodules while this path remains stable for existing
pytest commands and CI references.
"""

from tests.map_views.map_page import *  # noqa: F401,F403
from tests.map_views.raid_api import *  # noqa: F401,F403
from tests.map_views.scout_api import *  # noqa: F401,F403
from tests.map_views.status_api import *  # noqa: F401,F403
