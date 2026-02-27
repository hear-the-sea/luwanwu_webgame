"""
门客招募系统服务
"""

from __future__ import annotations

import logging
import random
from datetime import timedelta
from typing import TYPE_CHECKING, Dict, Iterable, List, Optional, Sequence, Tuple

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from core.config import RECRUITMENT
from core.exceptions import (
    GuestCapacityFullError,
    GuestNotIdleError,
    InsufficientStockError,
    InvalidAllocationError,
    NoTemplateAvailableError,
    RetainerCapacityFullError,
)
from core.utils.time_scale import scale_duration

if TYPE_CHECKING:
    from gameplay.models import Manor

from ..models import (
    DEFENSE_TO_HP_MULTIPLIER,
    MAX_GUEST_SKILL_SLOTS,
    MIN_HP_FLOOR,
    Guest,
    GuestRarity,
    GuestRecruitment,
    GuestSkill,
    GuestStatus,
    GuestTemplate,
    RecruitmentCandidate,
    RecruitmentPool,
    RecruitmentPoolEntry,
    RecruitmentRecord,
)
from ..utils.name_generator import generate_random_name
from ..utils.recruitment_utils import HERMIT_RARITY, RARITY_ORDER, choose_rarity, filter_entries, weighted_choice
from ..utils.recruitment_variance import apply_recruitment_variance

logger = logging.getLogger(__name__)

# 不可重复招募的稀有度（绿色及以上）
NON_REPEATABLE_RARITIES = frozenset(
    {
        GuestRarity.GREEN,
        GuestRarity.BLUE,
        GuestRarity.RED,
        GuestRarity.PURPLE,
        GuestRarity.ORANGE,
    }
)

CORE_POOL_TIERS = (
    RecruitmentPool.Tier.CUNMU,
    RecruitmentPool.Tier.XIANGSHI,
    RecruitmentPool.Tier.HUISHI,
    RecruitmentPool.Tier.DIANSHI,
)


def _invalidate_recruitment_hall_cache(manor_id: int | None) -> None:
    if not manor_id:
        return
    try:
        from gameplay.services.utils.cache import invalidate_recruitment_hall_cache

        invalidate_recruitment_hall_cache(int(manor_id))
    except Exception:
        logger.debug("Failed to invalidate recruitment hall cache for manor_id=%s", manor_id, exc_info=True)


# ============ 模板缓存 ============


def _get_recruitable_templates_by_rarity() -> Dict[str, List[GuestTemplate]]:
    """
    获取所有可招募模板，按稀有度分组缓存。

    使用 Django Cache 缓存结果，支持多进程共享。
    当模板数据变更时，需要调用 clear_template_cache() 刷新。

    Returns:
        按稀有度分组的模板字典
    """
    from django.core.cache import cache

    from gameplay.services.utils.cache import CACHE_TIMEOUT_CONFIG, CacheKeys

    cache_key = CacheKeys.GUEST_TEMPLATES_BY_RARITY
    cached = cache.get(cache_key)
    if cached is not None:
        # 缓存命中，重建模板对象
        template_ids_by_rarity = cached
        all_template_ids = [tid for ids in template_ids_by_rarity.values() for tid in ids]
        templates = {t.id: t for t in GuestTemplate.objects.filter(id__in=all_template_ids)}
        result = {}
        for rarity, ids in template_ids_by_rarity.items():
            result[rarity] = [templates[tid] for tid in ids if tid in templates]
        return result

    # 缓存未命中，查询数据库
    templates = list(GuestTemplate.objects.filter(recruitable=True))
    result: Dict[str, List[GuestTemplate]] = {}
    template_ids_by_rarity: Dict[str, List[int]] = {}

    for template in templates:
        # 隐士虽然是 black，但不应混入普通 black 池（隐士有专门的抽取逻辑）
        if template.is_hermit:
            continue

        if template.rarity not in result:
            result[template.rarity] = []
            template_ids_by_rarity[template.rarity] = []
        result[template.rarity].append(template)
        template_ids_by_rarity[template.rarity].append(template.id)

    # 缓存模板ID列表（可序列化）
    cache.set(cache_key, template_ids_by_rarity, timeout=CACHE_TIMEOUT_CONFIG)
    return result


def _get_hermit_templates() -> List[GuestTemplate]:
    """
    获取所有可招募的隐士模板（缓存）。

    Returns:
        隐士模板列表
    """
    from django.core.cache import cache

    from gameplay.services.utils.cache import CACHE_TIMEOUT_CONFIG, CacheKeys

    cache_key = CacheKeys.HERMIT_TEMPLATES
    cached = cache.get(cache_key)
    if cached is not None:
        # 缓存命中，重建模板对象
        return list(GuestTemplate.objects.filter(id__in=cached))

    # 缓存未命中，查询数据库
    templates = list(
        GuestTemplate.objects.filter(
            rarity=GuestRarity.BLACK,
            is_hermit=True,
            recruitable=True,
        )
    )
    template_ids = [t.id for t in templates]
    cache.set(cache_key, template_ids, timeout=CACHE_TIMEOUT_CONFIG)
    return templates


