"""
Compatibility entrypoint for inventory view tests.

The original file exceeded the audit size threshold. Tests now live in
`tests/inventory_views/` submodules while this path remains stable for existing
pytest commands and CI references.
"""

from tests.inventory_views.guest_item_actions import *  # noqa: F401,F403
from tests.inventory_views.page_context import *  # noqa: F401,F403
from tests.inventory_views.roster_actions import *  # noqa: F401,F403
from tests.inventory_views.treasury_moves import *  # noqa: F401,F403
