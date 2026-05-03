from __future__ import annotations

import asyncio
from typing import Any, cast

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from researchmate.agent import root_agent

APP_NAME = "researchmate"
USER_ID = "m0-user"
SESSION_ID = "m0-session"


async def _check_hello() -> bool:
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

    received_text = False
    async for event in runner.run_async(
        user_id=USER_ID,
        session_id=session.id,
        new_message=types.Content(
            role="user",
            parts=[types.Part(text="hello")],
        ),
    ):
        content = event.content
        if not content or not content.parts:
            continue
        if any((part.text or "").strip() for part in content.parts):
            received_text = True

    return received_text


def main() -> None:
    if not asyncio.run(_check_hello()):
        raise SystemExit("DeepSeek hello check failed: no text response received")
    print("DeepSeek hello check passed: text response received")


if __name__ == "__main__":
    main()