def clear_template_cache() -> None:
    """
    清除模板缓存。

    当 GuestTemplate 数据变更时调用此函数刷新缓存。
    """
    from django.core.cache import cache

    from gameplay.services.utils.cache import CacheKeys

    cache.delete_many(
        [
            CacheKeys.GUEST_TEMPLATES_BY_RARITY,
            CacheKeys.HERMIT_TEMPLATES,
        ]
    )


def _filter_templates(
    templates: List[GuestTemplate],
    excluded_ids: set[int],
) -> List[GuestTemplate]:
    """从模板列表中过滤掉已排除的模板"""
    if not excluded_ids:
        return templates
    return [t for t in templates if t.id not in excluded_ids]


def get_excluded_template_ids(manor: Manor) -> set[int]:
    """
    获取玩家不能再招募的门客模板ID。

    排除规则：
    - 绿色及以上稀有度：已拥有则排除
    - 黑色隐士：已拥有则排除
    - 黑色/灰色普通：可重复招募，不排除

    Args:
        manor: 庄园对象

    Returns:
        需要排除的模板ID集合
    """
    # 直接使用 values_list 获取需要的字段，无需 select_related
    owned_templates = manor.guests.values_list("template_id", "template__rarity", "template__is_hermit")

    excluded = set()
    for template_id, rarity, is_hermit in owned_templates:
        # 绿色及以上稀有度排除
        if rarity in NON_REPEATABLE_RARITIES:
            excluded.add(template_id)
        # 黑色隐士也排除
        elif rarity == GuestRarity.BLACK and is_hermit:
            excluded.add(template_id)

    return excluded


def list_pools(core_only: bool = False, *, include_entries: bool = True) -> Iterable[RecruitmentPool]:
    """列出所有招募卡池，按级别从高到低排序（殿试->村募）"""
    qs = RecruitmentPool.objects.all()
    if include_entries:
        qs = qs.prefetch_related("entries__template")
    if core_only:
        qs = qs.filter(tier__in=CORE_POOL_TIERS)

    # 定义排序优先级：殿试 > 会试 > 乡试 > 村募
    tier_priority = {
        RecruitmentPool.Tier.DIANSHI: 0,
        RecruitmentPool.Tier.HUISHI: 1,
        RecruitmentPool.Tier.XIANGSHI: 2,
        RecruitmentPool.Tier.CUNMU: 3,
    }

    pools = list(qs)
    pools.sort(key=lambda p: tier_priority.get(p.tier, 99))
    return pools


def get_pool_recruitment_duration_seconds(pool: RecruitmentPool) -> int:
    """获取卡池招募倒计时秒数（仅使用 YAML/数据库配置并应用全局时间倍率）。"""
    base_seconds = int(getattr(pool, "cooldown_seconds", 0) or 0)
    if base_seconds <= 0:
        return 0
    return scale_duration(base_seconds, minimum=1)


def _get_pool_daily_draw_limit() -> int:
    """获取单卡池每日招募上限。"""
    value = int(getattr(RECRUITMENT, "DAILY_POOL_DRAW_LIMIT", 300) or 300)
    return max(1, value)


def _count_pool_draws_today(manor_id: int, pool_id: int, *, now=None) -> int:
    """
    统计指定庄园在“今日”对指定卡池已发起的招募次数。

    仅统计 pending/completed，失败记录不计入上限。
    """
    current_time = now or timezone.now()
    local_now = timezone.localtime(current_time)
    day_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    valid_statuses = (GuestRecruitment.Status.PENDING, GuestRecruitment.Status.COMPLETED)
    return GuestRecruitment.objects.filter(
        manor_id=manor_id,
        pool_id=pool_id,
        status__in=valid_statuses,
        started_at__gte=day_start,
        started_at__lt=day_end,
    ).count()


def has_active_guest_recruitment(manor: Manor) -> bool:
    """是否存在进行中的门客招募。"""
    return manor.guest_recruitments.filter(status=GuestRecruitment.Status.PENDING).exists()


def get_active_guest_recruitment(manor: Manor) -> GuestRecruitment | None:
    """获取最早完成的一条进行中门客招募。"""
    return (
        manor.guest_recruitments.filter(status=GuestRecruitment.Status.PENDING)
        .select_related("pool")
        .order_by("complete_at")
        .first()
    )


def available_guests(manor: Manor) -> Sequence[Guest]:
    """获取庄园所有可用门客"""
    return (
        manor.guests.select_related("template")
        .prefetch_related("gear_items__template")
        .order_by("-template__rarity", "-level")
    )


def list_candidates(manor: Manor) -> QuerySet[RecruitmentCandidate]:
    """列出庄园的招募候选门客"""
    return manor.candidates.only("id", "display_name", "rarity", "rarity_revealed", "created_at").order_by("created_at")


