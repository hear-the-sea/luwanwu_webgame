from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView as DjangoLoginView
from django.core.cache import cache
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views.generic import CreateView, TemplateView

from core.utils.network import get_client_ip

from .forms import LoginForm, SignUpForm
from .models import User
from .utils import purge_other_sessions

# 登录失败限制配置
LOGIN_ATTEMPT_LIMIT = 5  # 最大尝试次数
LOGIN_ATTEMPT_WINDOW = 300  # 时间窗口（秒）
LOGIN_LOCKOUT_DURATION = 900  # 锁定时长（秒）


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


def _check_login_attempts(request, username: str = None) -> tuple[bool, int]:
    """
    检查登录尝试次数（IP + 用户名双重限制）

    Returns:
        (是否被锁定, 剩余锁定秒数)
    """
    ip_key, username_key = _get_login_attempt_key(request, username)

    # 检查 IP 限制
    ip_attempts = cache.get(ip_key, 0)
    if ip_attempts >= LOGIN_ATTEMPT_LIMIT:
        ttl = cache.ttl(ip_key) if hasattr(cache, 'ttl') else LOGIN_LOCKOUT_DURATION
        return True, ttl

    # 检查用户名限制（如果提供）
    if username_key:
        user_attempts = cache.get(username_key, 0)
        if user_attempts >= LOGIN_ATTEMPT_LIMIT:
            ttl = cache.ttl(username_key) if hasattr(cache, 'ttl') else LOGIN_LOCKOUT_DURATION
            return True, ttl

    return False, 0


def _record_failed_attempt(request, username: str = None) -> int:
    """记录失败的登录尝试，返回当前尝试次数（取 IP 和用户名中较高者）"""
    ip_key, username_key = _get_login_attempt_key(request, username)

    # 记录 IP 尝试
    ip_attempts = cache.get(ip_key, 0) + 1
    cache.set(ip_key, ip_attempts, timeout=LOGIN_LOCKOUT_DURATION)

    # 记录用户名尝试（如果提供）
    user_attempts = 0
    if username_key:
        user_attempts = cache.get(username_key, 0) + 1
        cache.set(username_key, user_attempts, timeout=LOGIN_LOCKOUT_DURATION)

    return max(ip_attempts, user_attempts)


def _clear_login_attempts(request, username: str = None) -> None:
    """登录成功后清除尝试记录"""
    ip_key, username_key = _get_login_attempt_key(request, username)
    cache.delete(ip_key)
    if username_key:
        cache.delete(username_key)


class LoginView(DjangoLoginView):
    form_class = LoginForm
    template_name = "registration/login.html"

    def dispatch(self, request, *args, **kwargs):
        """检查是否被锁定"""
        is_locked, remaining = _check_login_attempts(request)
        if is_locked:
            # 安全修复：使用模糊的提示信息，不泄露精确的锁定时间
            messages.error(request, "登录尝试次数过多，请稍后再试")
            return render(request, self.template_name, {'form': self.form_class()})
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        # 登录成功，清除失败记录（同时清除 IP 和用户名的记录）
        username = form.cleaned_data.get('username', '')
        _clear_login_attempts(self.request, username)
        messages.success(self.request, "欢迎回来，指挥官。")
        response = super().form_valid(form)
        # 仅保留当前登录的 session，实现顶号
        self.request.session.save()
        purge_other_sessions(self.request.user.id, self.request.session.session_key)
        return response

    def form_invalid(self, form):
        # 登录失败，记录尝试次数（基于 IP + 用户名双重限制）
        username = form.cleaned_data.get('username', '')
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
        # 在保存用户前，将地区信息附加到用户对象
        user = form.save(commit=False)
        user._signup_region = form.cleaned_data.get('region', 'overseas')
        user.save()
        self.object = user

        login(self.request, self.object)
        messages.success(self.request, "注册成功，已自动登录。")
        # 新注册后也保持单活跃 session
        self.request.session.save()
        purge_other_sessions(self.request.user.id, self.request.session.session_key)
        return redirect(self.success_url)


class ProfileView(LoginRequiredMixin, TemplateView):
    template_name = "accounts/profile.html"
