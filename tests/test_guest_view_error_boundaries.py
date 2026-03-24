"""
Compatibility entrypoint for guest view error boundary tests.

The original file exceeded the audit size threshold. Tests now live in
`tests/guest_view_error_boundaries/` submodules while this path remains stable
for existing pytest commands and CI references.
"""

from tests.guest_view_error_boundaries.equipment_views import *  # noqa: F401,F403
from tests.guest_view_error_boundaries.recruit_views import *  # noqa: F401,F403
from tests.guest_view_error_boundaries.roster_views import *  # noqa: F401,F403
from tests.guest_view_error_boundaries.skill_views import *  # noqa: F401,F403
from tests.guest_view_error_boundaries.training_views import *  # noqa: F401,F403
