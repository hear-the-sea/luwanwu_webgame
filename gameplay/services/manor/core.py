"""
庄园和建筑管理服务
"""

from __future__ import annotations

import logging
import math
import re
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from threading import Lock

from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from common.utils.celery import safe_apply_async
from core.exceptions import (
    BuildingConcurrentUpgradeLimitError,
    BuildingMaxLevelError,
    BuildingUpgradingError,
    GameError,
    MessageError,
)
from core.utils.imports import is_missing_target_import
from core.utils.infrastructure import (
    DATABASE_INFRASTRUCTURE_EXCEPTIONS,
    NOTIFICATION_INFRASTRUCTURE_EXCEPTIONS,
    InfrastructureExceptions,
    combine_infrastructure_exceptions,
)
from core.utils.time_scale import scale_duration

from ...constants import BUILDING_MAX_LEVELS, MAX_CONCURRENT_BUILDING_UPGRADES, BuildingKeys, ManorNameConstants
from ...models import (
    ArenaTournament,
    Building,
    BuildingType,
    ItemTemplate,
    Manor,
    Message,
    MissionRun,
    RaidRun,
    ResourceEvent,
    ScoutRecord,
)
from ..utils.cache import invalidate_home_stats_cache
from ..utils.notifications import notify_user
from . import provisioning as _provisioning
from . import refresh as _refresh

CAPACITY_BASE = 20000
CAPACITY_GROWTH_SILVER = 1.299657
CAPACITY_GROWTH_GRAIN = 1.3905
MANOR_MESSAGE_BEST_EFFORT_EXCEPTIONS: InfrastructureExceptions = combine_infrastructure_exceptions(
    MessageError,
    infrastructure_exceptions=DATABASE_INFRASTRUCTURE_EXCEPTIONS,
)


def calculate_building_capacity(level: int, is_silver_vault: bool = False) -> int:
    growth = CAPACITY_GROWTH_SILVER if is_silver_vault else CAPACITY_GROWTH_GRAIN
    return int(CAPACITY_BASE * (growth ** (level - 1)))


logger = logging.getLogger(__name__)


class ManorNameConflictError(GameError):
    """Raised when the requested manor name is already occupied."""

    error_code = "MANOR_NAME_CONFLICT"


class ManorRenameValidationError(GameError):
    """Raised when the requested manor name is invalid."""

    error_code = "MANOR_RENAME_VALIDATION_ERROR"


class ManorRenameItemError(GameError):
    """Raised when rename-card lookup or consumption fails."""

    error_code = "MANOR_RENAME_ITEM_ERROR"


class ManorNotFoundError(GameError):
    """Raised when a user tries to access gameplay without a provisioned manor."""

    error_code = "MANOR_NOT_FOUND"
    default_message = "庄园尚未初始化，请重新登录后再试"


INITIAL_PEACE_SHIELD_KEYS: tuple[str, ...] = (
    "peace_shield_small",
    "peace_shield_medium",
    "peace_shield_large",
)

_LOCAL_REFRESH_FALLBACK: dict[int, float] = {}
_LOCAL_REFRESH_FALLBACK_LOCK = Lock()
_LOCAL_REFRESH_FALLBACK_MAX_SIZE = 10000
_LOCAL_REFRESH_FALLBACK_CLEANUP_BATCH = 2000
_LOCAL_REFRESH_FALLBACK_EVICT_COUNT = 1000


def _cleanup_local_fallback_cache(now_monotonic: float, stale_threshold: float) -> None:
    _refresh.cleanup_local_fallback_cache(
        _LOCAL_REFRESH_FALLBACK,
        max_size=_LOCAL_REFRESH_FALLBACK_MAX_SIZE,
        cleanup_batch=_LOCAL_REFRESH_FALLBACK_CLEANUP_BATCH,
        evict_count=_LOCAL_REFRESH_FALLBACK_EVICT_COUNT,
        now_monotonic=now_monotonic,
        stale_threshold=stale_threshold,
    )


