"""
门客招募系统服务
"""

from __future__ import annotations

import random
from functools import lru_cache
from typing import TYPE_CHECKING, Dict, Iterable, List, Optional, Sequence, Tuple

from django.db import transaction

from core.exceptions import (
    GuestCapacityFullError,
    InvalidAllocationError,
    NoTemplateAvailableError,
    RetainerCapacityFullError,
)

if TYPE_CHECKING:
    from gameplay.models import Manor

from ..models import (
    DEFENSE_TO_HP_MULTIPLIER,
    MAX_GUEST_SKILL_SLOTS,
    MIN_HP_FLOOR,
    Guest,
    GuestRarity,
    GuestSkill,
    GuestTemplate,
    RecruitmentCandidate,
    RecruitmentPool,
    RecruitmentPoolEntry,
    RecruitmentRecord,
)
from ..utils.name_generator import generate_random_name
from ..utils.recruitment_utils import HERMIT_RARITY, RARITY_ORDER, choose_rarity, filter_entries, weighted_choice
from ..utils.recruitment_variance import apply_recruitment_variance

# 不可重复招募的稀有度（绿色及以上）
NON_REPEATABLE_RARITIES = frozenset({
    GuestRarity.GREEN,
    GuestRarity.BLUE,
    GuestRarity.RED,
    GuestRarity.PURPLE,
    GuestRarity.ORANGE,
})

CORE_POOL_TIERS = (
    RecruitmentPool.Tier.TONGSHI,
    RecruitmentPool.Tier.XIANGSHI,
    RecruitmentPool.Tier.HUISHI,
    RecruitmentPool.Tier.DIANSHI,
)


# ============ 模板缓存 ============

@lru_cache(maxsize=1)
def _get_recruitable_templates_by_rarity() -> Dict[str, List[GuestTemplate]]:
    """
    获取所有可招募模板，按稀有度分组缓存。

    使用 lru_cache 缓存结果，避免重复查询数据库。
    当模板数据变更时，需要调用 clear_template_cache() 刷新。

    Returns:
        按稀有度分组的模板字典
    """
    templates = list(GuestTemplate.objects.filter(recruitable=True))
    result: Dict[str, List[GuestTemplate]] = {}
    for template in templates:
        if template.rarity not in result:
            result[template.rarity] = []
        result[template.rarity].append(template)
    return result


@lru_cache(maxsize=1)
def _get_hermit_templates() -> List[GuestTemplate]:
    """
    获取所有可招募的隐士模板（缓存）。

    Returns:
        隐士模板列表
    """
    return list(GuestTemplate.objects.filter(
        rarity=GuestRarity.BLACK,
        is_hermit=True,
        recruitable=True,
    ))


def clear_template_cache() -> None:
    """
    清除模板缓存。

    当 GuestTemplate 数据变更时调用此函数刷新缓存。
    """
    _get_recruitable_templates_by_rarity.cache_clear()
    _get_hermit_templates.cache_clear()


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
    owned_templates = manor.guests.values_list(
        "template_id", "template__rarity", "template__is_hermit"
    )

    excluded = set()
    for template_id, rarity, is_hermit in owned_templates:
        # 绿色及以上稀有度排除
        if rarity in NON_REPEATABLE_RARITIES:
            excluded.add(template_id)
        # 黑色隐士也排除
        elif rarity == GuestRarity.BLACK and is_hermit:
            excluded.add(template_id)

    return excluded


def list_pools(core_only: bool = False) -> Iterable[RecruitmentPool]:
    """列出所有招募卡池"""
    qs = RecruitmentPool.objects.prefetch_related("entries__template").order_by("tier", "id")
    if core_only:
        qs = qs.filter(tier__in=CORE_POOL_TIERS)
    return qs


def available_guests(manor: Manor) -> Sequence[Guest]:
    """获取庄园所有可用门客"""
    return (
        manor.guests.select_related("template")
        .prefetch_related("gear_items__template")
        .order_by("-template__rarity", "-level")
    )


def list_candidates(manor: Manor) -> Iterable[RecruitmentCandidate]:
    """列出庄园的招募候选门客"""
    return manor.candidates.select_related("pool", "template").order_by("created_at")


