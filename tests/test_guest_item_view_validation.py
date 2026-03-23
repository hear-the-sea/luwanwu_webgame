"""
Compatibility entrypoint for guest item view validation tests.

The original file exceeded the audit size threshold. Tests now live in
`tests/guest_item_view_validation/` submodules while this path remains stable
for existing pytest commands and CI references.
"""

from tests.guest_item_view_validation.gear_views import *  # noqa: F401,F403
from tests.guest_item_view_validation.item_usage_views import *  # noqa: F401,F403
from tests.guest_item_view_validation.recruitment_views import *  # noqa: F401,F403
from tests.guest_item_view_validation.skill_views import *  # noqa: F401,F403
