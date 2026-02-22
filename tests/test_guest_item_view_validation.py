from __future__ import annotations

import pytest
from django.contrib.messages import get_messages
from django.test import Client
from django.urls import reverse

from gameplay.models import InventoryItem, ItemTemplate
from gameplay.services.manor.core import ensure_manor
from guests.models import RecruitmentCandidate, RecruitmentPool
from guests.services import finalize_candidate, recruit_guest


def _bootstrap_guest_client(game_data, django_user_model, *, username: str):
    user = django_user_model.objects.create_user(username=username, password="pass123")
    manor = ensure_manor(user)
    manor.grain = manor.silver = 500000
    manor.save(update_fields=["grain", "silver"])

    pool = RecruitmentPool.objects.get(key="tongshi")
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
def test_recruit_view_rejects_when_action_lock_conflicts(game_data, django_user_model, monkeypatch):
    user = django_user_model.objects.create_user(username="view_recruit_lock_conflict", password="pass123")
    ensure_manor(user)
    client = Client()
    assert client.login(username="view_recruit_lock_conflict", password="pass123")
    pool = RecruitmentPool.objects.get(key="tongshi")
    called = {"count": 0}

    monkeypatch.setattr("guests.views.recruit._acquire_recruit_action_lock", lambda *_a, **_k: (False, ""))

    def _unexpected_recruit(*_args, **_kwargs):
        called["count"] += 1
        return []

    monkeypatch.setattr("guests.views.recruit.recruit_guest", _unexpected_recruit)

    response = client.post(reverse("guests:recruit"), {"pool": str(pool.pk)})

    assert response.status_code == 302
    assert response.url == reverse("gameplay:recruitment_hall")
    messages = [str(m) for m in get_messages(response.wsgi_request)]
    assert any("请求处理中，请稍候重试" in m for m in messages)
    assert called["count"] == 0


@pytest.mark.django_db
def test_candidate_accept_view_rejects_when_action_lock_conflicts(game_data, django_user_model, monkeypatch):
    user = django_user_model.objects.create_user(username="view_candidate_accept_lock_conflict", password="pass123")
    manor = ensure_manor(user)
    client = Client()
    assert client.login(username="view_candidate_accept_lock_conflict", password="pass123")
    pool = RecruitmentPool.objects.get(key="tongshi")
    candidate = recruit_guest(manor, pool, seed=1)[0]
    called = {"count": 0}

    monkeypatch.setattr("guests.views.recruit._acquire_recruit_action_lock", lambda *_a, **_k: (False, ""))

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
def test_candidate_accept_view_rejects_invalid_action(game_data, django_user_model, monkeypatch):
    user = django_user_model.objects.create_user(username="view_candidate_accept_invalid_action", password="pass123")
    manor = ensure_manor(user)
    client = Client()
    assert client.login(username="view_candidate_accept_invalid_action", password="pass123")
    pool = RecruitmentPool.objects.get(key="tongshi")
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
def test_use_magnifying_glass_view_rejects_when_action_lock_conflicts_ajax(game_data, django_user_model, monkeypatch):
    user = django_user_model.objects.create_user(username="view_magnify_lock_conflict", password="pass123")
    ensure_manor(user)
    client = Client()
    assert client.login(username="view_magnify_lock_conflict", password="pass123")
    called = {"count": 0}

    monkeypatch.setattr("guests.views.recruit._acquire_recruit_action_lock", lambda *_a, **_k: (False, ""))

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
