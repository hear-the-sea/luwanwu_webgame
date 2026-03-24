"""
Compatibility entrypoint for forge view tests.

The original file exceeded the audit size threshold. Tests now live in
`tests/forge_views/` submodules while this path remains stable for existing
pytest commands and CI references.
"""

from tests.forge_views.blueprint_actions import *  # noqa: F401,F403
from tests.forge_views.decompose_actions import *  # noqa: F401,F403
from tests.forge_views.forging_actions import *  # noqa: F401,F403
from tests.forge_views.page_context import *  # noqa: F401,F403
