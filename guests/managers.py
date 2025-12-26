"""
门客查询管理器

提供常用的门客查询方法，避免在视图和服务层重复 select_related/prefetch_related。

使用示例:
    # 替代: manor.guests.select_related("template").prefetch_related("skills")
    guests = Guest.objects.for_manor(manor).with_full_details()

    # 获取空闲门客
    idle_guests = Guest.objects.for_manor(manor).idle()

    # 获取可出战门客
    available = Guest.objects.for_manor(manor).available_for_battle()
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import models

if TYPE_CHECKING:
    from gameplay.models import Manor


class GuestQuerySet(models.QuerySet):
    """
    门客查询集，提供链式查询方法
    """

    def with_template(self) -> "GuestQuerySet":
        """
        预加载门客模板

        用于需要访问 template.name, template.rarity 等的场景
        """
        return self.select_related("template")

    def with_gear(self) -> "GuestQuerySet":
        """
        预加载装备及装备模板

        用于需要访问门客装备列表的场景
        """
        return self.prefetch_related("gear_items__template")

    def with_skills(self) -> "GuestQuerySet":
        """
        预加载技能

        用于需要访问门客技能列表的场景
        """
        return self.prefetch_related("guest_skills__skill")

    def with_full_details(self) -> "GuestQuerySet":
        """
        预加载所有相关数据

        用于门客详情页等需要完整信息的场景
        替代: select_related("template").prefetch_related("gear_items__template", "guest_skills__skill")
        """
        return self.select_related("template").prefetch_related(
            "gear_items__template",
            "guest_skills__skill",
        )

    def with_battle_details(self) -> "GuestQuerySet":
        """
        预加载战斗所需数据

        用于战斗模拟等需要门客属性和技能的场景
        """
        return self.select_related("template").prefetch_related("skills")

    def idle(self) -> "GuestQuerySet":
        """
        筛选空闲状态的门客
        """
        return self.filter(status="idle")

    def injured(self) -> "GuestQuerySet":
        """
        筛选重伤状态的门客
        """
        return self.filter(status="injured")

    def working(self) -> "GuestQuerySet":
        """
        筛选打工中的门客
        """
        return self.filter(status="working")

    def deployed(self) -> "GuestQuerySet":
        """
        筛选出征中的门客
        """
        return self.filter(status="deployed")

    def available_for_battle(self) -> "GuestQuerySet":
        """
        筛选可出战的门客（空闲状态）

        包含模板预加载，按稀有度和等级排序
        """
        return (
            self.filter(status="idle")
            .select_related("template")
            .order_by("-template__rarity", "-level")
        )

    def by_rarity(self, rarity: str) -> "GuestQuerySet":
        """
        按稀有度筛选
        """
        return self.filter(template__rarity=rarity)

    def ordered_by_power(self) -> "GuestQuerySet":
        """
        按战力排序（稀有度、等级）
        """
        return self.order_by("-template__rarity", "-level")

    def ordered_by_creation(self, desc: bool = True) -> "GuestQuerySet":
        """
        按创建时间排序
        """
        return self.order_by("-created_at" if desc else "created_at")


class GuestManager(models.Manager):
    """
    门客模型管理器

    提供便捷的查询方法，封装常用的 select_related/prefetch_related 组合
    """

    def get_queryset(self) -> GuestQuerySet:
        return GuestQuerySet(self.model, using=self._db)

    def for_manor(self, manor: "Manor") -> GuestQuerySet:
        """
        获取指定庄园的门客

        Args:
            manor: 庄园对象或庄园ID

        Returns:
            GuestQuerySet: 该庄园的门客查询集
        """
        manor_id = getattr(manor, "id", manor)
        return self.get_queryset().filter(manor_id=manor_id)

    def with_template(self) -> GuestQuerySet:
        """预加载门客模板"""
        return self.get_queryset().with_template()

    def with_full_details(self) -> GuestQuerySet:
        """预加载所有相关数据"""
        return self.get_queryset().with_full_details()

    def idle(self) -> GuestQuerySet:
        """筛选空闲门客"""
        return self.get_queryset().idle()

    def available_for_battle(self) -> GuestQuerySet:
        """筛选可出战门客"""
        return self.get_queryset().available_for_battle()
