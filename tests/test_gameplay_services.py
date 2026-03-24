"""
Compatibility entrypoint for gameplay service tests.

The original file exceeded the audit size threshold. Tests now live in
`tests/gameplay_services/` submodules while this path remains stable for
existing pytest commands and CI references.
"""

from tests.gameplay_services.manor_bootstrap import *  # noqa: F401,F403
from tests.gameplay_services.resource_flows import *  # noqa: F401,F403
