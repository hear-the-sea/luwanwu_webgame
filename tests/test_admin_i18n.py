import re

from django.apps import apps
from django.contrib import admin
from django.contrib.admin.utils import label_for_field

TARGET_APP_LABELS = {"accounts", "battle", "gameplay", "guests", "guilds", "trade"}
ASCII_RE = re.compile(r"[A-Za-z]")


def test_admin_app_verbose_names_are_chinese():
    issues = []
    for app_label in sorted(TARGET_APP_LABELS):
        app_config = apps.get_app_config(app_label)
        if ASCII_RE.search(app_config.verbose_name):
            issues.append(f"{app_label}: {app_config.verbose_name}")
    assert not issues, "后台应用分组仍含英文:\n" + "\n".join(issues)


def test_admin_list_display_labels_are_chinese():
    issues = []
    for model, model_admin in admin.site._registry.items():
        if model._meta.app_label not in TARGET_APP_LABELS:
            continue
        for field_name in getattr(model_admin, "list_display", ()):
            label = label_for_field(field_name, model, model_admin)
            if isinstance(label, str) and ASCII_RE.search(label):
                issues.append(f"{model._meta.label}.{field_name} -> {label}")
    assert not issues, "后台列表列名仍含英文:\n" + "\n".join(sorted(issues))
