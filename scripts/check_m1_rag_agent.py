from __future__ import annotations

import argparse
import asyncio
from typing import Any, cast

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from researchmate.agent import root_agent

APP_NAME = "researchmate"
USER_ID = "m1-user"
SESSION_ID = "m1-rag-session"
DEFAULT_PROMPT = (
    "Use the local knowledge base. What does the RAG basics paper say about "
    "grounded answers? Include source citations in the form [source: paper_id, p.N]."
)


async def _run_rag_agent(prompt: str) -> str:
    session_service = cast(Any, InMemorySessionService)()
    session = await session_service.create_session(
        app_name=APP_NAME,
        user_id=USER_ID,
        session_id=SESSION_ID,
    )
    runner = Runner(
        app_name=APP_NAME,
        agent=root_agent,
        session_service=session_service,
    )

    texts: list[str] = []
    async for event in runner.run_async(
        user_id=USER_ID,
        session_id=session.id,
        new_message=types.Content(
            role="user",
            parts=[types.Part(text=prompt)],
        ),
    ):
        content = event.content
        if not content or not content.parts:
            continue
        texts.extend((part.text or "").strip() for part in content.parts if part.text)

    return "\n".join(texts)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check the M1 RAG agent path.")
    parser.add_argument(
        "--prompt",
        default=DEFAULT_PROMPT,
        help="Prompt to send after you manually ingest local PDFs.",
    )
    parser.add_argument(
        "--expect-citation",
        help="Optional exact citation to require, for example '[source: paper_X, p.1]'.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    answer = asyncio.run(_run_rag_agent(str(args.prompt)))
    expected = str(args.expect_citation) if args.expect_citation else "[source:"
    if expected not in answer:
        raise SystemExit(
            "M1 RAG agent check failed: expected citation marker was not produced.\n"
            f"Expected: {expected}\n"
            f"Answer:\n{answer}"
        )
    print("M1 RAG agent check passed: expected citation marker was produced")


if __name__ == "__main__":
    main()
