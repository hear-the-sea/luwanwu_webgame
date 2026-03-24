from __future__ import annotations

import pytest

from core.exceptions import GuildValidationError
from gameplay.models import InventoryItem
from guilds.models import GuildMember
from guilds.services import guild as guild_service

pytest_plugins = ("tests.guilds.conftest",)


@pytest.mark.django_db
class TestGuildCreation:
    def test_create_guild_success(self, user_with_gold_bars):
        guild = guild_service.create_guild(user=user_with_gold_bars, name="测试帮会", description="这是一个测试帮会")

        assert guild is not None
        assert guild.name == "测试帮会"
        assert guild.level == 1
        assert guild.is_active is True

        membership = GuildMember.objects.get(user=user_with_gold_bars, guild=guild)
        assert membership.position == "leader"
        assert membership.is_active is True
        assert guild.technologies.count() == 7

    def test_create_guild_duplicate_name(self, user_with_gold_bars, django_user_model, gold_bar_template):
        guild_service.create_guild(user=user_with_gold_bars, name="唯一帮会", description="")

        user2 = django_user_model.objects.create_user(username="user2", password="pass12345")
        from gameplay.services.manor.core import ensure_manor

        manor2 = ensure_manor(user2)
        InventoryItem.objects.create(
            manor=manor2,
            template=gold_bar_template,
            quantity=10,
            storage_location="warehouse",
        )

        with pytest.raises(GuildValidationError, match="帮会名称已存在"):
            guild_service.create_guild(user=user2, name="唯一帮会", description="")

    def test_create_guild_invalid_name(self, user_with_gold_bars):
        with pytest.raises(GuildValidationError, match="至少需要"):
            guild_service.create_guild(user=user_with_gold_bars, name="A", description="")

        with pytest.raises(GuildValidationError, match="只能包含"):
            guild_service.create_guild(user=user_with_gold_bars, name="帮会@#$", description="")

    def test_create_guild_insufficient_gold(self, django_user_model, gold_bar_template):
        user = django_user_model.objects.create_user(username="poor_user", password="pass12345")
        from gameplay.services.manor.core import ensure_manor

        ensure_manor(user)

        with pytest.raises(GuildValidationError, match="金条不足"):
            guild_service.create_guild(user=user, name="穷人帮会", description="")
