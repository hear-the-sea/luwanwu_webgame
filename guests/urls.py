from django.urls import path

from .views import (
    GuestDetailView,
    RecruitView,
    RosterView,
    TrainView,
    accept_candidate_view,
    dismiss_guest_view,
    equip_view,
    gear_options_view,
    unequip_view,
    forget_skill_view,
    learn_skill_view,
    allocate_points_view,
    use_experience_item_view,
    use_medicine_item_view,
    use_magnifying_glass_view,
    pay_salary_view,
    pay_all_salaries_view,
    check_training_view,
)

app_name = "guests"

urlpatterns = [
    path("", RosterView.as_view(), name="roster"),
    path("<int:pk>/", GuestDetailView.as_view(), name="detail"),
    path("<int:pk>/dismiss/", dismiss_guest_view, name="dismiss"),
    path("<int:pk>/learn-skill/", learn_skill_view, name="learn_skill"),
    path("<int:pk>/forget-skill/", forget_skill_view, name="forget_skill"),
    path("<int:pk>/allocate-points/", allocate_points_view, name="allocate_points"),
    path("<int:pk>/use-exp-item/", use_experience_item_view, name="use_exp_item"),
    path("<int:pk>/use-medicine/", use_medicine_item_view, name="use_medicine_item"),
    path("<int:pk>/pay-salary/", pay_salary_view, name="pay_salary"),
    path("<int:pk>/check-training/", check_training_view, name="check_training"),
    path("recruit/", RecruitView.as_view(), name="recruit"),
    path("train/", TrainView.as_view(), name="train"),
    path("equip/", equip_view, name="equip"),
    path("gear-options/", gear_options_view, name="gear_options"),
    path("unequip/", unequip_view, name="unequip"),
    path("candidates/accept/", accept_candidate_view, name="candidate_accept"),
    path("candidates/reveal/", use_magnifying_glass_view, name="use_magnifying_glass"),
    path("pay-all-salaries/", pay_all_salaries_view, name="pay_all_salaries"),
]