def _build_rarity_search_order(rarity: str) -> list[str]:
    search_order = [rarity]
    if rarity in RARITY_ORDER:
        idx = RARITY_ORDER.index(rarity)
        search_order.extend(RARITY_ORDER[idx + 1 :] + RARITY_ORDER[:idx])
    else:
        search_order.extend(RARITY_ORDER)
    return search_order


def _resolve_entry_template(
    entry: RecruitmentPoolEntry,
    rarity_hint: str,
    excluded_ids: set[int],
    explicit_template_ids: set[int],
    templates_by_rarity: Dict[str, List[GuestTemplate]],
    category_cache: Dict[Tuple[str | None, str | None], List[GuestTemplate]],
    rng: random.Random,
) -> GuestTemplate | None:
    if entry.template_id:
        return entry.template if entry.template.recruitable else None

    rarity_value = entry.rarity or rarity_hint
    if not rarity_value:
        return None
    archetype_key = entry.archetype or None
    cache_key = (rarity_value, archetype_key)
    if cache_key not in category_cache:
        base_templates = templates_by_rarity.get(rarity_value, [])
        if archetype_key:
            base_templates = [t for t in base_templates if t.archetype == archetype_key]
        category_cache[cache_key] = _filter_templates(base_templates, explicit_template_ids | excluded_ids)
    templates = category_cache[cache_key]
    return rng.choice(templates) if templates else None


def choose_template_from_entries(
    entries: List[RecruitmentPoolEntry],
    rng: random.Random,
    excluded_ids: set[int] | None = None,
    *,
    templates_by_rarity: Dict[str, List[GuestTemplate]] | None = None,
    hermit_templates: List[GuestTemplate] | None = None,
) -> GuestTemplate:
    """
    从卡池条目中随机选择一个门客模板。

    如果 entries 为空，直接从所有 recruitable=True 的模板中按稀有度随机选择。

    Args:
        entries: 卡池条目列表（可为空）
        rng: 随机数生成器
        excluded_ids: 需要排除的模板ID集合（已拥有的门客）

    Returns:
        随机选中的门客模板

    Raises:
        NoTemplateAvailableError: 没有可用模板时抛出
    """
    if excluded_ids is None:
        excluded_ids = set()

    rarity = choose_rarity(rng)

    # 处理隐士类型：从缓存的隐士模板中选择
    if rarity == HERMIT_RARITY:
        loaded_hermit_templates = hermit_templates if hermit_templates is not None else _get_hermit_templates()
        available_hermit_templates = _filter_templates(loaded_hermit_templates, excluded_ids)
        if available_hermit_templates:
            return rng.choice(available_hermit_templates)
        # 无可用隐士，降级为普通黑色
        rarity = GuestRarity.BLACK

    # 如果没有配置 entries，直接从缓存的模板中选择
    if not entries:
        return _choose_template_by_rarity_cached(
            rarity,
            excluded_ids,
            rng,
            templates_by_rarity=templates_by_rarity,
        )

    # 有 entries 配置时，使用原有逻辑（但使用缓存的模板数据）
    filtered_entries = [e for e in entries if not e.template_id or e.template_id not in excluded_ids]

    explicit_template_ids = {entry.template_id for entry in filtered_entries if entry.template_id}
    # 获取缓存的模板数据
    loaded_templates_by_rarity = (
        templates_by_rarity if templates_by_rarity is not None else _get_recruitable_templates_by_rarity()
    )
    category_cache: Dict[Tuple[str | None, str | None], List[GuestTemplate]] = {}

    search_order = _build_rarity_search_order(rarity)

    for rarity_option in search_order:
        options = filter_entries(filtered_entries, rarity_option)
        if not options:
            continue
        chosen_entry = weighted_choice(options, rng)
        template = _resolve_entry_template(
            chosen_entry,
            rarity_option,
            excluded_ids,
            explicit_template_ids,
            loaded_templates_by_rarity,
            category_cache,
            rng,
        )
        if template:
            return template

    # 全局回退（使用缓存版本）
    return _choose_template_by_rarity_cached(
        rarity,
        excluded_ids,
        rng,
        templates_by_rarity=loaded_templates_by_rarity,
    )


def _choose_template_by_rarity_cached(
    rarity: str,
    excluded_ids: set[int],
    rng: random.Random,
    *,
    templates_by_rarity: Dict[str, List[GuestTemplate]] | None = None,
) -> GuestTemplate:
    """
    按稀有度从缓存的模板中随机选择。

    使用预加载的模板缓存，避免数据库查询。
    如果目标稀有度无可用模板，会尝试降级到其他稀有度。
    """
    loaded_templates_by_rarity = (
        templates_by_rarity if templates_by_rarity is not None else _get_recruitable_templates_by_rarity()
    )

    # 构建搜索顺序：目标稀有度优先，然后按顺序尝试其他稀有度
    search_order = _build_rarity_search_order(rarity)

    for rarity_option in search_order:
        templates = loaded_templates_by_rarity.get(rarity_option, [])
        available = _filter_templates(templates, excluded_ids)
        if available:
            return rng.choice(available)

    raise NoTemplateAvailableError()


