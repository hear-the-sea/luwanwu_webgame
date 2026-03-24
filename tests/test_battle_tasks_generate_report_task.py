"""
Compatibility entrypoint for battle generate_report_task tests.

The original file exceeded the audit size threshold. Tests now live in
`tests/battle_tasks_generate_report_task/` submodules while this path remains
stable for existing pytest commands and CI references.
"""

from tests.battle_tasks_generate_report_task.defense_inputs import *  # noqa: F401,F403
from tests.battle_tasks_generate_report_task.guest_snapshots import *  # noqa: F401,F403
from tests.battle_tasks_generate_report_task.offense_inputs import *  # noqa: F401,F403
from tests.battle_tasks_generate_report_task.task_boundaries import *  # noqa: F401,F403
