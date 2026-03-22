import pytest
from django_redis.exceptions import ConnectionInterrupted


@pytest.mark.django_db
def test_get_player_rank_matches_expected_order(django_user_model):
    from gameplay.services.manor.core import ensure_manor
    from gameplay.services.ranking import get_player_rank

    # Create manors in a deterministic order; created_at should reflect insertion order.
    u1 = django_user_model.objects.create_user(username="rank_u1", password="pass")
    u2 = django_user_model.objects.create_user(username="rank_u2", password="pass")
    u3 = django_user_model.objects.create_user(username="rank_u3", password="pass")
    u4 = django_user_model.objects.create_user(username="rank_u4", password="pass")

    m1 = ensure_manor(u1)
    m2 = ensure_manor(u2)
    m3 = ensure_manor(u3)
    m4 = ensure_manor(u4)

    # Prestige: m3 highest, then m1/m2 tie (m1 earlier), then m4.
    m1.prestige = 100
    m1.save(update_fields=["prestige"])
    m2.prestige = 100
    m2.save(update_fields=["prestige"])
    m3.prestige = 200
    m3.save(update_fields=["prestige"])
    m4.prestige = 50
    m4.save(update_fields=["prestige"])

    # Sanity: tie-break by created_at (m1 created earlier than m2).
    assert get_player_rank(m3) == 1
    assert get_player_rank(m1) == 2
    assert get_player_rank(m2) == 3
    assert get_player_rank(m4) == 4


@pytest.mark.django_db
def test_get_player_rank_tolerates_cache_backend_failure(django_user_model, monkeypatch):
    from gameplay.services.manor.core import ensure_manor
    from gameplay.services.ranking import get_player_rank

    user = django_user_model.objects.create_user(username="rank_cache_failure", password="pass")
    other = django_user_model.objects.create_user(username="rank_cache_failure_other", password="pass")

    manor = ensure_manor(user)
    ahead = ensure_manor(other)
    manor.prestige = 100
    manor.save(update_fields=["prestige"])
    ahead.prestige = 200
    ahead.save(update_fields=["prestige"])

    monkeypatch.setattr(
        "gameplay.services.ranking.cache.get",
        lambda *_a, **_k: (_ for _ in ()).throw(ConnectionInterrupted("cache down")),
    )
    monkeypatch.setattr(
        "gameplay.services.ranking.cache.set",
        lambda *_a, **_k: (_ for _ in ()).throw(ConnectionInterrupted("cache down")),
    )

    assert get_player_rank(manor) == 2


@pytest.mark.django_db
def test_get_player_rank_runtime_marker_cache_error_bubbles_up(django_user_model, monkeypatch):
    from gameplay.services.manor.core import ensure_manor
    from gameplay.services.ranking import get_player_rank

    user = django_user_model.objects.create_user(username="rank_runtime_marker", password="pass")
    manor = ensure_manor(user)
    manor.prestige = 100
    manor.save(update_fields=["prestige"])

    monkeypatch.setattr(
        "gameplay.services.ranking.cache.get",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("cache down")),
    )

    with pytest.raises(RuntimeError, match="cache down"):
        get_player_rank(manor)


@pytest.mark.django_db
def test_get_player_rank_cache_set_programming_error_bubbles_up(django_user_model, monkeypatch):
    from gameplay.services.manor.core import ensure_manor
    from gameplay.services.ranking import get_player_rank

    user = django_user_model.objects.create_user(username="rank_set_programming", password="pass")
    other = django_user_model.objects.create_user(username="rank_set_programming_other", password="pass")

    manor = ensure_manor(user)
    ahead = ensure_manor(other)
    manor.prestige = 100
    manor.save(update_fields=["prestige"])
    ahead.prestige = 200
    ahead.save(update_fields=["prestige"])

    monkeypatch.setattr("gameplay.services.ranking.cache.get", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "gameplay.services.ranking.cache.set",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("broken ranking cache contract")),
    )

    with pytest.raises(AssertionError, match="broken ranking cache contract"):
        get_player_rank(manor)