def _choose_template_by_rarity(
    rarity: str,
    excluded_ids: set[int],
    rng: random.Random,
) -> GuestTemplate:
    """
    按稀有度从所有可招募模板中随机选择。

    如果目标稀有度无可用模板，会尝试降级到其他稀有度。
    """
    # 构建搜索顺序：目标稀有度优先，然后按顺序尝试其他稀有度
    search_order = _build_rarity_search_order(rarity)

    for rarity_option in search_order:
        qs = GuestTemplate.objects.filter(rarity=rarity_option, recruitable=True)
        if rarity_option == GuestRarity.BLACK:
            qs = qs.filter(is_hermit=False)
        if excluded_ids:
            qs = qs.exclude(id__in=excluded_ids)
        templates = list(qs)
        if templates:
            return rng.choice(templates)

    raise NoTemplateAvailableError()


def grant_template_skills(guest: Guest) -> None:
    """为门客授予模板预设技能"""
    initial_skills = list(guest.template.initial_skills.all())
    if not initial_skills:
        return
    existing_skill_ids = set(guest.guest_skills.values_list("skill_id", flat=True))
    capacity_left = MAX_GUEST_SKILL_SLOTS - len(existing_skill_ids)
    if capacity_left <= 0:
        return

    skills_to_create = []
    for skill in initial_skills:
        if skill.id in existing_skill_ids:
            continue
        if len(skills_to_create) >= capacity_left:
            break
        skills_to_create.append(
            GuestSkill(
                guest=guest,
                skill=skill,
                source=GuestSkill.Source.TEMPLATE,
            )
        )

    if skills_to_create:
        GuestSkill.objects.bulk_create(skills_to_create)


def create_guest_from_template(
    *,
    manor: Manor,
    template: GuestTemplate,
    rarity: Optional[str] = None,
    archetype: Optional[str] = None,
    custom_name: str = "",
    rng: Optional[random.Random] = None,
    grant_skills: bool = True,
    save: bool = True,
) -> Guest:
    """
    按模板创建门客（含属性波动、初始HP与技能）。

    Args:
        manor: 所属庄园
        template: 门客模板
        rarity: 用于属性波动的稀有度（默认使用模板稀有度）
        archetype: 用于属性波动的流派（默认使用模板流派）
        custom_name: 自定义名称（黑/灰门客使用）
        rng: 随机数生成器
        grant_skills: 是否授予模板技能（需要已保存）
        save: 是否直接保存到数据库
    """
    rng = rng or random.Random()
    effective_rarity = rarity or template.rarity
    effective_archetype = archetype or template.archetype

    gender_choice = template.default_gender
    if not gender_choice or gender_choice == "unknown":
        gender_choice = rng.choice(["male", "female"])
    morality_value = template.default_morality or rng.randint(30, 100)

    template_attrs = {
        "force": template.base_attack,
        "intellect": template.base_intellect,
        "defense": template.base_defense,
        "agility": template.base_agility,
        "luck": template.base_luck,
    }
    varied_attrs = apply_recruitment_variance(
        template_attrs,
        rarity=effective_rarity,
        archetype=effective_archetype,
        rng=rng,
    )

    # 预计算初始 HP（与 Guest.max_hp property 保持一致）
    initial_hp = max(
        MIN_HP_FLOOR,
        template.base_hp + varied_attrs["defense"] * DEFENSE_TO_HP_MULTIPLIER,
    )

    guest = Guest(
        manor=manor,
        template=template,
        custom_name=custom_name,
        force=varied_attrs["force"],
        intellect=varied_attrs["intellect"],
        defense_stat=varied_attrs["defense"],
        agility=varied_attrs["agility"],
        luck=varied_attrs["luck"],
        # 记录初始属性（用于计算升级成长）
        initial_force=varied_attrs["force"],
        initial_intellect=varied_attrs["intellect"],
        initial_defense=varied_attrs["defense"],
        initial_agility=varied_attrs["agility"],
        loyalty=60,
        gender=gender_choice,
        morality=morality_value,
        current_hp=initial_hp,
    )

    if save:
        guest.save()
        if grant_skills:
            grant_template_skills(guest)

    return guest


def reveal_candidate_rarity(manor: Manor) -> int:
    """
    使用放大镜显示所有候选门客的稀有度。

    Args:
        manor: 庄园对象

    Returns:
        被显示的候选门客数量
    """
    candidates = manor.candidates.filter(rarity_revealed=False)
    count = candidates.update(rarity_revealed=True)
    if count > 0:
        _invalidate_recruitment_hall_cache(getattr(manor, "id", None))
    return count


