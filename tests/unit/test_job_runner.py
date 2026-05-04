from __future__ import annotations

import asyncio
from pathlib import Path

from researchmate.services.job_runner import JobContext, JobRunner


async def test_job_runner_tracks_progress_and_result(tmp_path: Path) -> None:
    runner = JobRunner(tmp_path / "jobs.db")

    async def handler(context: JobContext) -> dict[str, object]:
        await asyncio.sleep(0.01)
        await context.progress(50.0, "halfway")
        return {"ok": True}

    runner.register_handler("unit", handler)
    await runner.start()
    try:
        job_id = await runner.submit("unit", {"value": 1}, "tester")
        events: list[str] = []
        async for event in runner.subscribe(job_id):
            events.append(event.event)
        record = await runner.get_job(job_id)
    finally:
        await runner.close()

    assert "progress" in events
    assert "done" in events
    assert record is not None
    assert record.state == "done"
    assert record.progress == 100.0
    assert record.result == {"ok": True}
