from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone


@pytest.mark.django_db
def test_guild_tech_daily_production_runs_and_updates_last_production_at(monkeypatch, django_user_model):
    from guilds.models import Guild, GuildTechnology
    from guilds.tasks import guild_tech_daily_production

    calls: list[tuple[str, int]] = []

    monkeypatch.setattr(
        "guilds.tasks.produce_equipment",
        lambda guild, level: calls.append(("equipment", int(level))),
    )
    monkeypatch.setattr(
        "guilds.tasks.produce_experience_items",
        lambda guild, level: calls.append(("exp", int(level))),
    )
    monkeypatch.setattr(
        "guilds.tasks.produce_resource_packs",
        lambda guild, level: calls.append(("packs", int(level))),
    )
    monkeypatch.setattr(
        guild_tech_daily_production,
        "retry",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("retry should not be called")),
    )

    founder = django_user_model.objects.create_user(username="g_founder", password="pass")
    guild = Guild.objects.create(name="G1", founder=founder, is_active=True)

    for key in ("equipment_forge", "experience_refine", "resource_supply"):
        GuildTechnology.objects.create(guild=guild, tech_key=key, level=2)

    result = guild_tech_daily_production.run()
    assert result == "processed 1 guilds"
    assert sorted(calls) == [("equipment", 2), ("exp", 2), ("packs", 2)]

    updated = {t.tech_key: t.last_production_at for t in GuildTechnology.objects.filter(guild=guild)}
    assert all(updated.values())


@pytest.mark.django_db
def test_guild_tech_daily_production_handles_inner_errors(monkeypatch, django_user_model):
    from guilds.models import Guild, GuildTechnology
    from guilds.tasks import guild_tech_daily_production

    calls: list[str] = []

    def _boom(_guild, _level):
        raise RuntimeError("boom")

    monkeypatch.setattr("guilds.tasks.produce_equipment", _boom)
    monkeypatch.setattr(
        "guilds.tasks.produce_experience_items",
        lambda guild, level: calls.append("exp"),
    )
    monkeypatch.setattr(
        "guilds.tasks.produce_resource_packs",
        lambda guild, level: calls.append("packs"),
    )
    monkeypatch.setattr(
        guild_tech_daily_production,
        "retry",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("retry should not be called")),
    )

    founder = django_user_model.objects.create_user(username="g_founder2", password="pass")
    guild = Guild.objects.create(name="G2", founder=founder, is_active=True)
    GuildTechnology.objects.create(guild=guild, tech_key="equipment_forge", level=2)
    GuildTechnology.objects.create(guild=guild, tech_key="experience_refine", level=2)
    GuildTechnology.objects.create(guild=guild, tech_key="resource_supply", level=2)

    result = guild_tech_daily_production.run()
    assert result == "processed 1 guilds"
    assert sorted(calls) == ["exp", "packs"]


@pytest.mark.django_db
def test_reset_guild_weekly_stats_retries_on_error(monkeypatch):
    from guilds.tasks import reset_guild_weekly_stats

    monkeypatch.setattr("guilds.tasks.reset_weekly_contributions", lambda: (_ for _ in ()).throw(RuntimeError("x")))

    called = {"retry": 0}

    def _retry(exc):
        called["retry"] += 1
        raise RuntimeError("retried")

    monkeypatch.setattr(reset_guild_weekly_stats, "retry", _retry)

    with pytest.raises(RuntimeError, match="retried"):
        reset_guild_weekly_stats.run()

    assert called["retry"] == 1


@pytest.mark.django_db
def test_cleanup_old_guild_logs_deletes_only_old_rows(monkeypatch, django_user_model):
    from guilds.models import Guild, GuildDonationLog, GuildExchangeLog, GuildMember, GuildResourceLog
    from guilds.tasks import cleanup_old_guild_logs

    monkeypatch.setattr(
        cleanup_old_guild_logs,
        "retry",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("retry should not be called")),
    )

    founder = django_user_model.objects.create_user(username="g_founder3", password="pass")
    member_user = django_user_model.objects.create_user(username="g_member", password="pass")
    guild = Guild.objects.create(name="G3", founder=founder, is_active=True)
    member = GuildMember.objects.create(guild=guild, user=member_user)

    donation = GuildDonationLog.objects.create(
        guild=guild,
        member=member,
        resource_type="silver",
        amount=1,
        contribution_gained=1,
    )
    exchange = GuildExchangeLog.objects.create(
        guild=guild,
        member=member,
        item_key="x",
        quantity=1,
        contribution_cost=1,
    )
    resource = GuildResourceLog.objects.create(guild=guild, action="donation", silver_change=1)

    old_ts = timezone.now() - timedelta(days=31)
    GuildDonationLog.objects.filter(pk=donation.pk).update(donated_at=old_ts)
    GuildExchangeLog.objects.filter(pk=exchange.pk).update(exchanged_at=old_ts)
    GuildResourceLog.objects.filter(pk=resource.pk).update(created_at=old_ts)

    # New rows should be kept.
    GuildDonationLog.objects.create(
        guild=guild,
        member=member,
        resource_type="silver",
        amount=2,
        contribution_gained=2,
    )

    result = cleanup_old_guild_logs.run()
    assert "cleaned up" in result
    assert GuildDonationLog.objects.count() == 1
    assert GuildExchangeLog.objects.count() == 0
    assert GuildResourceLog.objects.count() == 0
