from __future__ import annotations

from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from gameplay.constants import REGION_CHOICES

from .models import User


class SignUpForm(UserCreationForm):
    email = forms.EmailField(label="邮箱", required=True)
    title = forms.CharField(label="身份/头衔", max_length=64, required=False)
    region = forms.ChoiceField(
        label="选择地区", choices=REGION_CHOICES, initial="overseas", help_text="选择您庄园所在的地区"
    )

    class Meta(UserCreationForm.Meta):  # type: ignore[name-defined]
        model = User
        fields = ("username", "email", "title", "region", "password1", "password2")

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update(
                {"class": "input", "placeholder": field.label},
            )

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("该邮箱已注册")
        return email


class LoginForm(AuthenticationForm):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update(
                {"class": "input", "placeholder": field.label},
            )
