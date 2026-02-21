"""
门客视图模块
"""

from .equipment import equip_view, gear_options_view, unequip_view
from .items import use_medicine_item_view
from .recruit import RecruitView, accept_candidate_view, use_magnifying_glass_view
from .roster import GuestDetailView, RosterView, dismiss_guest_view
from .salary import pay_all_salaries_view, pay_salary_view
from .skills import forget_skill_view, learn_skill_view
from .training import TrainView, allocate_points_view, check_training_view, use_experience_item_view

__all__ = [
    # roster
    "RosterView",
    "GuestDetailView",
    "dismiss_guest_view",
    # recruit
    "RecruitView",
    "accept_candidate_view",
    "use_magnifying_glass_view",
    # training
    "TrainView",
    "use_experience_item_view",
    "allocate_points_view",
    "check_training_view",
    # equipment
    "equip_view",
    "unequip_view",
    "gear_options_view",
    # skills
    "learn_skill_view",
    "forget_skill_view",
    # items
    "use_medicine_item_view",
    # salary
    "pay_salary_view",
    "pay_all_salaries_view",
]
