from __future__ import annotations

import argparse
import json
from collections.abc import Iterator

import httpx

from researchmate.config import get_settings


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


def _fail(message: str) -> None:
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


def build_parser() -> argparse.ArgumentParser:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="ResearchMate milestone smoke tests.")
    parser.add_argument("--steps", default="1,2", help="Comma-separated steps, e.g. 1,2.")
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
    return parser


def main() -> None:
    args = build_parser().parse_args()
    requested_steps = _parse_steps(str(args.steps))
    unsupported = [step for step in requested_steps if step not in {1, 2}]
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


if __name__ == "__main__":
    main()
