from __future__ import annotations

import argparse
import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import NoReturn

import httpx

from researchmate.config import get_settings
from researchmate.services.oss_client import OssClient


def _parse_steps(value: str) -> list[int]:
    steps: list[int] = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        steps.append(int(item))
    return steps or [1, 2]


def _headers(token: str) -> dict[str, str]:
    return {"X-Internal-Token": token}


def _fail(message: str) -> NoReturn:
    raise RuntimeError(message)


def _check_response(response: httpx.Response) -> None:
    if response.status_code < 400:
        return
    try:
        payload = response.json()
    except ValueError:
        payload = {"message": response.text, "trace_id": response.headers.get("X-Trace-Id")}
    message = payload.get("message", response.text) if isinstance(payload, dict) else str(payload)
    trace_id = payload.get("trace_id") if isinstance(payload, dict) else None
    _fail(f"HTTP {response.status_code}: {message}" + (f" trace_id={trace_id}" if trace_id else ""))


def _iter_sse(response: httpx.Response) -> Iterator[tuple[str, dict[str, object]]]:
    event = "message"
    data_lines: list[str] = []
    for line in response.iter_lines():
        if not line:
            if data_lines:
                data = "\n".join(data_lines)
                try:
                    payload = json.loads(data)
                except json.JSONDecodeError:
                    payload = {"raw": data}
                yield event, payload
            event = "message"
            data_lines = []
            continue
        if line.startswith("event:"):
            event = line.removeprefix("event:").strip()
        elif line.startswith("data:"):
            data_lines.append(line.removeprefix("data:").strip())
    if data_lines:
        data = "\n".join(data_lines)
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            payload = {"raw": data}
        yield event, payload


def step_1_health(client: httpx.Client, *, deep: bool) -> None:
    for path in ("/v1/livez", "/v1/readyz"):
        response = client.get(path)
        _check_response(response)
        payload = response.json()
        if payload.get("status") not in {"ok", "degraded"}:
            _fail(f"{path} returned unexpected status: {payload}")
    if deep:
        response = client.get("/v1/healthz?deep=true")
        _check_response(response)
        payload = response.json()
        if "llm" not in payload:
            _fail("/v1/healthz?deep=true did not include llm status")
    print("[step 1] health ok")


def step_2_session_chat(client: httpx.Client, *, user_id: str) -> None:
    create_response = client.post("/v1/sessions", json={"user_id": user_id})
    _check_response(create_response)
    session_id = str(create_response.json()["session_id"])
    events: list[str] = []
    with client.stream(
        "POST",
        f"/v1/chat/{session_id}",
        json={"message": "请用一句话说明 ResearchMate 可以做什么。"},
        timeout=120.0,
    ) as response:
        _check_response(response)
        for event, payload in _iter_sse(response):
            events.append(event)
            if event == "error":
                _fail(f"chat stream returned error event: {payload}")
            if event == "final":
                full_text = payload.get("full_text")
                if not isinstance(full_text, str) or not full_text.strip():
                    _fail("final event did not include non-empty full_text")
                break
    if "thinking" not in events:
        _fail(f"chat stream missing thinking event: {events}")
    if "token" not in events:
        _fail(f"chat stream missing token event: {events}")
    if "final" not in events:
        _fail(f"chat stream missing final event: {events}")
    print("[step 2] session + chat ok")


