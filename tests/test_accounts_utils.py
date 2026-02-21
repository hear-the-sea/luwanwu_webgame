from unittest.mock import Mock

from accounts import utils as account_utils


def test_purge_other_sessions_does_not_release_foreign_lock(monkeypatch):
    user_id = 123
    lock_key = f"{account_utils.USER_LOGIN_LOCK_PREFIX}{user_id}"
    cache_key = f"{account_utils.USER_SESSION_CACHE_PREFIX}{user_id}"
    delete_mock = Mock()
    token_holder: dict[str, str] = {}

    def fake_add(key, value, timeout=None):
        assert key == lock_key
        token_holder["token"] = value
        return True

    def fake_get(key, default=None):
        if key == cache_key:
            return None
        if key == lock_key:
            return "another-token"
        return default

    monkeypatch.setattr(account_utils.cache, "add", fake_add)
    monkeypatch.setattr(account_utils.cache, "get", fake_get)
    monkeypatch.setattr(account_utils.cache, "set", lambda *args, **kwargs: None)
    monkeypatch.setattr(account_utils.cache, "delete", delete_mock)

    account_utils.purge_other_sessions(user_id, "current-session")
    delete_mock.assert_not_called()


def test_purge_other_sessions_releases_owned_lock(monkeypatch):
    user_id = 456
    lock_key = f"{account_utils.USER_LOGIN_LOCK_PREFIX}{user_id}"
    cache_key = f"{account_utils.USER_SESSION_CACHE_PREFIX}{user_id}"
    delete_mock = Mock()
    token_holder: dict[str, str] = {}

    def fake_add(key, value, timeout=None):
        assert key == lock_key
        token_holder["token"] = value
        return True

    def fake_get(key, default=None):
        if key == cache_key:
            return None
        if key == lock_key:
            return token_holder["token"]
        return default

    monkeypatch.setattr(account_utils.cache, "add", fake_add)
    monkeypatch.setattr(account_utils.cache, "get", fake_get)
    monkeypatch.setattr(account_utils.cache, "set", lambda *args, **kwargs: None)
    monkeypatch.setattr(account_utils.cache, "delete", delete_mock)

    account_utils.purge_other_sessions(user_id, "current-session")
    delete_mock.assert_called_once_with(lock_key)


def test_purge_other_sessions_falls_back_when_lock_busy(monkeypatch):
    set_mock = Mock()
    fallback_mock = Mock()
    user_id = 777
    current_session_key = "current-session"
    cache_key = f"{account_utils.USER_SESSION_CACHE_PREFIX}{user_id}"

    monkeypatch.setattr(account_utils, "LOGIN_LOCK_MAX_WAIT_SECONDS", 0.0)
    monkeypatch.setattr(account_utils.cache, "add", lambda *args, **kwargs: False)
    monkeypatch.setattr(account_utils.cache, "set", set_mock)
    monkeypatch.setattr(account_utils, "_purge_sessions_fallback", fallback_mock)

    account_utils.purge_other_sessions(user_id, current_session_key)
    fallback_mock.assert_called_once_with(user_id, current_session_key)
    set_mock.assert_called_once_with(cache_key, current_session_key, timeout=account_utils.USER_SESSION_CACHE_TTL)


def test_session_key_prefix_handles_none():
    assert account_utils._session_key_prefix(None) == "<none>"


def test_session_key_prefix_truncates_value():
    assert account_utils._session_key_prefix("abcdefghi") == "abcdefgh"
