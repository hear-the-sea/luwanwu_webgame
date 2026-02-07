import pytest


@pytest.mark.django_db
def test_demo_ping_task_returns_pong():
    from tasks.demo import ping

    assert ping.run() == "pong"
