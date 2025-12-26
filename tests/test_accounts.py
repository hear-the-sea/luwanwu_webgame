import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse


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