@transaction.atomic
def use_magnifying_glass_for_candidates(manor: Manor, item_id: int) -> int:
    """
    使用放大镜显示所有未显现候选门客稀有度（原子化版本）。

    关键保证：
    - 稀有度显现与道具扣减在同一事务中完成
    - 任一步失败都会整体回滚，避免“显现成功但扣道具失败”导致可重复白嫖
    - 锁顺序统一为 Manor -> InventoryItem -> RecruitmentCandidate
    """
    from gameplay.models import InventoryItem
    from gameplay.models import Manor as ManorModel
    from gameplay.services.inventory.core import consume_inventory_item_locked

    ManorModel.objects.select_for_update().get(pk=manor.pk)

    locked_item = (
        InventoryItem.objects.select_for_update()
        .select_related("template")
        .filter(
            pk=item_id,
            manor=manor,
            template__key="fangdajing",
            storage_location=InventoryItem.StorageLocation.WAREHOUSE,
        )
        .first()
    )
    if not locked_item:
        raise ValueError("道具不存在或不属于您的庄园")
    if locked_item.quantity <= 0:
        raise InsufficientStockError(locked_item.template.name, 1, locked_item.quantity)

    count = manor.candidates.filter(rarity_revealed=False).update(rarity_revealed=True)
    if count <= 0:
        return 0

    consume_inventory_item_locked(locked_item, 1)
    _invalidate_recruitment_hall_cache(getattr(manor, "id", None))
    return int(count)


@transaction.atomic
def recruit_guest(manor: Manor, pool: RecruitmentPool, seed: int | None = None) -> List[RecruitmentCandidate]:
    """
    从指定卡池招募门客。

    如果卡池未配置 entries，会从所有 recruitable=True 的模板中按稀有度随机选择。

    Args:
        manor: 庄园对象
        pool: 招募卡池
        seed: 随机数种子（可选）

    Returns:
        招募得到的候选门客列表
    """
    cost = pool.cost or {}
    if cost:
        from gameplay.models import ResourceEvent
        from gameplay.services.resources import spend_resources

        # 并发安全修复：先检查资源是否足够再删除候选
        # 避免资源不足时候选已被删除的问题
        spend_resources(
            manor,
            cost,
            note=f"卡池：{pool.name}",
            reason=ResourceEvent.Reason.RECRUIT_COST,
        )

    # 资源扣除成功后再清空候选门客并生成候选（防止玩家绕过前端确认）
    total_draw_count = pool.draw_count + manor.tavern_recruitment_bonus
    return _build_recruitment_candidates(
        manor,
        pool,
        seed=seed,
        total_draw_count=total_draw_count,
        clear_existing=True,
    )


def _build_recruitment_candidates(
    manor: Manor,
    pool: RecruitmentPool,
    *,
    seed: int | None = None,
    total_draw_count: int | None = None,
    clear_existing: bool = True,
) -> List[RecruitmentCandidate]:
    """
    生成候选门客（不处理资源扣除）。

    Args:
        manor: 庄园对象
        pool: 招募卡池
        seed: 随机种子
        total_draw_count: 候选数量，不传则按“基础+酒馆加成”
        clear_existing: 是否清空已有候选
    """
    if clear_existing:
        manor.candidates.all().delete()

    pool_entries = list(pool.entries.select_related("template"))
    rng = random.Random(seed)
    candidates_to_create: List[RecruitmentCandidate] = []
    templates_by_rarity = _get_recruitable_templates_by_rarity()
    hermit_templates = _get_hermit_templates()

    resolved_draw_count = total_draw_count
    if resolved_draw_count is None:
        resolved_draw_count = pool.draw_count + manor.tavern_recruitment_bonus
    resolved_draw_count = max(1, int(resolved_draw_count))

    # 获取玩家已拥有的需要排除的模板（绿色以上 + 黑色隐士）
    excluded_ids = get_excluded_template_ids(manor)

    for _ in range(resolved_draw_count):
        template = choose_template_from_entries(
            pool_entries,
            rng=rng,
            excluded_ids=excluded_ids,
            templates_by_rarity=templates_by_rarity,
            hermit_templates=hermit_templates,
        )
        template_to_use = template
        display_name = template.name
        # 黑色和灰色门客随机生成名字，但隐士除外（隐士保留原名）
        if template.rarity in (GuestRarity.BLACK, GuestRarity.GRAY) and not template.is_hermit:
            display_name = generate_random_name(rng)
        # 红色和灰色门客自动显示稀有度
        rarity_revealed = template_to_use.rarity in (GuestRarity.RED, GuestRarity.GRAY)
        candidates_to_create.append(
            RecruitmentCandidate(
                manor=manor,
                pool=pool,
                template=template_to_use,
                display_name=display_name,
                rarity=template_to_use.rarity,
                archetype=template_to_use.archetype,
                rarity_revealed=rarity_revealed,
            )
        )
        # 同一次招募中，也不能出现重复的需排除门客
        if template.rarity in NON_REPEATABLE_RARITIES or (template.rarity == GuestRarity.BLACK and template.is_hermit):
            excluded_ids.add(template.id)

    # 批量创建候选门客
    candidates = RecruitmentCandidate.objects.bulk_create(candidates_to_create)
    _invalidate_recruitment_hall_cache(getattr(manor, "id", None))
    return candidates


