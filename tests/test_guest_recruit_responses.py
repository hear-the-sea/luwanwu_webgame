from __future__ import annotations

from types import SimpleNamespace

import pytest
from django.test import RequestFactory

from guests.views import recruit_responses


def test_format_duration_breaks_down_hours_minutes_and_seconds():
    assert recruit_responses.format_duration(0) == "0秒"
    assert recruit_responses.format_duration(61) == "1分钟1秒"
    assert recruit_responses.format_duration(3661) == "1小时1分钟1秒"


def test_format_bulk_recruit_success_message_truncates_preview():
    guests = [SimpleNamespace(display_name=f"门客{i}") for i in range(5)]

    assert recruit_responses.format_bulk_recruit_success_message(guests, preview_limit=2) == (
        "成功招募 5 名门客：门客0, 门客1 等 3 名"
    )


@pytest.mark.django_db
def test_build_recruitment_hall_ajax_payload_projects_before_render(monkeypatch):
    request = RequestFactory().get("/recruitment/")
    request.user = SimpleNamespace(id=42)
    manor = SimpleNamespace(id=7)
    calls: list[tuple[str, object]] = []

    def _fake_project(*_args, **_kwargs):
        calls.append(("project", manor))

    def _fake_context(*_args, **_kwargs):
        calls.append(("context", manor))
        return {"candidate_count": 3}

    def _fake_render(template_name, context, request=None):
        calls.append(("render", template_name))
        assert request is not None
        assert context["candidate_count"] == 3
        return f"rendered:{template_name}"

    monkeypatch.setattr("guests.views.recruit_responses.project_resource_production_for_read", _fake_project)
    monkeypatch.setattr("gameplay.selectors.recruitment.get_recruitment_hall_context", _fake_context)
    monkeypatch.setattr("django.template.loader.render_to_string", _fake_render)

    payload = recruit_responses.build_recruitment_hall_ajax_payload(request, manor, use_cache=False)

    assert payload == {
        "hall_pools_html": "rendered:gameplay/partials/recruitment_pools_section.html",
        "hall_candidates_html": "rendered:gameplay/partials/recruitment_candidates_section.html",
        "hall_records_html": "rendered:gameplay/partials/recruitment_records_section.html",
        "candidate_count": 3,
    }
    assert calls[0] == ("project", manor)
    assert calls[1] == ("context", manor)
