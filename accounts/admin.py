from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from core.admin_i18n import apply_common_field_labels

from .models import User

apply_common_field_labels(User, labels={"username": "用户名", "title": "称号"})

admin.site.site_header = "江湖游戏后台管理"
admin.site.site_title = "江湖游戏后台"
admin.site.index_title = "运营管理"


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    fieldsets = DjangoUserAdmin.fieldsets + (("游戏信息", {"fields": ("title",)}),)
    list_display = ("username", "email", "title", "is_staff", "date_joined")
    search_fields = ("username", "email", "title")
