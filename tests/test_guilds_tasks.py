from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone


def _dispatch_immediately(task, *, args=None, kwargs=None, countdown=None, logger=None, log_message=""):
    del kwargs, countdown, logger, log_message
    task.run(*(args or []))
    return True


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
    monkeypatch.setattr("common.utils.celery.safe_apply_async", _dispatch_immediately)

    founder = django_user_model.objects.create_user(username="g_founder", password="pass")
    guild = Guild.objects.create(name="G1", founder=founder, is_active=True)

    for key in ("equipment_forge", "experience_refine", "resource_supply"):
        GuildTechnology.objects.create(guild=guild, tech_key=key, level=2)

    result = guild_tech_daily_production.run()
    assert result == "dispatched 1 guild tasks"
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
    monkeypatch.setattr("common.utils.celery.safe_apply_async", _dispatch_immediately)

    founder = django_user_model.objects.create_user(username="g_founder2", password="pass")
    guild = Guild.objects.create(name="G2", founder=founder, is_active=True)
    GuildTechnology.objects.create(guild=guild, tech_key="equipment_forge", level=2)
    GuildTechnology.objects.create(guild=guild, tech_key="experience_refine", level=2)
    GuildTechnology.objects.create(guild=guild, tech_key="resource_supply", level=2)

    result = guild_tech_daily_production.run()
    assert result == "dispatched 1 guild tasks"
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


@pytest.mark.django_db
def test_cleanup_invalid_guild_hero_pool_task(monkeypatch, django_user_model):
    from gameplay.services.manor.core import ensure_manor
    from guests.models import Guest, GuestArchetype, GuestRarity, GuestTemplate
    from guilds.models import Guild, GuildBattleLineupEntry, GuildHeroPoolEntry, GuildMember
    from guilds.tasks import cleanup_invalid_guild_hero_pool

    monkeypatch.setattr(
        cleanup_invalid_guild_hero_pool,
        "retry",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("retry should not be called")),
    )

    leader = django_user_model.objects.create_user(username="ghp_cleanup_leader", password="pass")
    manor = ensure_manor(leader)
    guild = Guild.objects.create(name="任务清理帮", founder=leader, is_active=True)
    member = GuildMember.objects.create(guild=guild, user=leader, position="leader")

    template = GuestTemplate.objects.create(
        key="ghp_cleanup_tpl",
        name="清理模板",
        archetype=GuestArchetype.MILITARY,
        rarity=GuestRarity.GREEN,
    )
    guest = Guest.objects.create(
        manor=manor,
        template=template,
        custom_name="清理门客",
        level=10,
        force=100,
        intellect=80,
        defense_stat=90,
        agility=70,
        luck=50,
        current_hp=1,
    )

    entry = GuildHeroPoolEntry.objects.create(
        guild=guild,
        owner_member=member,
        source_guest=guest,
        slot_index=1,
        last_submitted_at=timezone.now() - timedelta(days=8),
    )
    GuildBattleLineupEntry.objects.create(guild=guild, pool_entry=entry, slot_index=1, selected_by=leader)

    # 制造无效数据：成员已不在本帮
    member.is_active = False
    member.save(update_fields=["is_active"])

    result = cleanup_invalid_guild_hero_pool.run()

    assert "cleaned" in result
    assert GuildHeroPoolEntry.objects.filter(pk=entry.pk).count() == 0
    assert GuildBattleLineupEntry.objects.filter(guild=guild).count() == 0