def _schedule_guest_recruitment_completion(recruitment: GuestRecruitment, eta_seconds: int) -> None:
    """调度门客招募完成任务。"""
    countdown = max(0, int(eta_seconds))
    try:
        from guests.tasks import complete_guest_recruitment
    except Exception:
        logger.warning("Unable to import complete_guest_recruitment task; skip scheduling", exc_info=True)
        return

    transaction.on_commit(
        lambda: complete_guest_recruitment.apply_async(
            args=[recruitment.id],
            countdown=countdown,
            queue="timer",
        )
    )


@transaction.atomic
def start_guest_recruitment(manor: Manor, pool: RecruitmentPool, seed: int | None = None) -> GuestRecruitment:
    """
    启动异步门客招募：立即扣资源，进入倒计时，完成后生成候选。
    """
    from gameplay.models import Manor as ManorModel
    from gameplay.models import ResourceEvent
    from gameplay.services.resources import spend_resources

    locked_manor = ManorModel.objects.select_for_update().get(pk=manor.pk)

    if has_active_guest_recruitment(locked_manor):
        raise ValueError("已有招募正在进行中，请等待当前招募完成。")

    current_time = timezone.now()
    daily_limit = _get_pool_daily_draw_limit()
    draws_today = _count_pool_draws_today(locked_manor.pk, int(pool.pk), now=current_time)
    if draws_today >= daily_limit:
        raise ValueError(f"{pool.name}今日招募次数已达上限（{daily_limit}次）")

    resolved_seed = seed if seed is not None else random.SystemRandom().randint(1, 2**31 - 1)
    draw_count = pool.draw_count + locked_manor.tavern_recruitment_bonus
    duration_seconds = get_pool_recruitment_duration_seconds(pool)
    cost = dict(pool.cost or {})

    if cost:
        spend_resources(
            locked_manor,
            cost,
            note=f"卡池：{pool.name}",
            reason=ResourceEvent.Reason.RECRUIT_COST,
        )

    # 行为与原流程保持一致：开始新招募时清空现有候选
    locked_manor.candidates.all().delete()

    recruitment = GuestRecruitment.objects.create(
        manor=locked_manor,
        pool=pool,
        cost=cost,
        draw_count=max(1, int(draw_count)),
        duration_seconds=max(0, int(duration_seconds)),
        seed=int(resolved_seed),
        complete_at=current_time + timedelta(seconds=max(0, int(duration_seconds))),
    )
    _schedule_guest_recruitment_completion(recruitment, duration_seconds)
    _invalidate_recruitment_hall_cache(getattr(locked_manor, "id", None))
    return recruitment


def finalize_guest_recruitment(
    recruitment: GuestRecruitment,
    *,
    now=None,
    send_notification: bool = False,
) -> bool:
    """
    完成门客招募：生成候选并更新队列状态。
    """
    recruitment_id = getattr(recruitment, "pk", None)
    if not recruitment_id:
        return False

    current_time = now or timezone.now()

    with transaction.atomic():
        from gameplay.models import Manor as ManorModel

        locked = (
            GuestRecruitment.objects.select_for_update()
            .select_related("manor", "manor__user", "pool")
            .filter(pk=recruitment_id)
            .first()
        )
        if not locked or locked.status != GuestRecruitment.Status.PENDING:
            return False
        if locked.complete_at > current_time:
            return False
        if not locked.pool_id:
            locked.status = GuestRecruitment.Status.FAILED
            locked.finished_at = current_time
            locked.error_message = "招募卡池不存在"
            locked.save(update_fields=["status", "finished_at", "error_message"])
            _invalidate_recruitment_hall_cache(getattr(locked, "manor_id", None))
            return False
        ManorModel.objects.select_for_update().filter(pk=locked.manor_id).exists()

        try:
            candidates = _build_recruitment_candidates(
                locked.manor,
                locked.pool,
                seed=locked.seed,
                total_draw_count=locked.draw_count,
                clear_existing=True,
            )
        except Exception as exc:
            logger.exception("Failed to finalize guest recruitment %s: %s", locked.id, exc)
            locked.status = GuestRecruitment.Status.FAILED
            locked.finished_at = current_time
            locked.error_message = str(exc)[:255]
            locked.save(update_fields=["status", "finished_at", "error_message"])
            _invalidate_recruitment_hall_cache(getattr(locked, "manor_id", None))
            return False

        locked.status = GuestRecruitment.Status.COMPLETED
        locked.finished_at = current_time
        locked.result_count = len(candidates)
        locked.error_message = ""
        locked.save(update_fields=["status", "finished_at", "result_count", "error_message"])
        manor = locked.manor
        pool = locked.pool
        candidate_count = len(candidates)
        _invalidate_recruitment_hall_cache(getattr(manor, "id", None))

    if send_notification and pool:
        from gameplay.models import Message
        from gameplay.services.utils.messages import create_message
        from gameplay.services.utils.notifications import notify_user

        title = f"{pool.name}招募完成"
        body = f"您的{pool.name}已完成，生成 {candidate_count} 名候选门客，请前往聚贤庄挑选。"
        create_message(
            manor=manor,
            kind=Message.Kind.SYSTEM,
            title=title,
            body=body,
        )
        notify_user(
            manor.user_id,
            {
                "kind": "system",
                "title": title,
                "pool_key": pool.key,
                "candidate_count": candidate_count,
            },
            log_context="guest recruitment notification",
        )
    return True


