from __future__ import annotations

from researchmate.services.task_kinds import validate_task_params


def test_weekly_report_params_accept_hyphen_kind() -> None:
    params = validate_task_params(
        "weekly-report",
        {
            "week_start": "2026-04-20",
            "paper_count": 3,
            "focus_keywords": ["RAG"],
        },
    )

    assert params["week_start"] == "2026-04-20"
    assert params["paper_count"] == 3
    assert params["focus_keywords"] == ["RAG"]
    assert params["include_external"] is False


def test_filter_papers_params_accept_defaults() -> None:
    params = validate_task_params("filter-papers", {"query": "RAG agent"})

    assert params["query"] == "RAG agent"
    assert params["candidate_paper_ids"] == []
    assert params["top_n"] == 50
    assert params["max_iter"] == 3
