import pytest
from django.db import DatabaseError
from django.urls import reverse

from core.exceptions import ForgeOperationError
from tests.forge_views.support import assert_forge_redirect, response_messages


@pytest.mark.django_db
class TestDecomposeEquipmentView:
    def test_decompose_equipment_view_redirects_with_category(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user

        monkeypatch.setattr(
            "gameplay.services.buildings.forge.decompose_equipment",
            lambda *_a, **_k: {
                "equipment_key": "equip_dummy",
                "equipment_name": "测试装备",
                "quantity": 2,
                "rewards": {},
            },
        )

        response = client.post(
            reverse("gameplay:decompose_equipment"),
            data={"equipment_key": "equip_dummy", "quantity": "2", "category": "helmet"},
        )
        assert_forge_redirect(response, mode="decompose", category="helmet")

    def test_decompose_equipment_database_error_does_not_500(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user

        monkeypatch.setattr(
            "gameplay.services.buildings.forge.decompose_equipment",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(DatabaseError("db down")),
        )

        response = client.post(
            reverse("gameplay:decompose_equipment"),
            data={"equipment_key": "equip_dummy", "quantity": "1", "category": "helmet", "mode": "decompose"},
        )
        assert_forge_redirect(response, mode="decompose", category="helmet")
        assert any("操作失败，请稍后重试" in message for message in response_messages(response))

    def test_decompose_equipment_rejects_invalid_quantity(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user
        called = {"count": 0}

        def _unexpected_decompose(*_args, **_kwargs):
            called["count"] += 1

        monkeypatch.setattr("gameplay.services.buildings.forge.decompose_equipment", _unexpected_decompose)

        response = client.post(
            reverse("gameplay:decompose_equipment"),
            data={"equipment_key": "equip_dummy", "quantity": "-1", "category": "helmet", "mode": "decompose"},
        )
        assert_forge_redirect(response, mode="decompose", category="helmet")
        assert any("无效的数量" in message for message in response_messages(response))
        assert called["count"] == 0

    def test_decompose_equipment_programming_error_bubbles_up(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user
        monkeypatch.setattr(
            "gameplay.services.buildings.forge.decompose_equipment",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        with pytest.raises(RuntimeError, match="boom"):
            client.post(
                reverse("gameplay:decompose_equipment"),
                data={"equipment_key": "equip_dummy", "quantity": "1", "category": "helmet", "mode": "decompose"},
            )

    def test_decompose_equipment_known_error_shows_message(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user
        monkeypatch.setattr(
            "gameplay.services.buildings.forge.decompose_equipment",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(ForgeOperationError("decompose blocked")),
        )

        response = client.post(
            reverse("gameplay:decompose_equipment"),
            data={"equipment_key": "equip_dummy", "quantity": "1", "category": "helmet", "mode": "decompose"},
        )
        assert_forge_redirect(response, mode="decompose", category="helmet")
        assert any("decompose blocked" in message for message in response_messages(response))

    def test_decompose_equipment_legacy_value_error_bubbles_up(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user
        monkeypatch.setattr(
            "gameplay.services.buildings.forge.decompose_equipment",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("legacy decompose blocked")),
        )

        with pytest.raises(ValueError, match="legacy decompose blocked"):
            client.post(
                reverse("gameplay:decompose_equipment"),
                data={"equipment_key": "equip_dummy", "quantity": "1", "category": "helmet", "mode": "decompose"},
            )
