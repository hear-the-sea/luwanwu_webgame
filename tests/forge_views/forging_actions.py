from types import SimpleNamespace

import pytest
from django.db import DatabaseError
from django.urls import reverse

from core.exceptions import ForgeOperationError
from tests.forge_views.support import assert_forge_redirect, response_messages


@pytest.mark.django_db
class TestStartEquipmentForgingView:
    def test_start_equipment_forging_database_error_does_not_500(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user

        monkeypatch.setattr(
            "gameplay.services.buildings.forge.start_equipment_forging",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(DatabaseError("db down")),
        )

        response = client.post(
            reverse("gameplay:start_equipment_forging"),
            {"equipment_key": "equip_dummy", "quantity": "1", "category": "helmet", "mode": "synthesize"},
        )
        assert_forge_redirect(response, mode="synthesize", category="helmet")
        assert any("操作失败，请稍后重试" in message for message in response_messages(response))

    def test_start_equipment_forging_rejects_invalid_quantity(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user
        called = {"count": 0}

        def _unexpected_start(*_args, **_kwargs):
            called["count"] += 1

        monkeypatch.setattr("gameplay.services.buildings.forge.start_equipment_forging", _unexpected_start)

        response = client.post(
            reverse("gameplay:start_equipment_forging"),
            {"equipment_key": "equip_dummy", "quantity": "bad", "category": "helmet", "mode": "synthesize"},
        )
        assert_forge_redirect(response, mode="synthesize", category="helmet")
        assert any("无效的数量" in message for message in response_messages(response))
        assert called["count"] == 0

    def test_start_equipment_forging_rejects_missing_equipment_key(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user
        called = {"count": 0}

        def _unexpected_start(*_args, **_kwargs):
            called["count"] += 1

        monkeypatch.setattr("gameplay.services.buildings.forge.start_equipment_forging", _unexpected_start)

        response = client.post(
            reverse("gameplay:start_equipment_forging"),
            {"quantity": "1", "category": "helmet", "mode": "invalid"},
        )
        assert_forge_redirect(response, mode="synthesize", category="helmet")
        assert any("请选择装备类型" in message for message in response_messages(response))
        assert called["count"] == 0

    def test_start_equipment_forging_programming_error_bubbles_up(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user
        monkeypatch.setattr(
            "gameplay.services.buildings.forge.start_equipment_forging",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        with pytest.raises(RuntimeError, match="boom"):
            client.post(
                reverse("gameplay:start_equipment_forging"),
                {"equipment_key": "equip_dummy", "quantity": "1", "category": "helmet", "mode": "synthesize"},
            )

    def test_start_equipment_forging_known_error_shows_message(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user
        monkeypatch.setattr(
            "gameplay.services.buildings.forge.start_equipment_forging",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(ForgeOperationError("forge blocked")),
        )

        response = client.post(
            reverse("gameplay:start_equipment_forging"),
            {"equipment_key": "equip_dummy", "quantity": "1", "category": "helmet", "mode": "synthesize"},
        )
        assert_forge_redirect(response, mode="synthesize", category="helmet")
        assert any("forge blocked" in message for message in response_messages(response))

    def test_start_equipment_forging_legacy_value_error_bubbles_up(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user
        monkeypatch.setattr(
            "gameplay.services.buildings.forge.start_equipment_forging",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("legacy forge blocked")),
        )

        with pytest.raises(ValueError, match="legacy forge blocked"):
            client.post(
                reverse("gameplay:start_equipment_forging"),
                {"equipment_key": "equip_dummy", "quantity": "1", "category": "helmet", "mode": "synthesize"},
            )

    def test_start_equipment_forging_malformed_result_bubbles_up(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user
        monkeypatch.setattr(
            "gameplay.services.buildings.forge.start_equipment_forging",
            lambda *_args, **_kwargs: SimpleNamespace(
                equipment_name="测试装备",
                quantity=1,
                actual_duration="bad",
            ),
        )

        with pytest.raises(AssertionError, match="invalid forge production result actual_duration"):
            client.post(
                reverse("gameplay:start_equipment_forging"),
                {"equipment_key": "equip_dummy", "quantity": "1", "category": "helmet", "mode": "synthesize"},
            )
