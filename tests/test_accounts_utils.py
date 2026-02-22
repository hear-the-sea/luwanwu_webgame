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


def test_acquire_login_lock_falls_back_to_local_when_cache_add_errors(monkeypatch):
    lock_key = "login_lock:local_fallback"
    token = "token-a"

    account_utils._LOCAL_LOGIN_LOCKS.clear()
    monkeypatch.setattr(
        account_utils.cache,
        "add",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("cache down")),
    )
    monkeypatch.setattr(account_utils, "LOGIN_LOCK_MAX_WAIT_SECONDS", 0.0)

    assert account_utils._acquire_login_lock(lock_key, token) is True
    assert account_utils._acquire_login_lock(lock_key, "token-b") is False

    account_utils._release_login_lock(lock_key, token)
    assert account_utils._acquire_login_lock(lock_key, "token-b") is True
    account_utils._release_login_lock(lock_key, "token-b")


def test_session_key_prefix_handles_none():
    assert account_utils._session_key_prefix(None) == "<none>"


def test_session_key_prefix_truncates_value():
    assert account_utils._session_key_prefix("abcdefghi") == "abcdefgh"


def test_purge_sessions_fallback_scans_beyond_1000_records(monkeypatch):
    class _FakeSession:
        def __init__(self, session_key: str, user_id: str):
            self.session_key = session_key
            self._user_id = user_id
            self.deleted = False

        def get_decoded(self):
            return {"_auth_user_id": self._user_id}

        def delete(self):
            self.deleted = True

    class _FakeQuerySet:
        def __init__(self, sessions):
            self._sessions = sessions

        def iterator(self, chunk_size=1000):
            return iter(self._sessions)

    class _FakeManager:
        def __init__(self, sessions):
            self._sessions = sessions

        def filter(self, **kwargs):
            return _FakeQuerySet(self._sessions)

    target_user = "42"
    current_session = "keep-current"
    sessions = [_FakeSession(f"other-{i}", "1") for i in range(1005)]
    far_session = _FakeSession("far-target", target_user)
    sessions.append(far_session)
    sessions.append(_FakeSession(current_session, target_user))

    fake_session_model = type("FakeSessionModel", (), {"objects": _FakeManager(sessions)})
    monkeypatch.setattr(account_utils, "Session", fake_session_model)

    account_utils._purge_sessions_fallback(int(target_user), current_session)

    assert far_session.deleted is True
