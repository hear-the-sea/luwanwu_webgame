from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class RecruitViewResolutionError:
    message: str
    message_level: str = "error"
    status: int = 400


@dataclass(frozen=True)
class CandidateSelection:
    queryset: Any
    candidates: list[Any]
    candidate_ids: list[int] | None
    target_count: int


@dataclass(frozen=True)
class CandidateActionOutcome:
    action: str
    affected_count: int = 0
    succeeded: list[Any] = field(default_factory=list)
    failed: list[Any] = field(default_factory=list)
    error_message: str | None = None


def resolve_selected_candidate_selection(
    *,
    manor: Any,
    raw_candidate_ids: list[str],
    parse_positive_candidate_ids: Callable[[list[str]], list[int] | None],
    load_selected_candidates: Callable[..., tuple[Any, list[Any]]],
) -> tuple[CandidateSelection | None, RecruitViewResolutionError | None]:
    if not raw_candidate_ids:
        return None, RecruitViewResolutionError("请先勾选候选门客。", message_level="warning")

    candidate_ids = parse_positive_candidate_ids(raw_candidate_ids)
    if candidate_ids is None:
        return None, RecruitViewResolutionError("候选门客选择有误")

    queryset, candidates = load_selected_candidates(manor, candidate_ids)
    if not candidates:
        return None, RecruitViewResolutionError("未找到选中的候选门客。")

    return (
        CandidateSelection(
            queryset=queryset,
            candidates=candidates,
            candidate_ids=candidate_ids,
            target_count=len(candidates),
        ),
        None,
    )


def resolve_all_candidate_selection(
    *,
    manor: Any,
    action: str,
    candidate_model: Any,
) -> tuple[CandidateSelection | None, RecruitViewResolutionError | None]:
    queryset = candidate_model.objects.filter(manor=manor).order_by("id")
    if action == "discard":
        candidate_total = queryset.count()
        if candidate_total <= 0:
            return None, RecruitViewResolutionError("当前没有可操作的候选门客。")
        return (
            CandidateSelection(queryset=queryset, candidates=[], candidate_ids=None, target_count=candidate_total),
            None,
        )

    candidates = list(queryset)
    if not candidates:
        return None, RecruitViewResolutionError("当前没有可操作的候选门客。")

    return (
        CandidateSelection(queryset=queryset, candidates=candidates, candidate_ids=None, target_count=len(candidates)),
        None,
    )


def execute_candidate_action(
    *,
    action: str,
    selection: CandidateSelection,
    retain_candidates: Callable[[list[Any]], tuple[int, str | None]],
    finalize_candidates: Callable[[list[Any]], tuple[list[Any], list[Any]]],
) -> CandidateActionOutcome:
    if action == "discard":
        selection.queryset.delete()
        return CandidateActionOutcome(action=action, affected_count=selection.target_count)

    if action == "retain":
        retained, error_message = retain_candidates(selection.candidates)
        return CandidateActionOutcome(action=action, affected_count=retained, error_message=error_message)

    succeeded, failed = finalize_candidates(selection.candidates)
    return CandidateActionOutcome(action=action, succeeded=succeeded, failed=failed)


def reveal_candidate_rarities(
    *,
    manor: Any,
    item_id: int,
    use_magnifying_glass_for_candidates: Callable[[Any, int], int],
) -> int:
    return use_magnifying_glass_for_candidates(manor, item_id)
