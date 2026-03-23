from __future__ import annotations

import random

import pytest

from common.utils.random_utils import weighted_random_choice


def test_weighted_random_choice_length_mismatch_raises_assertion() -> None:
    with pytest.raises(AssertionError, match="items 和 weights 长度必须一致"):
        weighted_random_choice(["a", "b"], [1.0], random.Random(1))


def test_weighted_random_choice_non_positive_total_raises_assertion() -> None:
    with pytest.raises(AssertionError, match="权重总和必须大于 0"):
        weighted_random_choice(["a", "b"], [0.0, 0.0], random.Random(1))