def choose_template_from_entries(
    entries: List[RecruitmentPoolEntry],
    rng: random.Random,
    excluded_ids: set[int] | None = None,
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
        hermit_templates = _filter_templates(_get_hermit_templates(), excluded_ids)
        if hermit_templates:
            return rng.choice(hermit_templates)
        # 无可用隐士，降级为普通黑色
        rarity = GuestRarity.BLACK

    # 如果没有配置 entries，直接从缓存的模板中选择
    if not entries:
        return _choose_template_by_rarity_cached(rarity, excluded_ids, rng)

    # 有 entries 配置时，使用原有逻辑（但使用缓存的模板数据）
    filtered_entries = [
        e for e in entries
        if not e.template_id or e.template_id not in excluded_ids
    ]

    explicit_template_ids = {entry.template_id for entry in filtered_entries if entry.template_id}
    # 获取缓存的模板数据
    templates_by_rarity = _get_recruitable_templates_by_rarity()
    category_cache: Dict[Tuple[str | None, str | None], List[GuestTemplate]] = {}

    def resolve_entry(entry: RecruitmentPoolEntry, rarity_hint: str) -> GuestTemplate | None:
        if entry.template_id:
            return entry.template if entry.template.recruitable else None
        rarity_value = entry.rarity or rarity_hint
        if not rarity_value:
            return None
        archetype_key = entry.archetype or None
        cache_key = (rarity_value, archetype_key)
        if cache_key not in category_cache:
            # 使用缓存的模板数据进行过滤
            base_templates = templates_by_rarity.get(rarity_value, [])
            if archetype_key:
                base_templates = [t for t in base_templates if t.archetype == archetype_key]
            # 排除已拥有的模板和显式指定的模板
            all_excluded = explicit_template_ids | excluded_ids
            templates = _filter_templates(base_templates, all_excluded)
            category_cache[cache_key] = templates
        templates = category_cache[cache_key]
        if not templates:
            return None
        return rng.choice(templates)

    search_order = [rarity]
    if rarity in RARITY_ORDER:
        idx = RARITY_ORDER.index(rarity)
        search_order.extend(RARITY_ORDER[idx + 1 :] + RARITY_ORDER[:idx])
    else:
        search_order.extend(RARITY_ORDER)

    for rarity_option in search_order:
        options = filter_entries(filtered_entries, rarity_option)
        if not options:
            continue
        chosen_entry = weighted_choice(options, rng)
        template = resolve_entry(chosen_entry, rarity_option)
        if template:
            return template

    # 全局回退（使用缓存版本）
    return _choose_template_by_rarity_cached(rarity, excluded_ids, rng)


def _choose_template_by_rarity_cached(
    rarity: str,
    excluded_ids: set[int],
    rng: random.Random,
) -> GuestTemplate:
    """
    按稀有度从缓存的模板中随机选择。

    使用预加载的模板缓存，避免数据库查询。
    如果目标稀有度无可用模板，会尝试降级到其他稀有度。
    """
    templates_by_rarity = _get_recruitable_templates_by_rarity()

    # 构建搜索顺序：目标稀有度优先，然后按顺序尝试其他稀有度
    search_order = [rarity]
    if rarity in RARITY_ORDER:
        idx = RARITY_ORDER.index(rarity)
        search_order.extend(RARITY_ORDER[idx + 1 :] + RARITY_ORDER[:idx])
    else:
        search_order.extend(RARITY_ORDER)

    for rarity_option in search_order:
        templates = templates_by_rarity.get(rarity_option, [])
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
    search_order = [rarity]
    if rarity in RARITY_ORDER:
        idx = RARITY_ORDER.index(rarity)
        search_order.extend(RARITY_ORDER[idx + 1 :] + RARITY_ORDER[:idx])
    else:
        search_order.extend(RARITY_ORDER)

    for rarity_option in search_order:
        qs = GuestTemplate.objects.filter(rarity=rarity_option, recruitable=True)
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
    return count


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

    # 资源扣除成功后再清空候选门客（防止玩家绕过前端确认）
    manor.candidates.all().delete()
    pool_entries = list(pool.entries.select_related("template"))
    rng = random.Random(seed)
    candidates_to_create: List[RecruitmentCandidate] = []

    # 计算抽取数量：卡池基础数量 + 酒馆加成
    tavern_bonus = manor.tavern_recruitment_bonus
    total_draw_count = pool.draw_count + tavern_bonus

    # 获取玩家已拥有的需要排除的模板（绿色以上 + 黑色隐士）
    excluded_ids = get_excluded_template_ids(manor)

    for _ in range(total_draw_count):
        template = choose_template_from_entries(pool_entries, rng=rng, excluded_ids=excluded_ids)
        template_to_use = template
        display_name = template.name
        if template.rarity in (GuestRarity.BLACK, GuestRarity.GRAY):
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
        if template.rarity in NON_REPEATABLE_RARITIES or (
            template.rarity == GuestRarity.BLACK and template.is_hermit
        ):
            excluded_ids.add(template.id)

    # 批量创建候选门客
    candidates = RecruitmentCandidate.objects.bulk_create(candidates_to_create)
    return candidates


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
    guest = create_guest_from_template(
        manor=manor,
        template=template,
        rarity=candidate.rarity,
        archetype=candidate.archetype,
        custom_name=candidate.display_name if candidate.rarity in (GuestRarity.BLACK, GuestRarity.GRAY) else "",
        rng=rng,
    )
    RecruitmentRecord.objects.create(
        manor=manor,
        pool=candidate.pool,
        guest=guest,
        rarity=candidate.rarity,
    )
    candidate.delete()
    return guest


@transaction.atomic
def bulk_finalize_candidates(
    candidates: List[RecruitmentCandidate],
) -> Tuple[List[Guest], List[RecruitmentCandidate]]:
    """
    批量确认招募候选门客，将其转为正式门客。

    在单个事务中处理多个候选，减少数据库往返次数。
    会在开始时一���性检查容量，避免重复查询。

    Args:
        candidates: 候选门客对象列表

    Returns:
        (成功招募的门客列表, 因容量不足而失败的候选列表)
    """
    if not candidates:
        return [], []

    from gameplay.models import Manor

    # 使用 select_for_update 锁定庄园，防止并发超出容量
    manor = Manor.objects.select_for_update().get(pk=candidates[0].manor_id)
    capacity = manor.guest_capacity
    current_count = manor.guests.count()
    available_slots = capacity - current_count

    if available_slots <= 0:
        return [], candidates

    # 按可用槽位数量处理候选
    to_process = candidates[:available_slots]
    failed = candidates[available_slots:]

    rng = random.Random()
    template_ids = {candidate.template_id for candidate in to_process}
    template_map = {
        template.id: template
        for template in GuestTemplate.objects.filter(id__in=template_ids).prefetch_related("initial_skills")
    }
    guests_to_create: List[Guest] = []
    records_to_create: List[RecruitmentRecord] = []
    templates_for_guests: List[GuestTemplate] = []
    candidate_ids_to_delete: List[int] = []

    for candidate in to_process:
        template = template_map.get(candidate.template_id) or candidate.template
        guest = create_guest_from_template(
            manor=manor,
            template=template,
            rarity=candidate.rarity,
            archetype=candidate.archetype,
            custom_name=candidate.display_name if candidate.rarity in (GuestRarity.BLACK, GuestRarity.GRAY) else "",
            rng=rng,
            grant_skills=False,
            save=False,
        )
        guests_to_create.append(guest)
        templates_for_guests.append(template)
        candidate_ids_to_delete.append(candidate.id)

    # 批量创建门客
    # 注意：MySQL 不支持 bulk_create 返回主键（不支持 RETURNING 子句）
    # 为了确保后续创建关联对象时有正确的外键，直接逐个创建
    created_guests = []
    for guest_obj in guests_to_create:
        guest_obj.save()
        created_guests.append(guest_obj)

    # 批量创建招募记录
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
    manor = candidate.manor
    capacity = manor.retainer_capacity
    if manor.retainer_count >= capacity:
        raise RetainerCapacityFullError()

    manor.retainer_count += 1
    manor.save(update_fields=["retainer_count"])
    candidate.delete()


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
    # 安全修复：验证点数范围
    if points <= 0:
        raise InvalidAllocationError("zero_points")
    if guest.attribute_points < points:
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
    current_value = getattr(guest, target)
    if current_value + points > MAX_ATTRIBUTE_VALUE:
        raise InvalidAllocationError("attribute_overflow")

    guest.attribute_points -= points
    updated_fields = ["attribute_points"]

    # 增加属性值
    setattr(guest, target, getattr(guest, target) + points)
    updated_fields.append(target)

    # 记录已分配点数
    setattr(guest, allocated_field, getattr(guest, allocated_field) + points)
    updated_fields.append(allocated_field)

    unique_fields = list(dict.fromkeys(updated_fields))
    guest.save(update_fields=unique_fields)
    return guest
