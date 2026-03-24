"""
Compatibility entrypoint for atomic idempotency tests.

The original file exceeded the audit size threshold. Tests now live in
`tests/atomic_idempotency/` submodules while this path remains stable for
existing pytest commands and CI references.
"""

from tests.atomic_idempotency.building_technology_finalize import *  # noqa: F401,F403
from tests.atomic_idempotency.inventory_idempotency import *  # noqa: F401,F403
from tests.atomic_idempotency.production_finalize import *  # noqa: F401,F403
