"""
Compatibility entrypoint for integration external service tests.

The original file exceeded the audit size threshold. Tests now live in
`tests/integration/` submodules while this path remains stable for existing
pytest commands and CI references.
"""

from tests.integration.external_services_guild_message import *  # noqa: F401,F403
from tests.integration.external_services_mission_recruitment import *  # noqa: F401,F403
from tests.integration.external_services_raid_scout import *  # noqa: F401,F403
from tests.integration.external_services_trade import *  # noqa: F401,F403
