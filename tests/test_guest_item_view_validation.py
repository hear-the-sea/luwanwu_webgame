from __future__ import annotations

import pytest
from django.contrib.messages import get_messages
from django.test import Client
from django.urls import reverse

from gameplay.models import InventoryItem, ItemTemplate
from gameplay.services.manor.core import ensure_manor
from guests.models import GearSlot, RecruitmentCandidate, RecruitmentPool
from guests.services.recruitment import recruit_guest
from guests.services.recruitment_guests import finalize_candidate
from guests.views import recruit as recruit_views


def _bootstrap_guest_client(game_data, django_user_model, *, username: str):
    user = django_user_model.objects.create_user(username=username, password="pass123")
    manor = ensure_manor(user)
    manor.grain = manor.silver = 500000
    manor.save(update_fields=["grain", "silver"])

    pool = RecruitmentPool.objects.get(key="cunmu")
    candidate = recruit_guest(manor, pool, seed=1)[0]
    guest = finalize_candidate(candidate)

    client = Client()
    assert client.login(username=username, password="pass123")
    return manor, guest, client


@pytest.mark.django_db
def test_use_experience_item_view_rejects_invalid_item_id_ajax(game_data, django_user_model):
    _manor, guest, client = _bootstrap_guest_client(game_data, django_user_model, username="view_exp_item_invalid")

    response = client.post(
        reverse("guests:use_exp_item", args=[guest.pk]),
        {"item_id": "invalid"},
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert "请选择经验道具" in payload["error"]


@pytest.mark.django_db
def test_use_medicine_item_view_rejects_invalid_item_id_ajax(game_data, django_user_model):
    _manor, guest, client = _bootstrap_guest_client(game_data, django_user_model, username="view_medicine_item_invalid")

    response = client.post(
        reverse("guests:use_medicine_item", args=[guest.pk]),
        {"item_id": "invalid"},
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert "请选择药品道具" in payload["error"]


@pytest.mark.django_db
def test_use_medicine_item_view_ajax_success_returns_numeric_item_id(game_data, django_user_model):
    manor, guest, client = _bootstrap_guest_client(game_data, django_user_model, username="view_medicine_item_success")
    guest.current_hp = max(1, guest.max_hp - 100)
    guest.save(update_fields=["current_hp"])

    template = ItemTemplate.objects.create(
        key=f"view_medicine_item_success_{manor.id}",
        name="测试疗伤药",
        effect_type=ItemTemplate.EffectType.MEDICINE,
        effect_payload={"hp": 80},
    )
    item = InventoryItem.objects.create(
        manor=manor,
        template=template,
        quantity=2,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )

    response = client.post(
        reverse("guests:use_medicine_item", args=[guest.pk]),
        {"item_id": str(item.pk)},
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["item_id"] == item.pk
    assert isinstance(payload["item_id"], int)
    assert payload["new_quantity"] == 1


@pytest.mark.django_db
def test_use_experience_item_view_rejects_invalid_effect_payload_ajax(game_data, django_user_model, monkeypatch):
    manor, guest, client = _bootstrap_guest_client(game_data, django_user_model, username="view_exp_item_bad_payload")
    template = ItemTemplate.objects.create(
        key=f"view_exp_item_bad_payload_{manor.id}",
        name="异常经验配置道具",
        effect_type=ItemTemplate.EffectType.EXPERIENCE_ITEM,
        effect_payload={"time": None},
    )
    item = InventoryItem.objects.create(manor=manor, template=template, quantity=1)
    called = {"count": 0}

    def _unexpected_use(*_args, **_kwargs):
        called["count"] += 1
        return {}

    monkeypatch.setattr("guests.views.training.use_experience_item_for_guest", _unexpected_use)

    response = client.post(
        reverse("guests:use_exp_item", args=[guest.pk]),
        {"item_id": str(item.pk)},
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert "道具未配置有效时间" in payload["error"]
    assert called["count"] == 0


@pytest.mark.django_db
def test_use_medicine_item_view_rejects_invalid_effect_payload_ajax(game_data, django_user_model, monkeypatch):
    manor, guest, client = _bootstrap_guest_client(
        game_data, django_user_model, username="view_medicine_item_bad_payload"
    )
    template = ItemTemplate.objects.create(
        key=f"view_medicine_item_bad_payload_{manor.id}",
        name="异常药品配置道具",
        effect_type=ItemTemplate.EffectType.MEDICINE,
        effect_payload={"hp": None},
    )
    item = InventoryItem.objects.create(manor=manor, template=template, quantity=1)
    called = {"count": 0}

    def _unexpected_use(*_args, **_kwargs):
        called["count"] += 1
        return {}

    monkeypatch.setattr("guests.views.items.use_medicine_item_for_guest", _unexpected_use)

    response = client.post(
        reverse("guests:use_medicine_item", args=[guest.pk]),
        {"item_id": str(item.pk)},
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert "道具未配置有效恢复值" in payload["error"]
    assert called["count"] == 0


@pytest.mark.django_db
def test_use_magnifying_glass_view_rejects_invalid_item_id_ajax(game_data, django_user_model):
    user = django_user_model.objects.create_user(username="view_magnify_item_invalid", password="pass123")
    ensure_manor(user)
    client = Client()
    assert client.login(username="view_magnify_item_invalid", password="pass123")

    response = client.post(
        reverse("guests:use_magnifying_glass"),
        {"item_id": "invalid"},
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert "未找到放大镜道具" in payload["error"]


@pytest.mark.django_db
def test_gear_options_view_tolerates_cache_backend_failure(game_data, django_user_model, monkeypatch):
    user = django_user_model.objects.create_user(username="view_gear_options_cache_failure", password="pass123")
    manor = ensure_manor(user)
    client = Client()
    assert client.login(username="view_gear_options_cache_failure", password="pass123")

    monkeypatch.setattr("guests.services.equipment.ensure_inventory_gears", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "guests.views.equipment.cache.get",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("cache down")),
    )
    monkeypatch.setattr(
        "guests.views.equipment.cache.set",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("cache down")),
    )

    from guests.models import GearItem, GearTemplate

    template = GearTemplate.objects.create(
        key=f"view_gear_options_cache_failure_{manor.id}",
        name="缓存失败测试装备",
        slot=GearSlot.WEAPON,
        rarity="green",
    )
    GearItem.objects.create(manor=manor, template=template, guest=None)

    response = client.get(reverse("guests:gear_options"), {"slot": GearSlot.WEAPON})

    assert response.status_code == 200
    payload = response.json()
    assert payload["slot"] == GearSlot.WEAPON
    assert len(payload["options"]) == 1
    assert payload["options"][0]["name"] == template.name


@pytest.mark.django_db
def test_recruit_view_rejects_when_action_lock_conflicts(game_data, django_user_model, monkeypatch):
    user = django_user_model.objects.create_user(username="view_recruit_lock_conflict", password="pass123")
    ensure_manor(user)
    client = Client()
    assert client.login(username="view_recruit_lock_conflict", password="pass123")
    pool = RecruitmentPool.objects.get(key="cunmu")
    called = {"count": 0}

    monkeypatch.setattr("guests.views.recruit._acquire_recruit_action_lock", lambda *_a, **_k: (False, "", None))

    def _unexpected_recruit(*_args, **_kwargs):
        called["count"] += 1
        return None

    monkeypatch.setattr("guests.views.recruit.start_guest_recruitment", _unexpected_recruit)

    response = client.post(reverse("guests:recruit"), {"pool": str(pool.pk)})

    assert response.status_code == 302
    assert response.url == reverse("gameplay:recruitment_hall")
    messages = [str(m) for m in get_messages(response.wsgi_request)]
    assert any("请求处理中，请稍候重试" in m for m in messages)
    assert called["count"] == 0


@pytest.mark.django_db
def test_recruit_view_ajax_success_returns_recruitment_hall_partials(game_data, django_user_model):
    user = django_user_model.objects.create_user(username="view_recruit_ajax_success", password="pass123")
    manor = ensure_manor(user)
    manor.grain = manor.silver = 500000
    manor.save(update_fields=["grain", "silver"])
    client = Client()
    assert client.login(username="view_recruit_ajax_success", password="pass123")
    pool = RecruitmentPool.objects.get(key="cunmu")

    response = client.post(
        reverse("guests:recruit"),
        {"pool": str(pool.pk)},
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        HTTP_ACCEPT="application/json",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert "recruit-pools-section" in payload["hall_pools_html"]
    assert "recruit-candidates-section" in payload["hall_candidates_html"]
    assert "recruit-records-section" in payload["hall_records_html"]


@pytest.mark.django_db
def test_recruit_view_ajax_success_bypasses_cache_when_invalidation_fails(game_data, django_user_model, monkeypatch):
    user = django_user_model.objects.create_user(username="view_recruit_ajax_uncached", password="pass123")
    manor = ensure_manor(user)
    manor.grain = manor.silver = 500000
    manor.save(update_fields=["grain", "silver"])
    client = Client()
    assert client.login(username="view_recruit_ajax_uncached", password="pass123")
    pool = RecruitmentPool.objects.get(key="cunmu")

    monkeypatch.setattr("guests.views.recruit._invalidate_recruitment_hall_cache_for_manor", lambda *_a, **_k: False)
    monkeypatch.setattr(
        "gameplay.selectors.recruitment.cache.get",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("cache.get should be bypassed")),
    )
    monkeypatch.setattr(
        "gameplay.selectors.recruitment.cache.set",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("cache.set should be bypassed")),
    )

    response = client.post(
        reverse("guests:recruit"),
        {"pool": str(pool.pk)},
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        HTTP_ACCEPT="application/json",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert "recruit-candidates-section" in payload["hall_candidates_html"]


@pytest.mark.django_db
def test_candidate_accept_view_rejects_when_action_lock_conflicts(game_data, django_user_model, monkeypatch):
    user = django_user_model.objects.create_user(username="view_candidate_accept_lock_conflict", password="pass123")
    manor = ensure_manor(user)
    client = Client()
    assert client.login(username="view_candidate_accept_lock_conflict", password="pass123")
    pool = RecruitmentPool.objects.get(key="cunmu")
    candidate = recruit_guest(manor, pool, seed=1)[0]
    called = {"count": 0}

    monkeypatch.setattr("guests.views.recruit._acquire_recruit_action_lock", lambda *_a, **_k: (False, "", None))

    def _unexpected_finalize(*_args, **_kwargs):
        called["count"] += 1
        return [], []

    monkeypatch.setattr("guests.views.recruit._finalize_candidates", _unexpected_finalize)

    response = client.post(reverse("guests:candidate_accept"), {"candidate_ids": [str(candidate.pk)]})

    assert response.status_code == 302
    assert response.url == reverse("gameplay:recruitment_hall")
    messages = [str(m) for m in get_messages(response.wsgi_request)]
    assert any("请求处理中，请稍候重试" in m for m in messages)
    assert called["count"] == 0


@pytest.mark.django_db
def test_candidate_accept_view_uses_manor_wide_candidate_action_lock(game_data, django_user_model, monkeypatch):
    user = django_user_model.objects.create_user(username="view_candidate_accept_lock_scope", password="pass123")
    manor = ensure_manor(user)
    client = Client()
    assert client.login(username="view_candidate_accept_lock_scope", password="pass123")
    pool = RecruitmentPool.objects.get(key="cunmu")
    candidate = recruit_guest(manor, pool, seed=11)[0]
    captured: dict[str, str | int | None] = {}

    def _capture_lock(action, manor_id, scope):
        captured["action"] = action
        captured["manor_id"] = manor_id
        captured["scope"] = scope
        return False, "", None

    monkeypatch.setattr("guests.views.recruit._acquire_recruit_action_lock", _capture_lock)

    response = client.post(
        reverse("guests:candidate_accept"), {"candidate_ids": [str(candidate.pk)], "action": "retain"}
    )

    assert response.status_code == 302
    assert captured == {
        "action": "candidate_action",
        "manor_id": manor.id,
        "scope": f"candidate-actions:{manor.id}",
    }


@pytest.mark.django_db
def test_candidate_accept_view_retain_ajax_success_returns_recruitment_hall_partials(game_data, django_user_model):
    user = django_user_model.objects.create_user(username="view_candidate_accept_retain_ajax", password="pass123")
    manor = ensure_manor(user)
    manor.grain = manor.silver = 500000
    manor.save(update_fields=["grain", "silver"])
    client = Client()
    assert client.login(username="view_candidate_accept_retain_ajax", password="pass123")
    pool = RecruitmentPool.objects.get(key="cunmu")
    candidate = recruit_guest(manor, pool, seed=6)[0]
    retainer_before = manor.retainer_count

    response = client.post(
        reverse("guests:candidate_accept"),
        {"candidate_ids": [str(candidate.pk)], "action": "retain"},
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        HTTP_ACCEPT="application/json",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert "recruit-candidates-section" in payload["hall_candidates_html"]
    assert "已将 1 名候选收为家丁" in payload["message"]

    manor.refresh_from_db()
    assert manor.retainer_count == retainer_before + 1
    assert RecruitmentCandidate.objects.filter(pk=candidate.pk).exists() is False


@pytest.mark.django_db
def test_candidate_accept_view_rejects_invalid_candidate_ids(game_data, django_user_model):
    user = django_user_model.objects.create_user(username="view_candidate_accept_invalid_ids", password="pass123")
    ensure_manor(user)
    client = Client()
    assert client.login(username="view_candidate_accept_invalid_ids", password="pass123")

    response = client.post(reverse("guests:candidate_accept"), {"candidate_ids": ["abc"], "action": "recruit"})

    assert response.status_code == 302
    assert response.url == reverse("gameplay:recruitment_hall")
    messages = [str(m) for m in get_messages(response.wsgi_request)]
    assert any("候选门客选择有误" in m for m in messages)


@pytest.mark.django_db
def test_candidate_accept_view_discard_all_without_candidate_ids(game_data, django_user_model):
    user = django_user_model.objects.create_user(username="view_candidate_accept_discard_all", password="pass123")
    manor = ensure_manor(user)
    client = Client()
    assert client.login(username="view_candidate_accept_discard_all", password="pass123")
    pool = RecruitmentPool.objects.get(key="cunmu")
    recruit_guest(manor, pool, seed=3)
    total = manor.candidates.count()
    assert total > 0

    response = client.post(reverse("guests:candidate_accept"), {"scope": "all", "action": "discard"})

    assert response.status_code == 302
    assert response.url == reverse("gameplay:recruitment_hall")
    assert manor.candidates.count() == 0
    messages = [str(m) for m in get_messages(response.wsgi_request)]
    assert any(f"已放弃 {total} 名候选门客" in m for m in messages)


@pytest.mark.django_db
def test_candidate_accept_view_accept_all_without_candidate_ids(game_data, django_user_model, monkeypatch):
    user = django_user_model.objects.create_user(username="view_candidate_accept_accept_all", password="pass123")
    manor = ensure_manor(user)
    client = Client()
    assert client.login(username="view_candidate_accept_accept_all", password="pass123")
    pool = RecruitmentPool.objects.get(key="cunmu")
    recruit_guest(manor, pool, seed=4)

    called = {"count": 0}

    def _fake_finalize(candidates):
        called["count"] = len(candidates)
        return [], []

    monkeypatch.setattr("guests.views.recruit._finalize_candidates", _fake_finalize)

    response = client.post(reverse("guests:candidate_accept"), {"scope": "all", "action": "accept"})

    assert response.status_code == 302
    assert response.url == reverse("gameplay:recruitment_hall")
    assert called["count"] == manor.candidates.count()
    messages = [str(m) for m in get_messages(response.wsgi_request)]
    assert not any("请先勾选候选门客" in m for m in messages)


@pytest.mark.django_db
def test_candidate_accept_view_rejects_invalid_action(game_data, django_user_model, monkeypatch):
    user = django_user_model.objects.create_user(username="view_candidate_accept_invalid_action", password="pass123")
    manor = ensure_manor(user)
    client = Client()
    assert client.login(username="view_candidate_accept_invalid_action", password="pass123")
    pool = RecruitmentPool.objects.get(key="cunmu")
    candidate = recruit_guest(manor, pool, seed=1)[0]
    called = {"finalize": 0, "retain": 0}

    def _unexpected_finalize(*_args, **_kwargs):
        called["finalize"] += 1
        return [], []

    def _unexpected_retain(*_args, **_kwargs):
        called["retain"] += 1
        return 0, None

    monkeypatch.setattr("guests.views.recruit._finalize_candidates", _unexpected_finalize)
    monkeypatch.setattr("guests.views.recruit._retain_candidates", _unexpected_retain)

    response = client.post(
        reverse("guests:candidate_accept"),
        {"candidate_ids": [str(candidate.pk)], "action": "invalid_action"},
    )

    assert response.status_code == 302
    assert response.url == reverse("gameplay:recruitment_hall")
    messages = [str(m) for m in get_messages(response.wsgi_request)]
    assert any("操作类型无效" in m for m in messages)
    assert called["finalize"] == 0
    assert called["retain"] == 0
    assert RecruitmentCandidate.objects.filter(pk=candidate.pk).exists()


@pytest.mark.django_db
def test_candidate_accept_view_truncates_success_message_for_large_batch(game_data, django_user_model, monkeypatch):
    user = django_user_model.objects.create_user(username="view_candidate_accept_large_batch", password="pass123")
    manor = ensure_manor(user)
    manor.grain = manor.silver = 500000
    manor.save(update_fields=["grain", "silver"])
    client = Client()
    assert client.login(username="view_candidate_accept_large_batch", password="pass123")
    pool = RecruitmentPool.objects.get(key="cunmu")
    candidate = recruit_guest(manor, pool, seed=2)[0]

    class _DummyGuest:
        def __init__(self, display_name: str):
            self.display_name = display_name

    total = recruit_views.RECRUIT_SUCCESS_NAME_PREVIEW_LIMIT + 3
    succeeded = [_DummyGuest(f"门客{i}") for i in range(total)]

    monkeypatch.setattr(
        "guests.views.recruit._acquire_recruit_action_lock", lambda *_a, **_k: (True, "lock-test", "mock-token")
    )
    monkeypatch.setattr("guests.views.recruit._release_recruit_action_lock", lambda *_a, **_k: None)
    monkeypatch.setattr("guests.views.recruit._finalize_candidates", lambda *_a, **_k: (succeeded, []))

    response = client.post(
        reverse("guests:candidate_accept"), {"candidate_ids": [str(candidate.pk)], "action": "accept"}
    )

    assert response.status_code == 302
    assert response.url == reverse("gameplay:recruitment_hall")
    message_list = [str(m) for m in get_messages(response.wsgi_request)]
    success_message = next((m for m in message_list if f"成功招募 {total} 名门客" in m), "")
    assert success_message
    assert "等 3 名" in success_message
    assert f"门客{recruit_views.RECRUIT_SUCCESS_NAME_PREVIEW_LIMIT}" not in success_message


@pytest.mark.django_db
def test_use_magnifying_glass_view_rejects_when_action_lock_conflicts_ajax(game_data, django_user_model, monkeypatch):
    user = django_user_model.objects.create_user(username="view_magnify_lock_conflict", password="pass123")
    ensure_manor(user)
    client = Client()
    assert client.login(username="view_magnify_lock_conflict", password="pass123")
    called = {"count": 0}

    monkeypatch.setattr("guests.views.recruit._acquire_recruit_action_lock", lambda *_a, **_k: (False, "", None))

    def _unexpected_reveal(*_args, **_kwargs):
        called["count"] += 1
        return 0

    monkeypatch.setattr("guests.views.recruit.use_magnifying_glass_for_candidates", _unexpected_reveal)

    response = client.post(
        reverse("guests:use_magnifying_glass"),
        {"item_id": "1"},
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )

    assert response.status_code == 409
    payload = response.json()
    assert payload["success"] is False
    assert "请求处理中，请稍候重试" in payload["error"]
    assert called["count"] == 0


@pytest.mark.django_db
def test_use_magnifying_glass_view_ajax_success_returns_recruitment_hall_partials(game_data, django_user_model):
    user = django_user_model.objects.create_user(username="view_magnify_ajax_success", password="pass123")
    manor = ensure_manor(user)
    manor.grain = manor.silver = 500000
    manor.save(update_fields=["grain", "silver"])
    client = Client()
    assert client.login(username="view_magnify_ajax_success", password="pass123")
    pool = RecruitmentPool.objects.get(key="cunmu")
    recruit_guest(manor, pool, seed=7)

    template, _created = ItemTemplate.objects.get_or_create(
        key="fangdajing",
        defaults={
            "name": "放大镜",
            "effect_type": ItemTemplate.EffectType.TOOL,
            "is_usable": True,
        },
    )
    item = InventoryItem.objects.create(
        manor=manor,
        template=template,
        quantity=1,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )

    response = client.post(
        reverse("guests:use_magnifying_glass"),
        {"item_id": str(item.pk)},
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        HTTP_ACCEPT="application/json",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert "显现" in payload["message"]
    assert "recruit-candidates-section" in payload["hall_candidates_html"]


@pytest.mark.django_db
def test_use_experience_item_view_unexpected_error_returns_500(game_data, django_user_model, monkeypatch):
    manor, guest, client = _bootstrap_guest_client(game_data, django_user_model, username="view_exp_item_unexpected")
    template = ItemTemplate.objects.create(
        key=f"view_exp_item_unexpected_{manor.id}",
        name="异常经验道具",
        effect_type=ItemTemplate.EffectType.EXPERIENCE_ITEM,
        effect_payload={"time": 3600},
    )
    item = InventoryItem.objects.create(manor=manor, template=template, quantity=1)

    monkeypatch.setattr(
        "guests.views.training.use_experience_item_for_guest",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    response = client.post(
        reverse("guests:use_exp_item", args=[guest.pk]),
        {"item_id": str(item.pk)},
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )

    assert response.status_code == 500
    payload = response.json()
    assert payload["success"] is False
    assert "操作失败，请稍后重试" in payload["error"]


@pytest.mark.django_db
def test_use_medicine_item_view_unexpected_error_returns_500(game_data, django_user_model, monkeypatch):
    manor, guest, client = _bootstrap_guest_client(
        game_data, django_user_model, username="view_medicine_item_unexpected"
    )
    template = ItemTemplate.objects.create(
        key=f"view_medicine_item_unexpected_{manor.id}",
        name="异常药品道具",
        effect_type=ItemTemplate.EffectType.MEDICINE,
        effect_payload={"hp": 100},
    )
    item = InventoryItem.objects.create(manor=manor, template=template, quantity=1)

    monkeypatch.setattr(
        "guests.views.items.use_medicine_item_for_guest",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    response = client.post(
        reverse("guests:use_medicine_item", args=[guest.pk]),
        {"item_id": str(item.pk)},
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )

    assert response.status_code == 500
    payload = response.json()
    assert payload["success"] is False
    assert "操作失败，请稍后重试" in payload["error"]


@pytest.mark.django_db
def test_use_magnifying_glass_view_unexpected_error_returns_500(game_data, django_user_model, monkeypatch):
    user = django_user_model.objects.create_user(username="view_magnify_item_unexpected", password="pass123")
    ensure_manor(user)
    client = Client()
    assert client.login(username="view_magnify_item_unexpected", password="pass123")

    monkeypatch.setattr(
        "guests.views.recruit.use_magnifying_glass_for_candidates",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    response = client.post(
        reverse("guests:use_magnifying_glass"),
        {"item_id": "1"},
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )

    assert response.status_code == 500
    payload = response.json()
    assert payload["success"] is False
    assert "操作失败，请稍后重试" in payload["error"]


@pytest.mark.django_db
def test_learn_skill_view_rejects_invalid_item_id_redirect(game_data, django_user_model):
    _manor, guest, client = _bootstrap_guest_client(game_data, django_user_model, username="view_learn_skill_invalid")

    response = client.post(
        reverse("guests:learn_skill", args=[guest.pk]),
        {"item_id": "invalid"},
    )

    assert response.status_code == 302
    messages = [str(m) for m in get_messages(response.wsgi_request)]
    assert any("请选择技能书" in m for m in messages)


@pytest.mark.django_db
def test_forget_skill_view_rejects_invalid_guest_skill_id_redirect(game_data, django_user_model):
    _manor, guest, client = _bootstrap_guest_client(game_data, django_user_model, username="view_forget_skill_invalid")

    response = client.post(
        reverse("guests:forget_skill", args=[guest.pk]),
        {"guest_skill_id": "invalid"},
    )

    assert response.status_code == 302
    messages = [str(m) for m in get_messages(response.wsgi_request)]
    assert any("未指定技能" in m for m in messages)
