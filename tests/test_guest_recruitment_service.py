"""
Compatibility entrypoint for guest recruitment service tests.

The original file exceeded the audit size threshold. Tests now live in
`tests/guest_recruitment_service/` submodules while this path remains stable
for existing pytest commands and CI references.
"""

from tests.guest_recruitment_service.attribute_and_cache import *  # noqa: F401,F403
from tests.guest_recruitment_service.candidate_persistence import *  # noqa: F401,F403
from tests.guest_recruitment_service.finalization_refresh import *  # noqa: F401,F403
from tests.guest_recruitment_service.template_selection import *  # noqa: F401,F403
