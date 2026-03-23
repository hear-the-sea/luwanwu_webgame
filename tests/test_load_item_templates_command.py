from __future__ import annotations

from pathlib import Path

import pytest

from gameplay.management.commands.load_item_templates import Command, _load_item_image
from gameplay.models import ItemTemplate


@pytest.mark.django_db
def test_load_item_image_oserror_is_best_effort(monkeypatch, tmp_path: Path):
    command = Command()
    template = ItemTemplate.objects.create(
        key="image_best_effort_item",
        name="测试物品",
        effect_type="none",
    )
    image_path = tmp_path / "item.png"
    image_path.write_bytes(b"fake")

    monkeypatch.setattr(
        "gameplay.management.commands.load_item_templates.compress_and_resize_image",
        lambda *_a, **_k: (_ for _ in ()).throw(OSError("image backend down")),
    )

    _load_item_image(command, template, {"image": "item.png"}, tmp_path)

    template.refresh_from_db()
    assert not template.image


@pytest.mark.django_db
def test_load_item_image_programming_error_bubbles_up(monkeypatch, tmp_path: Path):
    command = Command()
    template = ItemTemplate.objects.create(
        key="image_programming_error_item",
        name="测试物品",
        effect_type="none",
    )
    image_path = tmp_path / "item.png"
    image_path.write_bytes(b"fake")

    monkeypatch.setattr(
        "gameplay.management.commands.load_item_templates.compress_and_resize_image",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("broken image contract")),
    )

    with pytest.raises(AssertionError, match="broken image contract"):
        _load_item_image(command, template, {"image": "item.png"}, tmp_path)