def _should_skip_refresh_by_local_fallback(manor_id: int, min_interval: int) -> bool:
    return _refresh.should_skip_refresh_by_local_fallback(
        _LOCAL_REFRESH_FALLBACK,
        state_lock=_LOCAL_REFRESH_FALLBACK_LOCK,
        max_size=_LOCAL_REFRESH_FALLBACK_MAX_SIZE,
        cleanup_batch=_LOCAL_REFRESH_FALLBACK_CLEANUP_BATCH,
        evict_count=_LOCAL_REFRESH_FALLBACK_EVICT_COUNT,
        manor_id=manor_id,
        min_interval=min_interval,
        monotonic_func=time.monotonic,
    )


def get_manor(user) -> Manor:
    try:
        return user.manor
    except Manor.DoesNotExist as exc:
        raise ManorNotFoundError() from exc


def bootstrap_manor(user, region: str = "overseas", initial_name: str | None = None) -> Manor:
    normalized_name = (initial_name or "").strip() or None
    manor, created = Manor.objects.get_or_create(user=user)
    location_assigned = manor.coordinate_x > 0 and manor.coordinate_y > 0
    if created or not location_assigned:
        try:
            assigned = _assign_manor_location_and_name(manor, region=region, normalized_name=normalized_name)
        except ManorNameConflictError:
            if created:
                Manor.objects.filter(pk=manor.pk, user=user, coordinate_x=0, coordinate_y=0).delete()
            raise
        if not assigned:
            if created:
                Manor.objects.filter(pk=manor.pk, user=user, coordinate_x=0, coordinate_y=0).delete()
            raise RuntimeError("Failed to allocate a unique manor coordinate after multiple attempts")
        manor.refresh_from_db(fields=["region", "coordinate_x", "coordinate_y", "name"])
    _ensure_manor_provisioning(manor, created=created)
    return manor


def ensure_manor(user, region: str = "overseas", initial_name: str | None = None) -> Manor:
    return bootstrap_manor(user, region=region, initial_name=initial_name)


def _ensure_manor_provisioning(manor: Manor, *, created: bool) -> None:
    _provisioning.ensure_manor_provisioning(
        manor,
        created=created,
        bootstrap_buildings_func=bootstrap_buildings,
        ensure_buildings_exist_func=ensure_buildings_exist,
        grant_initial_peace_shield_func=_grant_initial_peace_shield,
        deliver_active_global_mail_campaigns_func=_deliver_active_global_mail_campaigns,
    )


def _assign_manor_location_and_name(manor: Manor, *, region: str, normalized_name: str | None) -> bool:
    return _provisioning.assign_manor_location_and_name(
        manor,
        region=region,
        normalized_name=normalized_name,
        generate_unique_coordinate_func=generate_unique_coordinate,
        is_manor_name_available_func=is_manor_name_available,
        manor_model=Manor,
        conflict_error_cls=ManorNameConflictError,
    )


def _grant_initial_peace_shield(manor: Manor) -> None:
    _provisioning.grant_initial_peace_shield(
        manor,
        initial_peace_shield_keys=INITIAL_PEACE_SHIELD_KEYS,
        item_template_model=ItemTemplate,
        manor_model=Manor,
        timezone_module=timezone,
        logger=logger,
    )


def _deliver_active_global_mail_campaigns(manor: Manor) -> None:
    _provisioning.deliver_active_global_mail_campaigns(
        manor,
        is_missing_global_mail_schema_error_func=_is_missing_global_mail_schema_error,
        logger=logger,
    )


def _is_missing_global_mail_schema_error(exc: BaseException) -> bool:
    return _provisioning.is_missing_global_mail_schema_error(exc)


def generate_unique_coordinate(region: str) -> tuple[int, int]:
    return _provisioning.generate_unique_coordinate(region, manor_model=Manor, logger=logger)


def bootstrap_buildings(manor: Manor) -> None:
    _provisioning.bootstrap_buildings(manor, building_type_model=BuildingType, building_model=Building)


def ensure_buildings_exist(manor: Manor) -> None:
    _provisioning.ensure_buildings_exist(manor, building_type_model=BuildingType, building_model=Building)


def _has_due_manor_refresh_work(manor_id: int, now: datetime | None = None) -> bool:
    return _refresh.has_due_manor_refresh_work(
        mission_run_model=MissionRun,
        scout_record_model=ScoutRecord,
        raid_run_model=RaidRun,
        arena_tournament_model=ArenaTournament,
        manor_id=manor_id,
        now=now or timezone.now(),
        logger=logger,
    )


