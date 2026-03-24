import pytest
from django.core.management import call_command

from guests.models import RecruitmentPool


@pytest.fixture
def load_guest_data(db):
    if not RecruitmentPool.objects.exists():
        call_command("load_guest_templates", verbosity=0, skip_images=True)
