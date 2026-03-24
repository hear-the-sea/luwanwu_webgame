from __future__ import annotations

import pytest
from django.db import DatabaseError
from django.urls import reverse

from core.exceptions import OathBondError
from tests.jail_views.support import message_objects, oath_url, response_messages


@pytest.mark.django_db
class TestJailAndOathViews:
    def test_recruit_prisoner_view_rejects_when_action_lock_conflicts(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user
        called = {"count": 0}

        monkeypatch.setattr("gameplay.views.jail._acquire_jail_action_lock", lambda *_a, **_k: (False, "", None))

        def _unexpected_recruit(*_args, **_kwargs):
            called["count"] += 1

        monkeypatch.setattr("gameplay.views.jail.recruit_prisoner", _unexpected_recruit)

        response = client.post(reverse("gameplay:recruit_prisoner_view", kwargs={"prisoner_id": 1}))
        assert response.status_code == 302
        assert response.url == reverse("gameplay:jail")
        messages = message_objects(response)
        assert any(
            message.level_tag == "warning" and "请求处理中，请稍候重试" in message.message for message in messages
        )
        assert called["count"] == 0

    def test_add_oath_bond_view_database_error_does_not_500(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user

        monkeypatch.setattr(
            "gameplay.views.jail.add_oath_bond",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(DatabaseError("db down")),
        )

        response = client.post(reverse("gameplay:add_oath_bond_view"), {"guest_id": 1})
        assert response.status_code == 302
        assert response.url == oath_url()
        messages = response_messages(response)
        assert any("操作失败，请稍后重试" in message for message in messages)

    def test_add_oath_bond_view_known_game_error_shows_message(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user

        monkeypatch.setattr(
            "gameplay.views.jail.add_oath_bond",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(OathBondError("bond blocked")),
        )

        response = client.post(reverse("gameplay:add_oath_bond_view"), {"guest_id": 1})
        assert response.status_code == 302
        assert response.url == oath_url()
        messages = response_messages(response)
        assert any("bond blocked" in message for message in messages)

    def test_add_oath_bond_view_value_error_bubbles_up(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user

        monkeypatch.setattr(
            "gameplay.views.jail.add_oath_bond",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("bad payload")),
        )

        with pytest.raises(ValueError, match="bad payload"):
            client.post(reverse("gameplay:add_oath_bond_view"), {"guest_id": 1})

    def test_add_oath_bond_view_programming_error_bubbles_up(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user

        monkeypatch.setattr(
            "gameplay.views.jail.add_oath_bond",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        with pytest.raises(RuntimeError, match="boom"):
            client.post(reverse("gameplay:add_oath_bond_view"), {"guest_id": 1})

    def test_remove_oath_bond_view_uses_error_message_when_guest_not_bonded(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user

        monkeypatch.setattr("gameplay.views.jail.remove_oath_bond", lambda *_args, **_kwargs: 0)

        response = client.post(reverse("gameplay:remove_oath_bond_view", kwargs={"guest_id": 1}))
        assert response.status_code == 302
        assert response.url == oath_url()
        messages = message_objects(response)
        assert any(message.level_tag == "error" and "该门客未结义" in message.message for message in messages)
