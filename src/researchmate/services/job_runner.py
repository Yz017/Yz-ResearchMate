from __future__ import annotations

import asyncio
import json
import traceback
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import aiosqlite

JobState = Literal["queued", "running", "done", "failed", "interrupted", "cancelled"]
TERMINAL_STATES: frozenset[JobState] = frozenset({"done", "failed", "interrupted", "cancelled"})


@dataclass(frozen=True, slots=True)
class JobRecord:
    id: str
    kind: str
    state: JobState
    progress: float
    error: str | None
    params: dict[str, Any]
    result: dict[str, Any] | None
    user_id: str
    created_at: str
    finished_at: str | None

    def to_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "state": self.state,
            "progress": self.progress,
            "error": self.error,
            "params": self.params,
            "result": self.result,
            "user_id": self.user_id,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
        }


@dataclass(frozen=True, slots=True)
class JobEvent:
    event: str
    data: dict[str, Any]


@dataclass(slots=True)
class JobContext:
    runner: JobRunner
    job_id: str
    kind: str
    params: dict[str, Any]
    user_id: str

    async def progress(
        self,
        progress: float,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        await self.runner.update_progress(
            self.job_id,
            progress=progress,
            message=message,
            data=data,
        )


JobHandler = Callable[[JobContext], Awaitable[dict[str, Any] | None]]


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


def _decode_json_object(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    value = json.loads(raw)
    if isinstance(value, dict):
        return value
    return {"value": value}


def _job_from_row(row: aiosqlite.Row) -> JobRecord:
    return JobRecord(
        id=str(row["id"]),
        kind=str(row["kind"]),
        state=str(row["state"]),  # type: ignore[arg-type]
        progress=float(row["progress"]),
        error=str(row["error"]) if row["error"] else None,
        params=_decode_json_object(row["params_json"]),
        result=_decode_json_object(row["result_json"]) if row["result_json"] else None,
        user_id=str(row["user_id"]),
        created_at=str(row["created_at"]),
        finished_at=str(row["finished_at"]) if row["finished_at"] else None,
    )


class JobRunner:
    """Single-process asyncio job runner backed by SQLite state."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self._handlers: dict[str, JobHandler] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._subscribers: dict[str, set[asyncio.Queue[JobEvent]]] = {}
        self._ready = False
        self._ready_lock = asyncio.Lock()

    def register_handler(self, kind: str, handler: JobHandler) -> None:
        self._handlers[kind] = handler

    async def start(self) -> None:
        await self._ensure_ready()
        await self._mark_running_as_interrupted()

    async def close(self) -> None:
        for task in list(self._tasks.values()):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()

    async def submit(self, kind: str, params: dict[str, Any], user_id: str) -> str:
        await self._ensure_ready()
        if kind not in self._handlers:
            msg = f"unknown job kind: {kind}"
            raise ValueError(msg)
        job_id = str(uuid.uuid4())
        now = _utcnow_iso()
        async with self._connect() as db:
            await db.execute(
                """
                insert into jobs
                  (id, kind, state, progress, error, params_json, result_json,
                   user_id, created_at, finished_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    kind,
                    "queued",
                    0.0,
                    None,
                    json.dumps(params, ensure_ascii=False),
                    None,
                    user_id,
                    now,
                    None,
                ),
            )
            await db.commit()
        await self._emit(job_id, "queued", {"id": job_id, "state": "queued", "progress": 0.0})
        self._tasks[job_id] = asyncio.create_task(self._run(job_id), name=f"rm-job-{job_id}")
        return job_id

    async def cancel(self, job_id: str) -> bool:
        await self._ensure_ready()
        task = self._tasks.get(job_id)
        if task is not None:
            task.cancel()
            return True
        record = await self.get_job(job_id)
        if record is None or record.state in TERMINAL_STATES:
            return False
        await self._update_state(
            job_id,
            state="cancelled",
            progress=record.progress,
            error="cancelled before execution",
            result=None,
        )
        return True

    async def get_job(self, job_id: str) -> JobRecord | None:
        await self._ensure_ready()
        async with self._connect() as db:
            cursor = await db.execute("select * from jobs where id = ?", (job_id,))
            row = await cursor.fetchone()
        return _job_from_row(row) if row is not None else None

    async def update_progress(
        self,
        job_id: str,
        *,
        progress: float,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        safe_progress = min(max(float(progress), 0.0), 99.9)
        async with self._connect() as db:
            await db.execute(
                "update jobs set progress = ? where id = ?",
                (safe_progress, job_id),
            )
            await db.commit()
        await self._emit(
            job_id,
            "progress",
            {
                "id": job_id,
                "state": "running",
                "progress": safe_progress,
                "message": message,
                "data": data or {},
            },
        )

    async def subscribe(self, job_id: str) -> AsyncIterator[JobEvent]:
        record = await self.get_job(job_id)
        if record is None:
            msg = f"job not found: {job_id}"
            raise KeyError(msg)
        queue: asyncio.Queue[JobEvent] = asyncio.Queue()
        self._subscribers.setdefault(job_id, set()).add(queue)
        try:
            yield JobEvent("snapshot", record.to_payload())
            if record.state in TERMINAL_STATES:
                return
            while True:
                event = await queue.get()
                yield event
                state = event.data.get("state")
                if isinstance(state, str) and state in TERMINAL_STATES:
                    return
        finally:
            queues = self._subscribers.get(job_id)
            if queues is not None:
                queues.discard(queue)
                if not queues:
                    self._subscribers.pop(job_id, None)

    async def _run(self, job_id: str) -> None:
        try:
            record = await self.get_job(job_id)
            if record is None:
                return
            await self._update_state(job_id, state="running", progress=0.0)
            context = JobContext(
                runner=self,
                job_id=job_id,
                kind=record.kind,
                params=record.params,
                user_id=record.user_id,
            )
            handler = self._handlers[record.kind]
            result = await handler(context)
            await self._update_state(
                job_id,
                state="done",
                progress=100.0,
                result=result or {},
            )
        except asyncio.CancelledError:
            await self._update_state(
                job_id,
                state="cancelled",
                progress=0.0,
                error="cancelled",
                result=None,
            )
        except Exception:
            await self._update_state(
                job_id,
                state="failed",
                progress=0.0,
                error=traceback.format_exc(),
                result=None,
            )
        finally:
            self._tasks.pop(job_id, None)

    async def _update_state(
        self,
        job_id: str,
        *,
        state: JobState,
        progress: float,
        error: str | None = None,
        result: dict[str, Any] | None = None,
    ) -> None:
        finished_at = _utcnow_iso() if state in TERMINAL_STATES else None
        async with self._connect() as db:
            await db.execute(
                """
                update jobs
                set state = ?, progress = ?, error = ?, result_json = ?, finished_at = ?
                where id = ?
                """,
                (
                    state,
                    progress,
                    error,
                    json.dumps(result, ensure_ascii=False) if result is not None else None,
                    finished_at,
                    job_id,
                ),
            )
            await db.commit()
        await self._emit(
            job_id,
            state,
            {
                "id": job_id,
                "state": state,
                "progress": progress,
                "error": error,
                "result": result,
                "finished_at": finished_at,
            },
        )

    async def _emit(self, job_id: str, event: str, data: dict[str, Any]) -> None:
        for queue in list(self._subscribers.get(job_id, set())):
            queue.put_nowait(JobEvent(event=event, data=data))

    async def _mark_running_as_interrupted(self) -> None:
        async with self._connect() as db:
            await db.execute(
                """
                update jobs
                set state = 'interrupted',
                    error = 'service restarted before job completed',
                    finished_at = ?
                where state in ('queued', 'running')
                """,
                (_utcnow_iso(),),
            )
            await db.commit()

    async def _ensure_ready(self) -> None:
        if self._ready:
            return
        async with self._ready_lock:
            if self._ready:
                return
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            async with self._connect() as db:
                await db.execute(
                    """
                    create table if not exists jobs (
                        id text primary key,
                        kind text not null,
                        state text not null,
                        progress real not null,
                        error text,
                        params_json text not null,
                        result_json text,
                        user_id text not null,
                        created_at text not null,
                        finished_at text
                    )
                    """
                )
                await db.execute("create index if not exists idx_jobs_state on jobs(state)")
                await db.execute("create index if not exists idx_jobs_user on jobs(user_id)")
                await db.commit()
            self._ready = True

    @asynccontextmanager
    async def _connect(self) -> AsyncIterator[aiosqlite.Connection]:
        async with aiosqlite.connect(self.db_path) as connection:
            connection.row_factory = aiosqlite.Row
            yield connection
