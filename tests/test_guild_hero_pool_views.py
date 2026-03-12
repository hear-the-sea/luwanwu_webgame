from __future__ import annotations

from types import SimpleNamespace

import pytest
from django.contrib.messages import get_messages
from django.test import Client
from django.urls import reverse

from gameplay.services.manor.core import ensure_manor
from guilds.models import Guild, GuildMember


@pytest.fixture
def guild_member_client(django_user_model):
    user = django_user_model.objects.create_user(username="ghp_view_leader", password="pass12345")
    ensure_manor(user)
    guild = Guild.objects.create(name="门客池视图帮", founder=user, is_active=True)
    GuildMember.objects.create(guild=guild, user=user, position="leader")

    client = Client()
    assert client.login(username="ghp_view_leader", password="pass12345")
    return client, user, guild


@pytest.mark.django_db
def test_hero_pool_submit_invalid_params_show_error(guild_member_client):
    client, _user, _guild = guild_member_client

    response = client.post(reverse("guilds:hero_pool_submit"), {"slot_index": "x"}, follow=True)

    messages = [str(message) for message in get_messages(response.wsgi_request)]
    assert response.redirect_chain
    assert messages[-1] == "参数错误"


@pytest.mark.django_db
def test_hero_pool_submit_success_message_uses_unified_helper(guild_member_client, monkeypatch):
    client, _user, _guild = guild_member_client

    result = SimpleNamespace(
        replaced=True,
        entry=SimpleNamespace(slot_index=2),
        lineup_removed_count=1,
    )
    monkeypatch.setattr("guilds.views.hero_pool.hero_pool_service.submit_hero_pool_entry", lambda *_a, **_k: result)

    response = client.post(reverse("guilds:hero_pool_submit"), {"slot_index": 2, "guest_id": 99}, follow=True)

    messages = [str(message) for message in get_messages(response.wsgi_request)]
    assert response.redirect_chain
    assert messages[-1] == "已替换槽位 2 门客（原出战位已自动下阵 1 项）"


@pytest.mark.django_db
def test_lineup_add_value_error_shows_message(guild_member_client, monkeypatch):
    client, _user, _guild = guild_member_client

    def _raise(*_args, **_kwargs):
        raise ValueError("出战名单已满")

    monkeypatch.setattr("guilds.views.hero_pool.hero_pool_service.add_lineup_entry", _raise)

    response = client.post(reverse("guilds:lineup_add"), {"pool_entry_id": 1}, follow=True)

    messages = [str(message) for message in get_messages(response.wsgi_request)]
    assert response.redirect_chain
    assert messages[-1] == "出战名单已满"