def _wait_for_job(
    client: httpx.Client,
    job_id: str,
    *,
    status_path: str = "/v1/knowledge/jobs/{job_id}",
    timeout_seconds: float = 180.0,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout_seconds
    last_payload: dict[str, object] | None = None
    while time.monotonic() < deadline:
        response = client.get(status_path.format(job_id=job_id))
        _check_response(response)
        payload = response.json()
        if isinstance(payload, dict):
            last_payload = payload
            if payload.get("state") in {"done", "failed", "cancelled", "interrupted"}:
                return payload
        time.sleep(1.0)
    _fail(f"job {job_id} did not finish before timeout; last={last_payload}")


def step_3_ingest_chat(
    client: httpx.Client,
    *,
    user_id: str,
    sample_pdf: Path,
) -> None:
    if not sample_pdf.exists():
        _fail(f"sample PDF not found: {sample_pdf}")
    oss_key = OssClient.from_settings().put_file(sample_pdf)
    submit = client.post(
        "/v1/knowledge/ingest",
        json={
            "oss_keys": [oss_key],
            "owner_user_id": user_id,
            "tags": ["smoke"],
            "paper_id": "smoke_rag_basics",
            "title": "Smoke RAG Basics",
        },
        timeout=30.0,
    )
    _check_response(submit)
    job_id = str(submit.json()["job_id"])
    job = _wait_for_job(client, job_id)
    if job.get("state") != "done":
        _fail(f"ingest job failed: {job.get('error')}")

    create_response = client.post("/v1/sessions", json={"user_id": user_id})
    _check_response(create_response)
    session_id = str(create_response.json()["session_id"])
    final_text = ""
    citations = []
    with client.stream(
        "POST",
        f"/v1/chat/{session_id}",
        json={"message": "RAG basics 这份资料如何要求回答引用来源？"},
        timeout=120.0,
    ) as response:
        _check_response(response)
        for event, payload in _iter_sse(response):
            if event == "error":
                _fail(f"chat stream returned error event: {payload}")
            if event == "final":
                final_text = str(payload.get("full_text", ""))
                raw_citations = payload.get("citations", [])
                citations = raw_citations if isinstance(raw_citations, list) else []
                break
    if "smoke_rag_basics" not in final_text and not citations:
        _fail(f"RAG answer did not include smoke citation: {final_text}")
    print("[step 3] ingest + citation chat ok")


def step_4_memory_chat(client: httpx.Client, *, user_id: str) -> None:
    content = "我的研究方向是 M3 smoke 多模态对齐。"
    created = client.post(
        "/v1/memory",
        json={
            "user_id": user_id,
            "category": "research_direction",
            "content": content,
        },
    )
    _check_response(created)

    create_response = client.post("/v1/sessions", json={"user_id": user_id})
    _check_response(create_response)
    session_id = str(create_response.json()["session_id"])
    final_text = ""
    with client.stream(
        "POST",
        f"/v1/chat/{session_id}",
        json={"message": "请根据长期记忆回答：我的研究方向是什么？"},
        timeout=120.0,
    ) as response:
        _check_response(response)
        for event, payload in _iter_sse(response):
            if event == "error":
                _fail(f"chat stream returned error event: {payload}")
            if event == "final":
                final_text = str(payload.get("full_text", ""))
                break
    if "多模态" not in final_text and "对齐" not in final_text:
        _fail(f"memory answer did not reflect saved preference: {final_text}")
    print("[step 4] memory + new-session chat ok")


def step_5_weekly_report(
    client: httpx.Client,
    *,
    user_id: str,
    sample_pdf: Path,
) -> None:
    if not sample_pdf.exists():
        _fail(f"sample PDF not found: {sample_pdf}")
    oss_client = OssClient.from_settings()
    oss_key = oss_client.put_file(sample_pdf)
    submit = client.post(
        "/v1/knowledge/ingest",
        json={
            "oss_keys": [oss_key],
            "owner_user_id": user_id,
            "tags": ["smoke", "weekly"],
            "paper_id": "smoke_weekly_rag_basics",
            "title": "Smoke Weekly RAG Basics",
        },
        timeout=30.0,
    )
    _check_response(submit)
    ingest_job_id = str(submit.json()["job_id"])
    ingest_job = _wait_for_job(client, ingest_job_id)
    if ingest_job.get("state") != "done":
        _fail(f"weekly setup ingest failed: {ingest_job.get('error')}")

    task = client.post(
        "/v1/tasks/run",
        json={
            "kind": "weekly-report",
            "user_id": user_id,
            "params": {
                "week_start": "2026-04-20",
                "paper_count": 1,
                "focus_keywords": ["RAG"],
                "include_external": False,
            },
        },
        timeout=30.0,
    )
    _check_response(task)
    task_id = str(task.json()["task_id"])
    task_job = _wait_for_job(
        client,
        task_id,
        status_path="/v1/tasks/{job_id}",
        timeout_seconds=180.0,
    )
    if task_job.get("state") != "done":
        _fail(f"weekly_report task failed: {task_job.get('error')}")
    result = task_job.get("result")
    if not isinstance(result, dict):
        _fail(f"weekly_report result missing: {task_job}")
    artifact_key = result.get("artifact_oss_key")
    if not isinstance(artifact_key, str) or not artifact_key:
        _fail(f"weekly_report artifact key missing: {result}")
    settings = get_settings()
    local_report = oss_client.get_file(
        artifact_key,
        settings.oss_cache_dir / "smoke" / f"{task_id}.md",
    )
    markdown = local_report.read_text(encoding="utf-8")
    required = ["## TL;DR", "## Candidate Papers", "## Citations", "Authors:", "[source:"]
    missing = [item for item in required if item not in markdown]
    if missing:
        _fail(f"weekly report missing sections/content {missing}: {artifact_key}")
    print(f"[step 5] weekly_report ok artifact={artifact_key}")


def build_parser() -> argparse.ArgumentParser:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="ResearchMate milestone smoke tests.")
    parser.add_argument("--steps", default="1,2", help="Comma-separated steps, e.g. 1,2,3,4,5.")
    parser.add_argument(
        "--base-url",
        default=f"http://{settings.research_agent_bind}",
        help="ResearchMate service base URL.",
    )
    parser.add_argument(
        "--token",
        default=settings.research_agent_token.get_secret_value(),
        help="Internal service token.",
    )
    parser.add_argument("--user-id", default="smoke", help="User id for session tests.")
    parser.add_argument("--deep", action="store_true", help="Include deep LLM health probe.")
    parser.add_argument(
        "--sample-pdf",
        default="examples/pdfs/rag_basics.pdf",
        help="Sample PDF used by step 3.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    requested_steps = _parse_steps(str(args.steps))
    unsupported = [step for step in requested_steps if step not in {1, 2, 3, 4, 5}]
    if unsupported:
        _fail(f"steps {unsupported} are not implemented until later milestones")
    with httpx.Client(
        base_url=str(args.base_url).rstrip("/"),
        headers=_headers(str(args.token)),
        timeout=30.0,
    ) as client:
        if 1 in requested_steps:
            step_1_health(client, deep=bool(args.deep))
        if 2 in requested_steps:
            step_2_session_chat(client, user_id=str(args.user_id))
        if 3 in requested_steps:
            step_3_ingest_chat(
                client,
                user_id=str(args.user_id),
                sample_pdf=Path(str(args.sample_pdf)),
            )
        if 4 in requested_steps:
            step_4_memory_chat(client, user_id=str(args.user_id))
        if 5 in requested_steps:
            step_5_weekly_report(
                client,
                user_id=str(args.user_id),
                sample_pdf=Path(str(args.sample_pdf)),
            )


if __name__ == "__main__":
    main()
