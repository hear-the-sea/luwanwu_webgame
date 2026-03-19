import pytest
from django.core.cache import cache
from django_redis.exceptions import ConnectionInterrupted

from gameplay.selectors.recruitment import get_recruitment_hall_context
from gameplay.services.manor.core import ensure_manor
from gameplay.services.utils.cache import (
    CacheKeys,
    invalidate_recruitment_hall_cache,
    recruitment_hall_context_cache_key,
)
from guests.models import RecruitmentPool
from guests.services.recruitment import recruit_guest


@pytest.mark.django_db
def test_invalidate_recruitment_hall_cache_deletes_versioned_key(django_user_model):
    user = django_user_model.objects.create_user(username="recruit_cache_invalidate", password="pass123")
    manor = ensure_manor(user)

    legacy_key = CacheKeys.recruitment_hall_context(manor.id)
    current_key = recruitment_hall_context_cache_key(manor.id)
    cache.set(legacy_key, {"candidate_count": 1}, timeout=60)
    cache.set(current_key, {"candidate_count": 1}, timeout=60)

    invalidate_recruitment_hall_cache(manor.id)

    assert cache.get(legacy_key) is None
    assert cache.get(current_key) is None


@pytest.mark.django_db
def test_recruit_guest_invalidates_cached_empty_recruitment_hall_context(game_data, django_user_model):
    user = django_user_model.objects.create_user(username="recruit_cache_refresh", password="pass123")
    manor = ensure_manor(user)
    manor.silver = 500000
    manor.grain = 500000
    manor.save(update_fields=["silver", "grain"])

    pool = RecruitmentPool.objects.get(key="cunmu")
    manor.candidates.all().delete()

    cache.delete(recruitment_hall_context_cache_key(manor.id))
    cached_before = get_recruitment_hall_context(manor, records_limit=5)
    assert cached_before["candidate_count"] == 0

    recruit_guest(manor, pool, seed=11)
    expected_count = manor.candidates.count()
    assert expected_count > 0

    cached_after = get_recruitment_hall_context(manor, records_limit=5)
    assert cached_after["candidate_count"] == expected_count


@pytest.mark.django_db
def test_get_recruitment_hall_context_tolerates_cache_backend_failure(game_data, django_user_model, monkeypatch):
    user = django_user_model.objects.create_user(username="recruit_cache_backend_failure", password="pass123")
    manor = ensure_manor(user)
    manor.silver = 500000
    manor.grain = 500000
    manor.save(update_fields=["silver", "grain"])

    monkeypatch.setattr(
        "gameplay.selectors.recruitment.cache.get",
        lambda *_a, **_k: (_ for _ in ()).throw(ConnectionInterrupted("cache down")),
    )
    monkeypatch.setattr(
        "gameplay.selectors.recruitment.cache.set",
        lambda *_a, **_k: (_ for _ in ()).throw(ConnectionInterrupted("cache down")),
    )

    context = get_recruitment_hall_context(manor, records_limit=5)

    assert context["candidate_count"] == 0
    assert "pools" in context
