from __future__ import annotations

import logging
import time
from threading import Lock

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView as DjangoLoginView
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views.generic import CreateView, TemplateView

from core.config import SECURITY
from core.utils.network import get_client_ip
from gameplay.models import Manor
from gameplay.services.manor.core import ManorNameConflictError

from .forms import LoginForm, SignUpForm
from .models import User

# 从 core.config 导入配置
LOGIN_ATTEMPT_LIMIT = SECURITY.LOGIN_ATTEMPT_LIMIT
LOGIN_ATTEMPT_WINDOW = SECURITY.LOGIN_ATTEMPT_WINDOW
LOGIN_LOCKOUT_DURATION = SECURITY.LOGIN_LOCKOUT_DURATION
logger = logging.getLogger(__name__)
_LOCAL_LOGIN_CACHE: dict[str, tuple[object, float]] = {}
_LOCAL_LOGIN_CACHE_GUARD = Lock()
_LOCAL_LOGIN_CACHE_MAX_SIZE = 5000


def _get_client_ip(request) -> str:
    """
    获取客户端真实 IP 地址。

    安全说明：
    - 优先使用 REMOTE_ADDR（不可伪造）
    - 仅当配置了可信代理时才使用 X-Forwarded-For
    - 防止攻击者通过伪造 HTTP 头绕过登录限制
    """
    return get_client_ip(request, trust_proxy=True)


def _get_login_attempt_key(request, username: str = None) -> tuple[str, str]:
    """
    获取登录尝试的缓存 key（基于 IP + 用户名双重限制）。

    Returns:
        (ip_key, username_key) - 两个缓存 key
    """
    ip = _get_client_ip(request)
    ip_key = f"login_attempts:ip:{ip}"
    username_key = f"login_attempts:user:{username}" if username else None
    return ip_key, username_key


def _get_login_lock_key(request, username: str = None) -> tuple[str, str]:
    """
    获取登录锁缓存 key（基于 IP + 用户名双重限制）。

    Returns:
        (ip_lock_key, username_lock_key)
    """
    ip = _get_client_ip(request)
    ip_lock_key = f"login_lock:ip:{ip}"
    username_lock_key = f"login_lock:user:{username}" if username else None
    return ip_lock_key, username_lock_key


def _cleanup_local_login_cache(now: float) -> None:
    expired_keys = [key for key, (_value, expire_at) in _LOCAL_LOGIN_CACHE.items() if expire_at <= now]
    for key in expired_keys[:1000]:
        _LOCAL_LOGIN_CACHE.pop(key, None)

    if len(_LOCAL_LOGIN_CACHE) <= _LOCAL_LOGIN_CACHE_MAX_SIZE:
        return

    for key, _value in sorted(_LOCAL_LOGIN_CACHE.items(), key=lambda item: item[1][1])[:500]:
        _LOCAL_LOGIN_CACHE.pop(key, None)


def _local_login_cache_get(key: str, default=None):
    now = time.monotonic()
    with _LOCAL_LOGIN_CACHE_GUARD:
        record = _LOCAL_LOGIN_CACHE.get(key)
        if record is None:
            return default
        value, expire_at = record
        if expire_at <= now:
            _LOCAL_LOGIN_CACHE.pop(key, None)
            return default
        return value


def _local_login_cache_set(key: str, value, timeout: int) -> None:
    expire_at = time.monotonic() + max(1, int(timeout))
    with _LOCAL_LOGIN_CACHE_GUARD:
        _LOCAL_LOGIN_CACHE[key] = (value, expire_at)
        if len(_LOCAL_LOGIN_CACHE) > _LOCAL_LOGIN_CACHE_MAX_SIZE:
            _cleanup_local_login_cache(time.monotonic())


def _local_login_cache_delete(key: str) -> None:
    with _LOCAL_LOGIN_CACHE_GUARD:
        _LOCAL_LOGIN_CACHE.pop(key, None)


def _local_login_cache_incr(key: str, timeout: int) -> int:
    now = time.monotonic()
    expire_at = now + max(1, int(timeout))
    with _LOCAL_LOGIN_CACHE_GUARD:
        record = _LOCAL_LOGIN_CACHE.get(key)
        if record is None or record[1] <= now:
            _LOCAL_LOGIN_CACHE[key] = (1, expire_at)
            return 1

        current_value, _current_expire_at = record
        try:
            next_value = int(current_value) + 1
        except (TypeError, ValueError):
            next_value = 1
        _LOCAL_LOGIN_CACHE[key] = (next_value, expire_at)
        return next_value


