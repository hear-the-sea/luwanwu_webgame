"""
Compatibility entrypoint for YAML schema tests.

The original file exceeded the audit size threshold. Tests now live in
`tests/yaml_schema/` submodules while this path remains stable for existing
pytest commands and CI references.
"""

from tests.yaml_schema.arena_trade_rules import *  # noqa: F401,F403
from tests.yaml_schema.core_templates import *  # noqa: F401,F403
from tests.yaml_schema.mission_forge_shop import *  # noqa: F401,F403
from tests.yaml_schema.real_configs import *  # noqa: F401,F403
from tests.yaml_schema.result_api import *  # noqa: F401,F403
