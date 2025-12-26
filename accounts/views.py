from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView as DjangoLoginView
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, TemplateView

from .forms import LoginForm, SignUpForm
from .models import User
from .utils import purge_other_sessions


class LoginView(DjangoLoginView):
    form_class = LoginForm
    template_name = "registration/login.html"

    def form_valid(self, form):
        messages.success(self.request, "欢迎回来，指挥官。")
        response = super().form_valid(form)
        # 仅保留当前登录的 session，实现顶号
        self.request.session.save()
        purge_other_sessions(self.request.user.id, self.request.session.session_key)
        return response


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