def _check_login_attempts(request, username: str = None) -> tuple[bool, int]:
    """
    检查登录尝试次数（IP + 用户名双重限制）

    Returns:
        (是否被锁定, 剩余锁定秒数)
    """
    ip_lock_key, username_lock_key = _get_login_lock_key(request, username)

    # 检查 IP 锁定
    if _safe_cache_get(ip_lock_key):
        ttl = _normalize_lock_ttl(ip_lock_key)
        return True, ttl

    # 检查用户名锁定（如果提供）
    if username_lock_key and _safe_cache_get(username_lock_key):
        ttl = _normalize_lock_ttl(username_lock_key)
        return True, ttl

    return False, 0


def _normalize_lock_ttl(lock_key: str) -> int:
    if not hasattr(cache, "ttl"):
        return LOGIN_LOCKOUT_DURATION
    try:
        ttl = cache.ttl(lock_key)
    except Exception:
        logger.warning("Failed to read lock TTL from cache: key=%s", lock_key, exc_info=True)
        return LOGIN_LOCKOUT_DURATION
    if ttl is None:
        return LOGIN_LOCKOUT_DURATION
    try:
        ttl_int = int(ttl)
    except (TypeError, ValueError):
        return LOGIN_LOCKOUT_DURATION
    if ttl_int < 0:
        return LOGIN_LOCKOUT_DURATION
    return ttl_int


def _increment_attempt_counter(key: str) -> int:
    added: bool | None = None
    try:
        added = bool(cache.add(key, 1, timeout=LOGIN_ATTEMPT_WINDOW))
    except Exception:
        logger.warning("Failed to add login attempts cache key: %s", key, exc_info=True)
        added = None

    if added is True:
        _local_login_cache_set(key, 1, timeout=LOGIN_ATTEMPT_WINDOW)
        return 1

    if added is False:
        try:
            attempts = int(cache.incr(key))
            _local_login_cache_set(key, attempts, timeout=LOGIN_ATTEMPT_WINDOW)
            return attempts
        except Exception:
            logger.warning(
                "Failed to increment login attempts cache key: key=%s degraded=True",
                key,
                exc_info=True,
            )
            if not settings.DEBUG:
                # 生产环境：缓存故障时 fail-closed，返回限制值触发锁定
                logger.warning(
                    "Login attempt counter cache unavailable: key=%s degraded=True fallback_mode=fail_closed",
                    key,
                    exc_info=False,
                )
                from core.utils.task_monitoring import increment_degraded_counter

                increment_degraded_counter("login_security_degraded")
                return LOGIN_ATTEMPT_LIMIT
            # DEBUG 模式：回落到本地计数，避免阻断开发调试
            logger.warning("Fallback to local login attempt counter path: key=%s", key)
            attempts = 1
            try:
                raw_attempts = _safe_cache_get(key, 0)
                attempts = int(raw_attempts or 0) + 1
            except (TypeError, ValueError):
                attempts = 1
            _safe_cache_set(key, attempts, timeout=LOGIN_ATTEMPT_WINDOW)
            return attempts

    # added is None：cache.add 本身抛异常
    logger.warning(
        "Login attempt counter cache unavailable: key=%s degraded=True fallback_mode=%s",
        key,
        "local" if settings.DEBUG else "fail_closed",
    )
    if not settings.DEBUG:
        # 生产环境：缓存故障时 fail-closed，返回限制值触发锁定
        from core.utils.task_monitoring import increment_degraded_counter

        increment_degraded_counter("login_security_degraded")
        return LOGIN_ATTEMPT_LIMIT

    # DEBUG 模式：回落到本地计数，避免阻断开发调试
    attempts = 1
    try:
        raw_attempts = _safe_cache_get(key, 0)
        attempts = int(raw_attempts or 0) + 1
    except (TypeError, ValueError):
        attempts = 1

    _safe_cache_set(key, attempts, timeout=LOGIN_ATTEMPT_WINDOW)
    return attempts


def _record_failed_attempt(request, username: str = None) -> int:
    """记录失败的登录尝试，返回当前尝试次数（取 IP 和用户名中较高者）"""
    ip_key, username_key = _get_login_attempt_key(request, username)
    ip_lock_key, username_lock_key = _get_login_lock_key(request, username)

    # 记录 IP 尝试（窗口计数）
    ip_attempts = _increment_attempt_counter(ip_key)
    if ip_attempts >= LOGIN_ATTEMPT_LIMIT:
        _safe_cache_set(ip_lock_key, 1, timeout=LOGIN_LOCKOUT_DURATION)

    # 记录用户名尝试（如果提供）
    user_attempts = 0
    if username_key:
        user_attempts = _increment_attempt_counter(username_key)
        if user_attempts >= LOGIN_ATTEMPT_LIMIT and username_lock_key:
            _safe_cache_set(username_lock_key, 1, timeout=LOGIN_LOCKOUT_DURATION)

    return max(ip_attempts, user_attempts)


