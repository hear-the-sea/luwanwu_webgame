from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    fieldsets = DjangoUserAdmin.fieldsets + (("游戏信息", {"fields": ("title",)}),)
    list_display = ("username", "email", "title", "is_staff", "date_joined")
    search_fields = ("username", "email", "title")
