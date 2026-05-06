from __future__ import annotations

from pathlib import Path

from researchmate.services.paper_repo import PaperRepository


def test_paper_repo_upsert_list_and_update(tmp_path: Path) -> None:
    repo = PaperRepository(tmp_path / "papers.db")
    created = repo.upsert_paper(
        paper_id="paper_1",
        title="A Test Paper",
        authors=["Ada Lovelace", "Grace Hopper"],
        user_id="tester",
        tags=["rag"],
        year=2026,
    )

    assert created.id == "paper_1"
    assert created.authors == ["Ada Lovelace", "Grace Hopper"]

    listed = repo.list_papers(user_id="tester", tag="rag", year=2026, q="Test")
    assert [item.id for item in listed] == ["paper_1"]

    updated = repo.update_paper("paper_1", tags=["read"], rating=4.5)
    assert updated.tags == ["read"]
    assert updated.rating == 4.5
