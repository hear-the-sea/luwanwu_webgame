from unittest.mock import Mock

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import IntegrityError
from django.test import RequestFactory
from django.urls import reverse

from accounts import views as account_views
from accounts.forms import SignUpForm

User = get_user_model()


@pytest.mark.django_db
def test_user_can_register(client):
    response = client.post(
        reverse("accounts:register"),
        {
            "username": "test-user",
            "email": "test@example.com",
            "title": "先锋官",
            "region": "overseas",
            "password1": "StrongPass123!",
            "password2": "StrongPass123!",
        },
    )
    assert response.status_code == 302
    assert User.objects.filter(username="test-user").exists()


@pytest.mark.django_db
def test_user_email_blank_is_normalized_to_null():
    user = User.objects.create_user(username="email_null_user", password="pass123")
    user.refresh_from_db()
    assert user.email is None


@pytest.mark.django_db
def test_user_email_unique_constraint_is_enforced():
    User.objects.create_user(username="email_unique_1", email="Dup@Example.com", password="pass123")
    with pytest.raises(IntegrityError):
        User.objects.create_user(username="email_unique_2", email="dup@example.com", password="pass123")


@pytest.mark.django_db
def test_signup_form_rejects_duplicate_email_case_insensitive():
    User.objects.create_user(username="email_form_exists", email="used@example.com", password="pass123")
    form = SignUpForm(
        data={
            "username": "email_form_new",
            "email": " USED@EXAMPLE.COM ",
            "title": "测试",
            "region": "overseas",
            "password1": "StrongPass123!",
            "password2": "StrongPass123!",
        }
    )
    assert form.is_valid() is False
    assert "email" in form.errors


@pytest.mark.django_db
def test_register_view_handles_integrity_error_duplicate_email_race(client, monkeypatch):
    User.objects.create_user(username="race_existing", email="race@example.com", password="pass123")

    monkeypatch.setattr("accounts.forms.SignUpForm.clean_email", lambda self: self.cleaned_data["email"])
    monkeypatch.setattr("accounts.forms.SignUpForm.validate_unique", lambda self: None)

    response = client.post(
        reverse("accounts:register"),
        {
            "username": "race_new_user",
            "email": "race@example.com",
            "title": "先锋官",
            "region": "overseas",
            "password1": "StrongPass123!",
            "password2": "StrongPass123!",
        },
    )
    assert response.status_code == 200
    assert User.objects.filter(username="race_new_user").exists() is False
    form = response.context["form"]
    assert "email" in form.errors
    assert any("该邮箱已注册" in msg for msg in form.errors["email"])


@pytest.mark.django_db
def test_register_view_handles_integrity_error_duplicate_username_race(client, monkeypatch):
    User.objects.create_user(username="race_same_name", email="race_name_old@example.com", password="pass123")

    monkeypatch.setattr("accounts.forms.SignUpForm.clean_email", lambda self: self.cleaned_data["email"])
    monkeypatch.setattr("accounts.forms.SignUpForm.clean_username", lambda self: self.cleaned_data["username"])
    monkeypatch.setattr("accounts.forms.SignUpForm.validate_unique", lambda self: None)

    response = client.post(
        reverse("accounts:register"),
        {
            "username": "race_same_name",
            "email": "race_name_new@example.com",
            "title": "先锋官",
            "region": "overseas",
            "password1": "StrongPass123!",
            "password2": "StrongPass123!",
        },
    )
    assert response.status_code == 200
    assert User.objects.filter(email="race_name_new@example.com").exists() is False
    form = response.context["form"]
    assert "username" in form.errors
    assert any("该用户名已存在" in msg for msg in form.errors["username"])


def _build_login_request(remote_addr: str = "127.0.0.1"):
    request = RequestFactory().post("/accounts/login/", data={"username": "u", "password": "x"})
    request.META["REMOTE_ADDR"] = remote_addr
    return request


@pytest.mark.django_db
def test_login_attempts_lock_after_limit(monkeypatch):
    cache.clear()
    monkeypatch.setattr(account_views, "LOGIN_ATTEMPT_LIMIT", 3)
    monkeypatch.setattr(account_views, "LOGIN_ATTEMPT_WINDOW", 60)
    monkeypatch.setattr(account_views, "LOGIN_LOCKOUT_DURATION", 120)

    request = _build_login_request()

    assert account_views._record_failed_attempt(request, "tester") == 1
    assert account_views._check_login_attempts(request, "tester")[0] is False
    assert account_views._record_failed_attempt(request, "tester") == 2
    assert account_views._check_login_attempts(request, "tester")[0] is False

    assert account_views._record_failed_attempt(request, "tester") == 3
    is_locked, _remaining = account_views._check_login_attempts(request, "tester")
    assert is_locked is True