def _noop_manor_step(_manor: Manor) -> None:
    return None


def _run_manor_refresh(
    manor: Manor,
    *,
    prefer_async: bool,
    include_activity_refresh: bool,
    sync_resource_projection_func: Callable[[Manor], None],
) -> None:
    from ..arena import refresh_arena_activity
    from ..missions import refresh_mission_runs
    from ..raid import refresh_raid_runs, refresh_scout_records

    _refresh.refresh_manor_state(
        manor,
        prefer_async=prefer_async,
        include_activity_refresh=include_activity_refresh,
        settings_obj=settings,
        cache_backend=cache,
        logger=logger,
        timezone_module=timezone,
        finalize_upgrades_func=finalize_upgrades,
        has_due_manor_refresh_work_func=_has_due_manor_refresh_work,
        should_skip_refresh_by_local_fallback_func=_should_skip_refresh_by_local_fallback,
        sync_resource_production_func=sync_resource_projection_func,
        refresh_mission_runs_func=refresh_mission_runs,
        refresh_scout_records_func=refresh_scout_records,
        refresh_raid_runs_func=refresh_raid_runs,
        refresh_arena_activity_func=refresh_arena_activity,
    )


def refresh_manor_state(
    manor: Manor,
    *,
    prefer_async: bool = False,
    include_activity_refresh: bool = False,
) -> None:
    from ..resources import sync_resource_production

    _run_manor_refresh(
        manor,
        prefer_async=prefer_async,
        include_activity_refresh=include_activity_refresh,
        sync_resource_projection_func=sync_resource_production,
    )


def project_manor_activity_for_read(
    manor: Manor,
    *,
    prefer_async: bool = False,
) -> None:
    """
    Apply the read-side manor projection and compensate due activity state.

    This keeps page reads lightweight for resources while still finalizing
    overdue mission/scout/raid/arena activity so guest availability and status
    displays do not lag behind completed activity.
    """
    from ..resources import project_resource_production_for_read

    project_resource_production_for_read(manor)
    _run_manor_refresh(
        manor,
        prefer_async=prefer_async,
        include_activity_refresh=True,
        sync_resource_projection_func=_noop_manor_step,
    )


def finalize_building_upgrade(building: Building, now: datetime | None = None, send_notification: bool = True) -> bool:
    now = now or timezone.now()
    if not building.pk:
        return False

    updated = Building.objects.filter(
        pk=building.pk,
        is_upgrading=True,
        upgrade_complete_at__isnull=False,
        upgrade_complete_at__lte=now,
    ).update(
        level=F("level") + 1,
        is_upgrading=False,
        upgrade_complete_at=None,
    )
    if updated != 1:
        return False

    building = Building.objects.select_related("manor", "building_type").get(pk=building.pk)

    building_key = building.building_type.key
    if building_key == BuildingKeys.SILVER_VAULT:
        new_capacity = calculate_building_capacity(building.level, is_silver_vault=True)
        Manor.objects.filter(pk=building.manor_id).update(silver_capacity=new_capacity)
    elif building_key == BuildingKeys.GRANARY:
        new_capacity = calculate_building_capacity(building.level, is_silver_vault=False)
        Manor.objects.filter(pk=building.manor_id).update(grain_capacity=new_capacity)

    building.manor.invalidate_building_cache()
    invalidate_home_stats_cache(building.manor_id)
    if send_notification:
        from ..utils.messages import create_message

        try:
            create_message(
                manor=building.manor,
                kind=Message.Kind.SYSTEM,
                title=f"{building.building_type.name} 升级完成",
                body=f"等级 Lv{building.level - 1} → Lv{building.level}",
            )
        except MANOR_MESSAGE_BEST_EFFORT_EXCEPTIONS as exc:
            logger.warning(
                "building upgrade message creation failed: building_id=%s manor_id=%s error=%s",
                building.id,
                building.manor_id,
                exc,
                exc_info=True,
            )
            return True

        try:
            notify_user(
                building.manor.user_id,
                {
                    "kind": "system",
                    "title": f"{building.building_type.name} 升级完成",
                    "building_key": building.building_type.key,
                    "level": building.level,
                },
                log_context="building upgrade notification",
            )
        except NOTIFICATION_INFRASTRUCTURE_EXCEPTIONS as exc:
            logger.warning(
                "building upgrade notification failed: building_id=%s manor_id=%s error=%s",
                building.id,
                building.manor_id,
                exc,
                exc_info=True,
            )
    return True


