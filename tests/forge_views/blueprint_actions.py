import pytest
from django.db import DatabaseError
from django.urls import reverse

from core.exceptions import ForgeOperationError
from tests.forge_views.support import assert_forge_redirect, response_messages


@pytest.mark.django_db
class TestSynthesizeBlueprintEquipmentView:
    def test_synthesize_blueprint_equipment_view_redirects_with_category(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user

        monkeypatch.setattr(
            "gameplay.services.buildings.forge.synthesize_equipment_with_blueprint",
            lambda *_a, **_k: {
                "blueprint_key": "bp_dummy",
                "result_key": "equip_dummy",
                "result_name": "测试装备",
                "quantity": 1,
                "craft_times": 1,
            },
        )

        response = client.post(
            reverse("gameplay:synthesize_blueprint_equipment"),
            data={"blueprint_key": "bp_dummy", "quantity": "1", "category": "helmet"},
        )
        assert_forge_redirect(response, mode="synthesize", category="helmet")

    def test_synthesize_blueprint_equipment_database_error_does_not_500(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user

        monkeypatch.setattr(
            "gameplay.services.buildings.forge.synthesize_equipment_with_blueprint",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(DatabaseError("db down")),
        )

        response = client.post(
            reverse("gameplay:synthesize_blueprint_equipment"),
            data={"blueprint_key": "bp_dummy", "quantity": "1", "category": "helmet", "mode": "synthesize"},
        )
        assert_forge_redirect(response, mode="synthesize", category="helmet")
        assert any("操作失败，请稍后重试" in message for message in response_messages(response))

    def test_synthesize_blueprint_equipment_rejects_invalid_quantity(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user
        called = {"count": 0}

        def _unexpected_synthesize(*_args, **_kwargs):
            called["count"] += 1

        monkeypatch.setattr(
            "gameplay.services.buildings.forge.synthesize_equipment_with_blueprint",
            _unexpected_synthesize,
        )

        response = client.post(
            reverse("gameplay:synthesize_blueprint_equipment"),
            data={"blueprint_key": "bp_dummy", "quantity": "bad", "category": "helmet", "mode": "synthesize"},
        )
        assert_forge_redirect(response, mode="synthesize", category="helmet")
        assert any("无效的数量" in message for message in response_messages(response))
        assert called["count"] == 0

    def test_synthesize_blueprint_equipment_programming_error_bubbles_up(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user
        monkeypatch.setattr(
            "gameplay.services.buildings.forge.synthesize_equipment_with_blueprint",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        with pytest.raises(RuntimeError, match="boom"):
            client.post(
                reverse("gameplay:synthesize_blueprint_equipment"),
                data={"blueprint_key": "bp_dummy", "quantity": "1", "category": "helmet", "mode": "synthesize"},
            )

    def test_synthesize_blueprint_equipment_known_error_shows_message(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user
        monkeypatch.setattr(
            "gameplay.services.buildings.forge.synthesize_equipment_with_blueprint",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(ForgeOperationError("blueprint blocked")),
        )

        response = client.post(
            reverse("gameplay:synthesize_blueprint_equipment"),
            data={"blueprint_key": "bp_dummy", "quantity": "1", "category": "helmet", "mode": "synthesize"},
        )
        assert_forge_redirect(response, mode="synthesize", category="helmet")
        assert any("blueprint blocked" in message for message in response_messages(response))

    def test_synthesize_blueprint_equipment_legacy_value_error_bubbles_up(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user
        monkeypatch.setattr(
            "gameplay.services.buildings.forge.synthesize_equipment_with_blueprint",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("legacy blueprint blocked")),
        )

        with pytest.raises(ValueError, match="legacy blueprint blocked"):
            client.post(
                reverse("gameplay:synthesize_blueprint_equipment"),
                data={"blueprint_key": "bp_dummy", "quantity": "1", "category": "helmet", "mode": "synthesize"},
            )