@pytest.mark.django_db
def test_clear_login_attempts_removes_lock(monkeypatch):
    cache.clear()
    monkeypatch.setattr(account_views, "LOGIN_ATTEMPT_LIMIT", 2)
    monkeypatch.setattr(account_views, "LOGIN_ATTEMPT_WINDOW", 60)
    monkeypatch.setattr(account_views, "LOGIN_LOCKOUT_DURATION", 120)

    request = _build_login_request(remote_addr="10.0.0.2")
    account_views._record_failed_attempt(request, "tester2")
    account_views._record_failed_attempt(request, "tester2")
    assert account_views._check_login_attempts(request, "tester2")[0] is True

    account_views._clear_login_attempts(request, "tester2")
    assert account_views._check_login_attempts(request, "tester2")[0] is False


@pytest.mark.django_db
def test_check_login_attempts_respects_username_lock(monkeypatch):
    request = _build_login_request(remote_addr="10.0.0.8")
    _ip_lock_key, username_lock_key = account_views._get_login_lock_key(request, "locked_user")

    def fake_cache_get(key, default=None):
        if key == username_lock_key:
            return 1
        return default

    monkeypatch.setattr(account_views.cache, "get", fake_cache_get)
    monkeypatch.setattr(account_views.cache, "ttl", lambda _key: 60, raising=False)

    assert account_views._check_login_attempts(request, "locked_user")[0] is True


@pytest.mark.django_db
def test_check_login_attempts_fallback_ttl_when_cache_ttl_invalid(monkeypatch):
    request = _build_login_request(remote_addr="10.0.0.9")
    ip_lock_key, _username_lock_key = account_views._get_login_lock_key(request, "locked_user_2")

    def fake_cache_get(key, default=None):
        if key == ip_lock_key:
            return 1
        return default

    monkeypatch.setattr(account_views.cache, "get", fake_cache_get)
    monkeypatch.setattr(account_views.cache, "ttl", lambda _key: -1, raising=False)
    monkeypatch.setattr(account_views, "LOGIN_LOCKOUT_DURATION", 123)

    is_locked, ttl = account_views._check_login_attempts(request, "locked_user_2")
    assert is_locked is True
    assert ttl == 123


@pytest.mark.django_db
def test_increment_attempt_counter_fallback_resets_on_non_numeric_cache_value(monkeypatch):
    key = "login_attempts:test-corrupt"
    set_mock = Mock()

    monkeypatch.setattr(account_views.cache, "add", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        account_views.cache, "incr", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("no incr"))
    )
    monkeypatch.setattr(account_views.cache, "get", lambda *_args, **_kwargs: "not-a-number")
    monkeypatch.setattr(account_views.cache, "set", set_mock)

    attempts = account_views._increment_attempt_counter(key)
    assert attempts == 1
    set_mock.assert_called_once()
    assert set_mock.call_args[0][1] == 1


@pytest.mark.django_db
def test_increment_attempt_counter_fallback_tolerates_cache_read_write_errors(monkeypatch):
    key = "login_attempts:test-cache-error"

    monkeypatch.setattr(account_views.cache, "add", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        account_views.cache, "incr", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("no incr"))
    )
    monkeypatch.setattr(
        account_views.cache, "get", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("read fail"))
    )
    monkeypatch.setattr(
        account_views.cache, "set", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("write fail"))
    )

    attempts = account_views._increment_attempt_counter(key)
    assert attempts == 1


@pytest.mark.django_db
def test_check_login_attempts_fails_open_when_cache_get_errors(monkeypatch):
    request = _build_login_request(remote_addr="10.0.0.10")

    monkeypatch.setattr(
        account_views.cache,
        "get",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("cache down")),
    )

    is_locked, ttl = account_views._check_login_attempts(request, "tester")
    assert is_locked is False
    assert ttl == 0


@pytest.mark.django_db
def test_check_login_attempts_fallback_ttl_when_cache_ttl_errors(monkeypatch):
    request = _build_login_request(remote_addr="10.0.0.11")
    ip_lock_key, _username_lock_key = account_views._get_login_lock_key(request, "locked_user_3")

    def fake_cache_get(key, default=None):
        if key == ip_lock_key:
            return 1
        return default

    monkeypatch.setattr(account_views.cache, "get", fake_cache_get)
    monkeypatch.setattr(
        account_views.cache,
        "ttl",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("ttl fail")),
        raising=False,
    )
    monkeypatch.setattr(account_views, "LOGIN_LOCKOUT_DURATION", 321)

    is_locked, ttl = account_views._check_login_attempts(request, "locked_user_3")
    assert is_locked is True
    assert ttl == 321


@pytest.mark.django_db
def test_clear_login_attempts_tolerates_cache_delete_errors(monkeypatch):
    request = _build_login_request(remote_addr="10.0.0.12")
    delete_mock = Mock(side_effect=RuntimeError("delete fail"))
    monkeypatch.setattr(account_views.cache, "delete", delete_mock)

    account_views._clear_login_attempts(request, "tester")
    assert delete_mock.call_count >= 2