def finalize_upgrades(manor: Manor, now: datetime | None = None) -> None:
    now = now or timezone.now()
    ready = list(
        manor.buildings.select_related("building_type").filter(is_upgrading=True, upgrade_complete_at__lte=now)
    )
    if not ready:
        return
    for building in ready:
        finalize_building_upgrade(building, now=now, send_notification=True)


def schedule_building_completion(building: Building, eta_seconds: int) -> None:
    countdown = max(0, int(eta_seconds))
    try:
        from gameplay.tasks import complete_building_upgrade
    except ImportError as exc:
        if not is_missing_target_import(exc, "gameplay.tasks"):
            raise
        logger.warning("Unable to import complete_building_upgrade task; skip scheduling", exc_info=True)
        return

    def _dispatch_completion() -> None:
        dispatched = safe_apply_async(
            complete_building_upgrade,
            args=[building.id],
            countdown=countdown,
            logger=logger,
            log_message="complete_building_upgrade dispatch failed",
        )
        if not dispatched:
            logger.error(
                "complete_building_upgrade dispatch returned False; building may remain upgrading",
                extra={
                    "task_name": "complete_building_upgrade",
                    "building_id": getattr(building, "id", None),
                    "manor_id": getattr(building, "manor_id", None),
                },
            )

    transaction.on_commit(_dispatch_completion)


def start_upgrade(building: Building) -> None:
    from ..technology import get_building_cost_reduction

    manor = building.manor
    finalize_upgrades(manor)
    building.refresh_from_db(fields=["level", "is_upgrading", "upgrade_complete_at"])

    if building.is_upgrading:
        raise BuildingUpgradingError()

    building_key = building.building_type.key
    max_level = BUILDING_MAX_LEVELS.get(building_key)
    if max_level is not None and building.level >= max_level:
        raise BuildingMaxLevelError(building.building_type.name, max_level)

    upgrading_count = Building.objects.filter(manor=manor, is_upgrading=True).count()
    if upgrading_count >= MAX_CONCURRENT_BUILDING_UPGRADES:
        raise BuildingConcurrentUpgradeLimitError(MAX_CONCURRENT_BUILDING_UPGRADES)

    base_cost = building.next_level_cost()
    cost_reduction = get_building_cost_reduction(manor)
    reduction_multiplier = max(0, 1 - cost_reduction)
    cost = {resource: max(1, math.ceil(amount * reduction_multiplier)) for resource, amount in base_cost.items()}

    base_duration = building.next_level_duration()
    time_reduction = manor.citang_building_time_reduction
    duration_seconds = max(1, int(base_duration * (1 - time_reduction)))
    duration_seconds = scale_duration(duration_seconds, minimum=1)

    with transaction.atomic():
        manor = Manor.objects.select_for_update().get(pk=manor.pk)
        building = Building.objects.select_for_update().get(pk=building.pk)
        if building.is_upgrading:
            raise BuildingUpgradingError()

        upgrading_count = Building.objects.filter(manor=manor, is_upgrading=True).count()
        if upgrading_count >= MAX_CONCURRENT_BUILDING_UPGRADES:
            raise BuildingConcurrentUpgradeLimitError(MAX_CONCURRENT_BUILDING_UPGRADES)

        from ..resources import spend_resources_locked

        spend_resources_locked(manor, cost, building.building_type.name, ResourceEvent.Reason.UPGRADE_COST)

        silver_spent = cost.get("silver", 0)
        if silver_spent > 0:
            from .prestige import add_prestige_silver_locked

            add_prestige_silver_locked(manor, silver_spent)

        building.upgrade_complete_at = timezone.now() + timedelta(seconds=duration_seconds)
        building.is_upgrading = True
        building.save(update_fields=["upgrade_complete_at", "is_upgrading"])
        schedule_building_completion(building, duration_seconds)


