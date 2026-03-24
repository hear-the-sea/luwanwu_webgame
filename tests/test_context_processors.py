"""
Compatibility entrypoint for context processor tests.

The original file exceeded the audit size threshold. Tests now live in
`tests/context_processors/` submodules while this path remains stable for
existing pytest commands and CI references.
"""

from tests.context_processors.anonymous_stats import *  # noqa: F401,F403
from tests.context_processors.authenticated_sidebar import *  # noqa: F401,F403
from tests.context_processors.online_presence import *  # noqa: F401,F403
