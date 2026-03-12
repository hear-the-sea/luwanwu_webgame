import pytest

from gameplay.services.arena.exchange_helpers import (
    build_exchange_payload,
    build_exchange_summary,
    grant_exchange_items_locked,
    merge_item_grants,
    normalize_exchange_quantity,
    scale_reward_items,
    scale_reward_resources,
    send_exchange_success_message,
)


def test_normalize_exchange_quantity_validates_positive_values():
    assert normalize_exchange_quantity(3) == 3
    assert normalize_exchange_quantity("2") == 2

    with pytest.raises(ValueError, match="兑换数量无效"):
        normalize_exchange_quantity(0)


def test_scale_reward_resources_and_items():
    assert scale_reward_resources({"grain": 100, "silver": 50}, 2) == {"grain": 200, "silver": 100}
    assert scale_reward_items({"item_a": 1, "item_b": 3}, 2) == {"item_a": 2, "item_b": 6}


def test_merge_item_grants_accumulates_duplicate_keys():
    assert merge_item_grants({"item_a": 2}, {"item_a": 1, "item_b": 4}, {"item_b": 1}) == {
        "item_a": 3,
        "item_b": 5,
    }


def test_build_exchange_payload_and_summary_cover_all_sections():
    payload = build_exchange_payload(
        credited_resources={"grain": 100},
        overflow_resources={"silver": 50},
        granted_items={"item_a": 2},
    )
    summary = build_exchange_summary(
        credited_resources={"grain": 100},
        overflow_resources={"silver": 50},
        granted_items={"item_a": 2},
    )

    assert payload == {
        "resources": {"grain": 100},
        "resources_overflow": {"silver": 50},
        "items": {"item_a": 2},
    }
    assert summary == "资源已发放，道具已入库，部分资源因容量上限溢出"


def test_build_exchange_summary_returns_default_when_empty():
    assert build_exchange_summary(credited_resources={}, overflow_resources={}, granted_items={}) == "奖励已处理"


def test_grant_exchange_items_locked_merges_grants_and_calls_inventory_writer():
    calls = []

    granted = grant_exchange_items_locked(
        fixed_item_grants={"item_a": 2},
        random_item_grants={"item_a": 1, "item_b": 3},
        add_item_to_inventory_locked=lambda manor, item_key, amount: calls.append((manor, item_key, amount)),
        locked_manor="manor-1",
    )

    assert calls == [
        ("manor-1", "item_a", 2),
        ("manor-1", "item_a", 1),
        ("manor-1", "item_b", 3),
    ]
    assert granted == {"item_a": 3, "item_b": 3}


def test_send_exchange_success_message_swallows_message_errors(caplog):
    class _Reward:
        key = "grain_pack_small"
        name = "小粮包"

    class _Manor:
        id = 1

    with caplog.at_level("WARNING"):
        send_exchange_success_message(
            create_message_func=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("message backend down")),
            message_kind="reward",
            locked_manor=_Manor(),
            reward=_Reward(),
            total_cost=80,
            normalized_quantity=1,
            summary="资源已发放",
            logger=__import__("logging").getLogger("tests.arena.exchange"),
        )

    assert "arena exchange message failed" in caplog.text