MANOR_NAME_MIN_LENGTH = ManorNameConstants.MIN_LENGTH
MANOR_NAME_MAX_LENGTH = ManorNameConstants.MAX_LENGTH
MANOR_NAME_PATTERN = re.compile(r"^[\u4e00-\u9fa5a-zA-Z0-9_]+$")
BANNED_WORDS = ManorNameConstants.BANNED_WORDS


def validate_manor_name(name: str) -> tuple[bool, str]:
    if not name or not name.strip():
        return False, "名称不能为空"

    name = name.strip()
    if len(name) < MANOR_NAME_MIN_LENGTH:
        return False, f"名称至少需要{MANOR_NAME_MIN_LENGTH}个字符"
    if len(name) > MANOR_NAME_MAX_LENGTH:
        return False, f"名称最多{MANOR_NAME_MAX_LENGTH}个字符"
    if not MANOR_NAME_PATTERN.match(name):
        return False, "名称仅支持中文、英文、数字和下划线"

    name_lower = name.lower()
    for word in BANNED_WORDS:
        if word.lower() in name_lower:
            return False, "名称包含敏感词"

    return True, ""


def is_manor_name_available(name: str, exclude_manor_id: int | None = None) -> bool:
    queryset = Manor.objects.filter(name__iexact=name.strip())
    if exclude_manor_id:
        queryset = queryset.exclude(id=exclude_manor_id)
    return not queryset.exists()


@transaction.atomic
def rename_manor(manor: Manor, new_name: str, consume_item: bool = True) -> None:
    from ...models import InventoryItem, ItemTemplate

    new_name = new_name.strip()
    valid, error_msg = validate_manor_name(new_name)
    if not valid:
        raise ManorRenameValidationError(error_msg)
    if not is_manor_name_available(new_name, exclude_manor_id=manor.id):
        raise ManorNameConflictError("该名称已被使用")

    if consume_item:
        try:
            rename_card = ItemTemplate.objects.get(key="manor_rename_card")
        except ItemTemplate.DoesNotExist:
            raise ManorRenameItemError("庄园命名卡道具未配置")

        inventory_item = (
            InventoryItem.objects.select_for_update()
            .filter(
                manor=manor,
                template=rename_card,
                storage_location=InventoryItem.StorageLocation.WAREHOUSE,
                quantity__gt=0,
            )
            .first()
        )

        if not inventory_item:
            raise ManorRenameItemError("您没有庄园命名卡")

        updated = InventoryItem.objects.filter(pk=inventory_item.pk, quantity__gte=1).update(quantity=F("quantity") - 1)
        if not updated:
            raise ManorRenameItemError("道具消耗失败，请重试")

        InventoryItem.objects.filter(pk=inventory_item.pk, quantity__lte=0).delete()

    old_name = manor.name or manor.display_name
    manor.name = new_name
    try:
        manor.save(update_fields=["name"])
    except IntegrityError:
        logger.warning("Manor rename race condition detected for %s by user %s", new_name, manor.user_id)
        raise ManorNameConflictError("该名称已被使用")

    from ..utils.messages import create_message

    def _send_rename_message() -> None:
        try:
            create_message(
                manor=manor,
                kind=Message.Kind.SYSTEM,
                title="庄园更名成功",
                body=f"您的庄园已从「{old_name}」更名为「{new_name}」",
            )
        except MANOR_MESSAGE_BEST_EFFORT_EXCEPTIONS as exc:
            logger.warning(
                "manor rename message failed: manor_id=%s old_name=%s new_name=%s error=%s",
                manor.id,
                old_name,
                new_name,
                exc,
                exc_info=True,
            )

    transaction.on_commit(_send_rename_message)


def get_rename_card_count(manor: Manor) -> int:
    from ...models import InventoryItem, ItemTemplate

    try:
        rename_card = ItemTemplate.objects.get(key="manor_rename_card")
    except ItemTemplate.DoesNotExist:
        return 0

    item = InventoryItem.objects.filter(
        manor=manor,
        template=rename_card,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    ).first()

    return item.quantity if item else 0
