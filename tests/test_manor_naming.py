"""Tests for manor naming validation logic."""

from __future__ import annotations

from gameplay.services.manor.core import BANNED_WORDS, MANOR_NAME_MAX_LENGTH, MANOR_NAME_MIN_LENGTH, validate_manor_name


def test_validate_manor_name_rejects_empty():
    """Test that empty names are rejected."""
    valid, error = validate_manor_name("")
    assert valid is False
    assert "不能为空" in error

    valid, error = validate_manor_name("   ")
    assert valid is False
    assert "不能为空" in error


def test_validate_manor_name_rejects_too_short():
    """Test that names shorter than minimum are rejected."""
    valid, error = validate_manor_name("a")
    assert valid is False
    assert f"{MANOR_NAME_MIN_LENGTH}" in error


def test_validate_manor_name_rejects_too_long():
    """Test that names longer than maximum are rejected."""
    long_name = "a" * (MANOR_NAME_MAX_LENGTH + 1)
    valid, error = validate_manor_name(long_name)
    assert valid is False
    assert f"{MANOR_NAME_MAX_LENGTH}" in error


def test_validate_manor_name_accepts_valid_chinese():
    """Test that valid Chinese names are accepted."""
    valid, error = validate_manor_name("大明庄园")
    assert valid is True
    assert error == ""


def test_validate_manor_name_accepts_valid_english():
    """Test that valid English names are accepted."""
    valid, error = validate_manor_name("MyManor")
    assert valid is True
    assert error == ""


def test_validate_manor_name_accepts_mixed():
    """Test that mixed Chinese/English/numbers are accepted."""
    valid, error = validate_manor_name("庄园123")
    assert valid is True
    assert error == ""

    valid, error = validate_manor_name("Manor_01")
    assert valid is True
    assert error == ""


def test_validate_manor_name_rejects_special_characters():
    """Test that special characters are rejected."""
    invalid_names = [
        "庄园!",
        "Manor@123",
        "名字#",
        "test$name",
        "hello world",  # space
        "name<script>",
        "测试；",
    ]
    for name in invalid_names:
        valid, error = validate_manor_name(name)
        assert valid is False, f"Should reject: {name}"
        assert "仅支持" in error


def test_validate_manor_name_rejects_banned_words():
    """Test that banned words are rejected."""
    # Test with actual banned words if any exist
    if BANNED_WORDS:
        for word in list(BANNED_WORDS)[:3]:  # Test first 3
            valid, error = validate_manor_name(f"庄园{word}")
            assert valid is False, f"Should reject banned word: {word}"
            assert "敏感词" in error


def test_validate_manor_name_banned_words_case_insensitive():
    """Test that banned word check is case insensitive."""
    if BANNED_WORDS:
        # 找一个纯字母的敏感词进行测试
        alpha_words = [w for w in BANNED_WORDS if w.isalpha()]
        if alpha_words:
            word = alpha_words[0]
            # 构造一个不超过长度限制的测试名称
            test_name = word.upper()  # 例如: "ADMIN" 或 "GM"
            if len(test_name) < MANOR_NAME_MIN_LENGTH:
                test_name = test_name + "X" * (MANOR_NAME_MIN_LENGTH - len(test_name))
            valid, error = validate_manor_name(test_name)
            assert valid is False
            assert "敏感词" in error


def test_validate_manor_name_strips_whitespace():
    """Test that leading/trailing whitespace is handled."""
    valid, error = validate_manor_name("  有效名字  ")
    assert valid is True
    assert error == ""


def test_validate_manor_name_boundary_lengths():
    """Test names at exact boundary lengths."""
    # Exact minimum length
    min_name = "好" * MANOR_NAME_MIN_LENGTH
    valid, error = validate_manor_name(min_name)
    assert valid is True

    # Exact maximum length
    max_name = "好" * MANOR_NAME_MAX_LENGTH
    valid, error = validate_manor_name(max_name)
    assert valid is True
