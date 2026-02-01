from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView as DjangoLoginView
from django.core.cache import cache
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views.generic import CreateView, TemplateView

from .forms import LoginForm, SignUpForm
from .models import User
from .utils import purge_other_sessions

# 登录失败限制配置
LOGIN_ATTEMPT_LIMIT = 5  # 最大尝试次数
LOGIN_ATTEMPT_WINDOW = 300  # 时间窗口（秒）
LOGIN_LOCKOUT_DURATION = 900  # 锁定时长（秒）


def _get_login_attempt_key(request) -> str:
    """获取登录尝试的缓存 key（基于 IP）"""
    ip = request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip()
    if not ip:
        ip = request.META.get('REMOTE_ADDR', 'unknown')
    return f"login_attempts:{ip}"


def _check_login_attempts(request) -> tuple[bool, int]:
    """
    检查登录尝试次数

    Returns:
        (是否被锁定, 剩余锁定秒数)
    """
    key = _get_login_attempt_key(request)
    attempts = cache.get(key, 0)
    if attempts >= LOGIN_ATTEMPT_LIMIT:
        ttl = cache.ttl(key) if hasattr(cache, 'ttl') else LOGIN_LOCKOUT_DURATION
        return True, ttl
    return False, 0


def _record_failed_attempt(request) -> int:
    """记录失败的登录尝试，返回当前尝试次数"""
    key = _get_login_attempt_key(request)
    attempts = cache.get(key, 0) + 1
    cache.set(key, attempts, timeout=LOGIN_LOCKOUT_DURATION)
    return attempts


def _clear_login_attempts(request) -> None:
    """登录成功后清除尝试记录"""
    key = _get_login_attempt_key(request)
    cache.delete(key)


class LoginView(DjangoLoginView):
    form_class = LoginForm
    template_name = "registration/login.html"

    def dispatch(self, request, *args, **kwargs):
        """检查是否被锁定"""
        is_locked, remaining = _check_login_attempts(request)
        if is_locked:
            minutes = (remaining + 59) // 60  # 向上取整到分钟
            messages.error(request, f"登录尝试次数过多，请 {minutes} 分钟后再试")
            return render(request, self.template_name, {'form': self.form_class()})
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        # 登录成功，清除失败记录
        _clear_login_attempts(self.request)
        messages.success(self.request, "欢迎回来，指挥官。")
        response = super().form_valid(form)
        # 仅保留当前登录的 session，实现顶号
        self.request.session.save()
        purge_other_sessions(self.request.user.id, self.request.session.session_key)
        return response

    def form_invalid(self, form):
        # 登录失败，记录尝试次数
        attempts = _record_failed_attempt(self.request)
        remaining = LOGIN_ATTEMPT_LIMIT - attempts
        if remaining > 0:
            messages.warning(self.request, f"登录失败，还可尝试 {remaining} 次")
        else:
            messages.error(self.request, f"登录尝试次数过多，账号已被锁定 {LOGIN_LOCKOUT_DURATION // 60} 分钟")
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
