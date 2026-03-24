from __future__ import annotations

import pytest
from django.http import HttpResponse
from django.test import RequestFactory, override_settings

from battle_debugger.config import BattleConfig, ConfigLoader, InvalidPresetError, PartyConfig
from battle_debugger.views import custom_config, simulate, tune


def _make_staff_post_request(django_user_model, path: str, data: dict):
    user = django_user_model.objects.create_user(
        username=f"debugger-{path.replace('/', '-')}",
        password="pass",
        is_staff=True,
    )
    request = RequestFactory().post(path, data)
    request.user = user
    return request


def _valid_config() -> BattleConfig:
    return BattleConfig(
        name="test",
        attacker=PartyConfig(troops={"attacker_troop": 1}),
        defender=PartyConfig(troops={"defender_troop": 1}),
    )


@override_settings(DEBUG=True)
def test_load_preset_invalid_name_raises_explicit_error():
    loader = ConfigLoader()

    with pytest.raises(InvalidPresetError, match="预设名称无效"):
        loader.load_preset("../bad")


@pytest.mark.django_db
@override_settings(DEBUG=True)
def test_simulate_renders_error_for_invalid_preset_name(django_user_model, monkeypatch):
    request = _make_staff_post_request(
        django_user_model,
        "/debugger/simulate/",
        {"preset": "../bad", "repeat": "1"},
    )

    def _broken_load_preset(_self, _preset_name):
        raise InvalidPresetError("预设名称无效: '../bad'")

    monkeypatch.setattr("battle_debugger.views.ConfigLoader.load_preset", _broken_load_preset)
    monkeypatch.setattr("battle_debugger.views._render_debugger_error", lambda _request, message: HttpResponse(message))

    response = simulate(request)

    assert response.status_code == 200
    assert "预设名称无效".encode("utf-8") in response.content


@pytest.mark.django_db
@override_settings(DEBUG=True)
def test_simulate_bubbles_programming_errors(django_user_model, monkeypatch):
    request = _make_staff_post_request(
        django_user_model,
        "/debugger/simulate/",
        {"preset": "valid", "repeat": "1"},
    )

    monkeypatch.setattr("battle_debugger.views.ConfigLoader.load_preset", lambda _self, _preset_name: _valid_config())

    class BrokenSimulator:
        def __init__(self, _config):
            pass

        def run_battle(self, seed=None):
            raise AssertionError("broken battle debugger simulate contract")

    monkeypatch.setattr("battle_debugger.views.BattleSimulator", BrokenSimulator)

    with pytest.raises(AssertionError, match="broken battle debugger simulate contract"):
        simulate(request)


@pytest.mark.django_db
@override_settings(DEBUG=True)
def test_tune_bubbles_programming_errors(django_user_model, monkeypatch):
    request = _make_staff_post_request(
        django_user_model,
        "/debugger/tune/",
        {
            "preset": "valid",
            "param": "slaughter_multiplier",
            "values": "10,20",
            "repeat": "1",
        },
    )

    monkeypatch.setattr("battle_debugger.views.ConfigLoader.load_preset", lambda _self, _preset_name: _valid_config())

    class BrokenSimulator:
        def __init__(self, _config):
            pass

        def run_battle(self, seed=None):
            raise AssertionError("broken battle debugger tune contract")

    monkeypatch.setattr("battle_debugger.views.BattleSimulator", BrokenSimulator)

    with pytest.raises(AssertionError, match="broken battle debugger tune contract"):
        tune(request)


@pytest.mark.django_db
@override_settings(DEBUG=True)
def test_custom_config_bubbles_programming_errors(django_user_model, monkeypatch):
    request = _make_staff_post_request(
        django_user_model,
        "/debugger/custom/",
        {
            "attacker_guest_count": "0",
            "defender_guest_count": "0",
            "attacker_troop_types": ["infantry"],
            "attacker_troop_infantry": "5",
            "defender_troop_types": ["infantry"],
            "defender_troop_infantry": "5",
            "repeat": "1",
        },
    )

    class BrokenSimulator:
        def __init__(self, _config):
            pass

        def run_battle(self, seed=None):
            raise AssertionError("broken battle debugger custom config contract")

    monkeypatch.setattr("battle_debugger.views.BattleSimulator", BrokenSimulator)

    with pytest.raises(AssertionError, match="broken battle debugger custom config contract"):
        custom_config(request)


@pytest.mark.django_db
@override_settings(DEBUG=True)
def test_custom_config_renders_error_for_empty_sides(django_user_model, monkeypatch):
    request = _make_staff_post_request(
        django_user_model,
        "/debugger/custom/",
        {
            "attacker_guest_count": "0",
            "defender_guest_count": "0",
            "repeat": "1",
        },
    )

    monkeypatch.setattr("battle_debugger.views._render_debugger_error", lambda _request, message: HttpResponse(message))
    response = custom_config(request)

    assert response.status_code == 200
    assert "攻方必须至少有门客或小兵".encode("utf-8") in response.content