def refresh_guest_recruitments(manor: Manor, limit: int = 20) -> int:
    """兜底刷新门客招募状态（用于 worker 中断场景）。"""
    now = timezone.now()
    completed = 0
    recruitments = (
        manor.guest_recruitments.filter(status=GuestRecruitment.Status.PENDING, complete_at__lte=now)
        .select_related("pool", "manor", "manor__user")
        .order_by("complete_at")[:limit]
    )
    for recruitment in recruitments:
        if finalize_guest_recruitment(recruitment, now=now, send_notification=True):
            completed += 1
    return completed


@transaction.atomic
def finalize_candidate(candidate: RecruitmentCandidate) -> Guest:
    """
    确认招募候选门客，将其转为正式门客。

    Args:
        candidate: 候选门客对象

    Returns:
        创建的门客对象

    Raises:
        ValueError: 庄园容量已满时抛出
    """
    from gameplay.models import Manor

    # 使用 select_for_update 锁定庄园，防止并发超出容量
    manor = Manor.objects.select_for_update().get(pk=candidate.manor_id)
    capacity = manor.guest_capacity
    current = manor.guests.count()
    if current >= capacity:
        raise GuestCapacityFullError()
    rng = random.Random()
    template = candidate.template

    # 确定是否需要使用自定义名称（普通黑/灰门客使用随机名，隐士使用原名）
    use_custom_name = candidate.rarity in (GuestRarity.BLACK, GuestRarity.GRAY) and not template.is_hermit

    guest = create_guest_from_template(
        manor=manor,
        template=template,
        rarity=candidate.rarity,
        archetype=candidate.archetype,
        custom_name=candidate.display_name if use_custom_name else "",
        rng=rng,
    )
    RecruitmentRecord.objects.create(
        manor=manor,
        pool=candidate.pool,
        guest=guest,
        rarity=candidate.rarity,
    )
    candidate.delete()
    _invalidate_recruitment_hall_cache(getattr(manor, "id", None))
    return guest


def _preload_templates(template_ids: set[int]) -> Dict[int, GuestTemplate]:
    """预加载模板数据（事务外操作）"""
    return {
        template.id: template
        for template in GuestTemplate.objects.filter(id__in=template_ids).prefetch_related("initial_skills")
    }


def _prepare_guest_objects(
    candidates: List[RecruitmentCandidate],
    template_map: Dict[int, GuestTemplate],
    manor,
    rng: random.Random,
) -> tuple[List[Guest], List[GuestTemplate], List[int]]:
    """准备门客对象（事务外操作，不涉及数据库写入）"""
    guests_to_create: List[Guest] = []
    templates_for_guests: List[GuestTemplate] = []
    candidate_ids_to_delete: List[int] = []

    for candidate in candidates:
        template = template_map.get(candidate.template_id) or candidate.template

        use_custom_name = candidate.rarity in (GuestRarity.BLACK, GuestRarity.GRAY) and not template.is_hermit

        guest = create_guest_from_template(
            manor=manor,
            template=template,
            rarity=candidate.rarity,
            archetype=candidate.archetype,
            custom_name=candidate.display_name if use_custom_name else "",
            rng=rng,
            grant_skills=False,
            save=False,
        )
        guests_to_create.append(guest)
        templates_for_guests.append(template)
        candidate_ids_to_delete.append(candidate.id)

    return guests_to_create, templates_for_guests, candidate_ids_to_delete


