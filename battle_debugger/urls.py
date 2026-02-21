"""
Battle Debugger URL Configuration
"""

from django.urls import path

from . import views

app_name = "battle_debugger"

urlpatterns = [
    path("", views.index, name="index"),
    path("simulate/", views.simulate, name="simulate"),
    path("custom/", views.custom_config, name="custom_config"),
    path("result/<str:result_id>/", views.result_detail, name="result_detail"),
    path("tune/", views.tune, name="tune"),
    path("presets/<str:preset_name>/", views.preset_detail, name="preset_detail"),
    # API接口
    path("api/guests/", views.api_guests, name="api_guests"),
    path("api/skills/", views.api_skills, name="api_skills"),
    path("api/troops/", views.api_troops, name="api_troops"),
]
