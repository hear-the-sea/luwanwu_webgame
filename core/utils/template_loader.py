"""
模板加载工具 - 消除重复的模板加载模式

统一的模板加载函数，避免在多处重复 `{t.key: t for t in XxxTemplate.objects.all()}`
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Iterable

if TYPE_CHECKING:
    from django.db.models import Model, QuerySet


def load_templates_by_key(
    model_class: type[Model],
    keys: Iterable[str] | None = None,
    prefetch: list[str] | None = None,
    only_fields: list[str] | None = None,
) -> Dict[str, Any]:
    """
    加载模板对象并以key为键构建字典

    Args:
        model_class: 模板模型类（如 ItemTemplate, GuestTemplate）
        keys: 要加载的key列表，None表示加载全部
        prefetch: 需要预加载的关联字段
        only_fields: 只加载指定字段（性能优化）

    Returns:
        {key: template_object} 字典
    """
    qs: QuerySet = model_class.objects.all()

    if keys is not None:
        qs = qs.filter(key__in=keys)

    if prefetch:
        qs = qs.prefetch_related(*prefetch)

    if only_fields:
        qs = qs.only(*only_fields)

    return {t.key: t for t in qs}


def load_templates_by_id(
    model_class: type[Model],
    ids: Iterable[int],
    prefetch: list[str] | None = None,
) -> Dict[int, Any]:
    """
    加载模板对象并以id为键构建字典

    Args:
        model_class: 模板模型类
        ids: 要加载的id列表
        prefetch: 需要预加载的关联字段

    Returns:
        {id: template_object} 字典
    """
    qs: QuerySet = model_class.objects.filter(id__in=ids)

    if prefetch:
        qs = qs.prefetch_related(*prefetch)

    return {t.id: t for t in qs}