def _clear_login_attempts(request, username: str = None, *, clear_ip: bool = True) -> None:
    """登录成功后清除尝试记录。"""
    ip_key, username_key = _get_login_attempt_key(request, username)
    ip_lock_key, username_lock_key = _get_login_lock_key(request, username)
    if clear_ip:
        _safe_cache_delete(ip_key)
        _safe_cache_delete(ip_lock_key)
    if username_key:
        _safe_cache_delete(username_key)
    if username_lock_key:
        _safe_cache_delete(username_lock_key)


_CACHE_MISS = object()


def _safe_cache_get(key: str, default=None):
    local_value = _local_login_cache_get(key, default)
    try:
        cached = cache.get(key, _CACHE_MISS)
    except Exception:
        logger.warning("Failed to read cache key: %s", key, exc_info=True)
        return local_value
    if cached is _CACHE_MISS:
        return local_value
    if cached is not None:
        _local_login_cache_set(key, cached, timeout=max(LOGIN_ATTEMPT_WINDOW, LOGIN_LOCKOUT_DURATION))
    return cached


def _safe_cache_set(key: str, value, timeout: int) -> None:
    _local_login_cache_set(key, value, timeout=timeout)
    try:
        cache.set(key, value, timeout=timeout)
    except Exception:
        logger.warning("Failed to write cache key: %s", key, exc_info=True)


def _safe_cache_delete(key: str) -> None:
    _local_login_cache_delete(key)
    try:
        cache.delete(key)
    except Exception:
        logger.warning("Failed to delete cache key: %s", key, exc_info=True)


class LoginView(DjangoLoginView):
    form_class = LoginForm
    template_name = "registration/login.html"

    def dispatch(self, request, *args, **kwargs):
        """检查是否被锁定"""
        username_hint = None
        if request.method == "POST":
            username_hint = (request.POST.get("username", "") or "").strip() or None
        is_locked, remaining = _check_login_attempts(request, username_hint)
        if is_locked:
            # 安全修复：使用模糊的提示信息，不泄露精确的锁定时间
            messages.error(request, "登录尝试次数过多，请稍后再试")
            return render(request, self.template_name, {"form": self.form_class()})
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        # 登录成功后清理用户名与 IP 维度失败记录，避免共享出口 IP 被持续误伤。
        username = form.cleaned_data.get("username", "")
        _clear_login_attempts(self.request, username, clear_ip=True)
        messages.success(self.request, "欢迎回来，领主大人！")
        return super().form_valid(form)

    def form_invalid(self, form):
        # 登录失败，记录尝试次数（基于 IP + 用户名双重限制）
        username = form.cleaned_data.get("username", "")
        attempts = _record_failed_attempt(self.request, username)
        remaining = LOGIN_ATTEMPT_LIMIT - attempts
        if remaining > 0:
            messages.warning(self.request, "用户名或密码错误，请重试")
        else:
            # 安全修复：使用模糊的提示信息
            messages.error(self.request, "登录尝试次数过多，请稍后再试")
        return super().form_invalid(form)


class RegisterView(CreateView):
    model = User
    form_class = SignUpForm
    template_name = "accounts/register.html"
    success_url = reverse_lazy("home")

    def form_valid(self, form):
        # 在保存用户前，将地区与庄园名附加到用户对象
        user = form.save(commit=False)
        user._signup_region = form.cleaned_data.get("region", "overseas")
        user._signup_manor_name = (form.cleaned_data.get("manor_name") or "").strip()
        try:
            # 在可能存在外层事务（如测试事务）时，使用 savepoint 隔离唯一约束冲突
            # 避免 IntegrityError 污染当前连接，导致后续模板渲染触发 TransactionManagementError。
            with transaction.atomic():
                user.save()
        except ManorNameConflictError:
            form.add_error("manor_name", "该庄园名称已被使用")
            return self.form_invalid(form)
        except IntegrityError:
            normalized_email = (form.cleaned_data.get("email") or "").strip().lower()
            username = (form.cleaned_data.get("username") or "").strip()
            manor_name = (form.cleaned_data.get("manor_name") or "").strip()
            if normalized_email and User.objects.filter(email__iexact=normalized_email).exists():
                form.add_error("email", "该邮箱已注册")
            elif username and User.objects.filter(username=username).exists():
                form.add_error("username", "该用户名已存在")
            elif manor_name and Manor.objects.filter(name__iexact=manor_name).exists():
                form.add_error("manor_name", "该庄园名称已被使用")
            else:
                form.add_error(None, "注册失败，请稍后重试")
            return self.form_invalid(form)
        self.object = user

        login(self.request, self.object)
        messages.success(self.request, "注册成功，已自动登录。")
        return redirect(self.success_url)


class ProfileView(LoginRequiredMixin, TemplateView):
    template_name = "accounts/profile.html"
