"""
Compatibility entrypoint for guest service tests.

The original file exceeded the audit size threshold. Tests now live in
`tests/guests/` submodules while this path remains stable for existing pytest
commands and CI references.
"""

from tests.guests.recruitment_finalization import *  # noqa: F401,F403
from tests.guests.recruitment_flow import *  # noqa: F401,F403
from tests.guests.recruitment_scheduling import *  # noqa: F401,F403
from tests.guests.training_and_candidates import *  # noqa: F401,F403
