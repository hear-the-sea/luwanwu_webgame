from __future__ import annotations

import pytest

import guests.services.recruitment as recruitment_command_service
import guests.services.recruitment_guests as recruitment_guest_service
import guests.services.recruitment_shared as recruitment_shared
import guests.services.recruitment_templates as recruitment_template_service
from core.exceptions import GuestNotFoundError, GuestNotIdleError, InvalidAllocationError
from guests.models import GuestStatus, GuestTemplate
from tests.guest_recruitment_service.support import create_guest_for_allocation_tests


@pytest.mark.django_db
def test_allocate_attribute_points_rejects_zero_points(django_user_model):
    guest = create_guest_for_allocation_tests(django_user_model, "zero")

    with pytest.raises(InvalidAllocationError):
        recruitment_guest_service.allocate_attribute_points(guest, "force", 0)


@pytest.mark.django_db
def test_allocate_attribute_points_rejects_missing_unsaved_guest(django_user_model):
    from gameplay.services.manor.core import ensure_manor
    from guests.models import Guest

    user = django_user_model.objects.create_user(username="alloc_guest_unsaved", password="pass123")
    manor = ensure_manor(user)
    template = GuestTemplate.objects.create(
        key="alloc_guest_unsaved_tpl",
        name="未保存门客模板",
        archetype="civil",
        rarity="gray",
    )
    guest = Guest(manor=manor, template=template, attribute_points=1, force=1, intellect=1, defense_stat=1, agility=1)

    with pytest.raises(GuestNotFoundError, match="门客不存在"):
        recruitment_guest_service.allocate_attribute_points(guest, "force", 1)


@pytest.mark.django_db
def test_allocate_attribute_points_rejects_deleted_guest(django_user_model):
    guest = create_guest_for_allocation_tests(django_user_model, "deleted")
    guest.delete()

    with pytest.raises(GuestNotFoundError, match="门客不存在"):
        recruitment_guest_service.allocate_attribute_points(guest, "force", 1)


@pytest.mark.django_db
def test_allocate_attribute_points_rejects_negative_points(django_user_model):
    guest = create_guest_for_allocation_tests(django_user_model, "negative")

    with pytest.raises(InvalidAllocationError):
        recruitment_guest_service.allocate_attribute_points(guest, "force", -5)


@pytest.mark.django_db
def test_allocate_attribute_points_rejects_insufficient_points(django_user_model):
    guest = create_guest_for_allocation_tests(django_user_model, "insufficient")
    guest.attribute_points = 5
    guest.save(update_fields=["attribute_points"])

    with pytest.raises(InvalidAllocationError):
        recruitment_guest_service.allocate_attribute_points(guest, "force", 10)


@pytest.mark.django_db
def test_allocate_attribute_points_rejects_unknown_attribute(django_user_model):
    guest = create_guest_for_allocation_tests(django_user_model, "unknown")

    with pytest.raises(InvalidAllocationError):
        recruitment_guest_service.allocate_attribute_points(guest, "unknown_attr", 5)


@pytest.mark.django_db
def test_allocate_attribute_points_rejects_overflow(django_user_model):
    guest = create_guest_for_allocation_tests(django_user_model, "overflow")
    guest.attribute_points = 100
    guest.force = 9950
    guest.save(update_fields=["attribute_points", "force"])

    with pytest.raises(InvalidAllocationError, match="属性值已达上限"):
        recruitment_guest_service.allocate_attribute_points(guest, "force", 100)


@pytest.mark.django_db
def test_allocate_attribute_points_rejects_non_idle_guest(django_user_model):
    guest = create_guest_for_allocation_tests(django_user_model, "non_idle")
    guest.status = GuestStatus.DEPLOYED
    guest.save(update_fields=["status"])

    with pytest.raises(GuestNotIdleError):
        recruitment_guest_service.allocate_attribute_points(guest, "force", 1)


@pytest.mark.django_db
def test_allocate_attribute_points_success(django_user_model):
    guest = create_guest_for_allocation_tests(django_user_model, "success")

    result = recruitment_guest_service.allocate_attribute_points(guest, "force", 5)
    result.refresh_from_db()

    assert result.attribute_points == 5
    assert result.force == 55
    assert result.allocated_force == 5


def test_clear_template_cache_clears_both_caches():
    recruitment_template_service.clear_template_cache()


@pytest.mark.django_db
def test_guest_template_signal_clears_recruitment_template_cache(monkeypatch):
    calls: list[str] = []

    def _spy_clear_template_cache():
        calls.append("cleared")

    monkeypatch.setattr(recruitment_template_service, "clear_template_cache", _spy_clear_template_cache)

    GuestTemplate.objects.create(
        key="signal_clear_tpl",
        name="信号清缓存模板",
        archetype="civil",
        rarity="gray",
    )

    assert calls == ["cleared"]


@pytest.mark.django_db
def test_guest_template_signal_cache_infrastructure_error_degrades(monkeypatch):
    monkeypatch.setattr(
        recruitment_template_service,
        "clear_template_cache",
        lambda: (_ for _ in ()).throw(ConnectionError("cache down")),
    )

    GuestTemplate.objects.create(
        key="signal_cache_down_tpl",
        name="信号缓存降级模板",
        archetype="civil",
        rarity="gray",
    )


@pytest.mark.django_db
def test_guest_template_signal_programming_error_bubbles_up(monkeypatch):
    monkeypatch.setattr(
        recruitment_template_service,
        "clear_template_cache",
        lambda: (_ for _ in ()).throw(AssertionError("broken guest template cache contract")),
    )

    with pytest.raises(AssertionError, match="broken guest template cache contract"):
        GuestTemplate.objects.create(
            key="signal_cache_bug_tpl",
            name="信号缓存契约错误模板",
            archetype="civil",
            rarity="gray",
        )


def test_reveal_candidate_rarity_updates_unrevealed():
    from unittest.mock import MagicMock

    manor = MagicMock()
    manor.candidates.filter.return_value.update.return_value = 3

    count = recruitment_command_service.reveal_candidate_rarity(manor)

    assert count == 3
    manor.candidates.filter.assert_called_once_with(rarity_revealed=False)


def test_core_pool_tiers_has_expected_tiers():
    from guests.models import RecruitmentPool

    expected = (
        RecruitmentPool.Tier.CUNMU,
        RecruitmentPool.Tier.XIANGSHI,
        RecruitmentPool.Tier.HUISHI,
        RecruitmentPool.Tier.DIANSHI,
    )
    assert recruitment_shared.CORE_POOL_TIERS == expected