@transaction.atomic
def bulk_finalize_candidates(
    candidates: List[RecruitmentCandidate],
) -> Tuple[List[Guest], List[RecruitmentCandidate]]:
    """
    批量确认招募候选门客，将其转为正式门客。

    优化策略：
    1. 使用辅助函数预加载模板数据
    2. 使用辅助函数准备门客对象
    3. 减少事务内的复杂逻辑，提升并发性能

    Args:
        candidates: 候选门客对象列表

    Returns:
        (成功招募的门客列表, 因容量不足而失败的候选列表)
    """
    if not candidates:
        return [], []

    from gameplay.models import Manor

    # 锁定庄园并检查容量
    manor = Manor.objects.select_for_update().get(pk=candidates[0].manor_id)
    capacity = manor.guest_capacity
    current_count = manor.guests.count()
    available_slots = capacity - current_count

    if available_slots <= 0:
        return [], candidates

    to_process = candidates[:available_slots]
    failed = candidates[available_slots:]

    # 预加载模板并准备门客对象
    rng = random.Random()
    template_ids = {candidate.template_id for candidate in to_process}
    template_map = _preload_templates(template_ids)

    guests_to_create, templates_for_guests, candidate_ids_to_delete = _prepare_guest_objects(
        to_process, template_map, manor, rng
    )

    # 批量写入数据库
    created_guests = []
    for guest_obj in guests_to_create:
        guest_obj.save()
        created_guests.append(guest_obj)

    # 批量创建招募记录
    records_to_create = []
    for i, guest in enumerate(created_guests):
        candidate = to_process[i]
        records_to_create.append(
            RecruitmentRecord(
                manor=manor,
                pool=candidate.pool,
                guest=guest,
                rarity=candidate.rarity,
            )
        )
    RecruitmentRecord.objects.bulk_create(records_to_create)

    # 批量授予技能（需要逐个处理因为技能可能不同）
    all_skills_to_create = []
    for guest, template in zip(created_guests, templates_for_guests):
        initial_skills = list(template.initial_skills.all())
        for skill in initial_skills[:MAX_GUEST_SKILL_SLOTS]:
            all_skills_to_create.append(
                GuestSkill(
                    guest=guest,
                    skill=skill,
                    source=GuestSkill.Source.TEMPLATE,
                )
            )
    if all_skills_to_create:
        GuestSkill.objects.bulk_create(all_skills_to_create)

    # 批量删除候选
    RecruitmentCandidate.objects.filter(id__in=candidate_ids_to_delete).delete()
    _invalidate_recruitment_hall_cache(getattr(manor, "id", None))

    return created_guests, failed


@transaction.atomic
def convert_candidate_to_retainer(candidate: RecruitmentCandidate) -> None:
    """
    将候选门客转为家丁。

    Args:
        candidate: 候选门客对象

    Raises:
        ValueError: 家丁房容量已满时抛出
    """
    candidate_id = getattr(candidate, "pk", None)
    manor_id = getattr(candidate, "manor_id", None)
    if not candidate_id or not manor_id:
        raise ValueError("候选门客不存在或已处理")

    from gameplay.models import Manor

    # 锁顺序统一为 Manor -> RecruitmentCandidate，避免与其他招募流程死锁
    manor = Manor.objects.select_for_update().get(pk=manor_id)
    locked_candidate = (
        RecruitmentCandidate.objects.select_for_update().filter(pk=candidate_id, manor_id=manor_id).first()
    )
    if locked_candidate is None:
        raise ValueError("候选门客不存在或已处理")

    capacity = manor.retainer_capacity
    if manor.retainer_count >= capacity:
        raise RetainerCapacityFullError()

    manor.retainer_count += 1
    manor.save(update_fields=["retainer_count"])
    locked_candidate.delete()
    _invalidate_recruitment_hall_cache(getattr(manor, "id", None))


def allocate_attribute_points(guest: Guest, attribute: str, points: int) -> Guest:
    """
    为门客分配属性点到指定属性。

    Args:
        guest: 门客对象
        attribute: 属性名称（force/intellect/defense/agility）
        points: 要分配的点数

    Returns:
        更新后的门客对象

    Raises:
        ValueError: 参数不合法时抛出
    """
    if not getattr(guest, "pk", None):
        raise ValueError("门客不存在")

    with transaction.atomic():
        locked_guest = Guest.objects.select_for_update().filter(pk=guest.pk).first()
        if not locked_guest:
            raise ValueError("门客不存在")
        if locked_guest.status != GuestStatus.IDLE:
            raise GuestNotIdleError(locked_guest)

        # 安全修复：验证点数范围
        if points <= 0:
            raise InvalidAllocationError("zero_points")
        if locked_guest.attribute_points < points:
            raise InvalidAllocationError("insufficient")

        # 属性字段映射
        attr_map = {
            "force": "force",
            "intellect": "intellect",
            "defense": "defense_stat",
            "agility": "agility",
        }
        # 已分配点数字段映射
        allocated_map = {
            "force": "allocated_force",
            "intellect": "allocated_intellect",
            "defense": "allocated_defense",
            "agility": "allocated_agility",
        }

        target = attr_map.get(attribute)
        allocated_field = allocated_map.get(attribute)
        if not target or not allocated_field:
            raise InvalidAllocationError("unknown_attribute")

        # 安全修复：检查属性上限，防止溢出
        MAX_ATTRIBUTE_VALUE = 9999  # 属性值安全上限
        current_value = getattr(locked_guest, target)
        if current_value + points > MAX_ATTRIBUTE_VALUE:
            raise InvalidAllocationError("attribute_overflow")

        locked_guest.attribute_points -= points
        updated_fields = ["attribute_points"]

        # 增加属性值
        setattr(locked_guest, target, getattr(locked_guest, target) + points)
        updated_fields.append(target)

        # 记录已分配点数
        setattr(locked_guest, allocated_field, getattr(locked_guest, allocated_field) + points)
        updated_fields.append(allocated_field)

        unique_fields = list(dict.fromkeys(updated_fields))
        locked_guest.save(update_fields=unique_fields)
    return locked_guest
