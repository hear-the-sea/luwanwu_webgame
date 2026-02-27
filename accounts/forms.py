from __future__ import annotations

from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from gameplay.constants import REGION_CHOICES, ManorNameConstants

from .models import User


class SignUpForm(UserCreationForm):
    email = forms.EmailField(label="邮箱", required=True)
    manor_name = forms.CharField(
        label="庄园名称",
        max_length=ManorNameConstants.MAX_LENGTH,
        required=True,
        help_text=(
            f"{ManorNameConstants.MIN_LENGTH}-{ManorNameConstants.MAX_LENGTH}个字符，" "仅支持中文、英文、数字和下划线"
        ),
    )
    region = forms.ChoiceField(
        label="选择地区", choices=REGION_CHOICES, initial="overseas", help_text="选择您庄园所在的地区"
    )

    class Meta(UserCreationForm.Meta):  # type: ignore[name-defined]
        model = User
        fields = ("username", "email", "manor_name", "region", "password1", "password2")

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update(
                {"class": "input", "placeholder": field.label},
            )

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("该邮箱已注册")
        return email

    def clean_manor_name(self):
        from gameplay.services.manor.core import is_manor_name_available, validate_manor_name

        name = (self.cleaned_data.get("manor_name") or "").strip()
        is_valid, error_msg = validate_manor_name(name)
        if not is_valid:
            raise forms.ValidationError(error_msg)
        if not is_manor_name_available(name):
            raise forms.ValidationError("该庄园名称已被使用")
        return name


class LoginForm(AuthenticationForm):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update(
                {"class": "input", "placeholder": field.label},
            )
