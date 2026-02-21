"""
模板加载工具 - 消除重复的模板加载模式

统一的模板加载函数，避免在多处重复 `{t.key: t for t in XxxTemplate.objects.all()}`
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, Iterable, TypeVar, cast

if TYPE_CHECKING:
    from django.db.models import Manager, Model, QuerySet


TModel = TypeVar("TModel", bound="Model")


def _get_model_manager(model_class: type[TModel]) -> "Manager[TModel]":
    manager = getattr(model_class, "objects", None)
    if manager is None:
        raise AttributeError(f"{model_class.__name__} has no objects manager")
    return cast("Manager[TModel]", manager)


def load_templates_by_key(
    model_class: type[TModel],
    keys: Iterable[str] | None = None,
    prefetch: list[str] | None = None,
    only_fields: list[str] | None = None,
) -> Dict[str, TModel]:
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
    qs: "QuerySet[TModel]" = _get_model_manager(model_class).all()

    if keys is not None:
        qs = qs.filter(key__in=keys)

    if prefetch:
        qs = qs.prefetch_related(*prefetch)

    if only_fields:
        qs = qs.only(*only_fields)

    templates: Dict[str, TModel] = {}
    for template in qs:
        template_key = str(getattr(template, "key", "") or "").strip()
        if template_key:
            templates[template_key] = template
    return templates


def load_templates_by_id(
    model_class: type[TModel],
    ids: Iterable[int],
    prefetch: list[str] | None = None,
) -> Dict[int, TModel]:
    """
    加载模板对象并以id为键构建字典

    Args:
        model_class: 模板模型类
        ids: 要加载的id列表
        prefetch: 需要预加载的关联字段

    Returns:
        {id: template_object} 字典
    """
    qs: "QuerySet[TModel]" = _get_model_manager(model_class).filter(id__in=ids)

    if prefetch:
        qs = qs.prefetch_related(*prefetch)

    templates: Dict[int, TModel] = {}
    for template in qs:
        template_id = getattr(template, "id", None)
        if template_id is None:
            continue
        templates[int(template_id)] = template
    return templates
