from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from researchmate.agents.llm_policy import (
    FallbackLiteLlm,
    classify_llm_error,
    truncate_request_history,
)


def _content(text: str) -> types.Content:
    return types.Content(role="user", parts=[types.Part.from_text(text=text)])


def _first_text(content: types.Content) -> str:
    assert content.parts is not None
    assert content.parts[0].text is not None
    return content.parts[0].text


def test_truncate_request_history_keeps_recent_messages() -> None:
    llm_request = LlmRequest(
        contents=[
            _content("first message with a lot of words"),
            _content("second message with a lot of words"),
            _content("third message with a lot of words"),
        ]
    )

    policy = truncate_request_history(llm_request, soft_limit=20, keep_recent=2)

    assert policy["removed_messages"] >= 1
    assert len(llm_request.contents) == 2
    assert "second" in _first_text(llm_request.contents[0])
    assert "third" in _first_text(llm_request.contents[1])


def test_classify_llm_error_uses_retryable_status_code() -> None:
    class _RateLimitedError(Exception):
        status_code = 429

    code, message, retryable = classify_llm_error(_RateLimitedError("too fast"))

    assert code == "LLM_RATE_LIMITED"
    assert "too fast" in message
    assert retryable is True


@pytest.mark.asyncio
async def test_fallback_llm_tries_next_model_after_failure() -> None:
    class _FakeClient:
        def __init__(self, model: str, *, fail: bool) -> None:
            self.model = model
            self._fail = fail

        async def generate_content_async(
            self,
            llm_request: LlmRequest,
            stream: bool = False,
        ) -> AsyncGenerator[LlmResponse, None]:
            if self._fail:
                raise RuntimeError("boom")
            yield LlmResponse(
                content=types.Content(
                    role="model",
                    parts=[types.Part.from_text(text="ok")],
                ),
                model_version=self.model,
            )

    llm = FallbackLiteLlm(model="primary", fallback_models=("secondary",))
    llm._clients = [
        _FakeClient("primary", fail=True),
        _FakeClient("secondary", fail=False),
    ]
    llm_request = LlmRequest(contents=[_content("ping")])

    responses = [response async for response in llm.generate_content_async(llm_request)]

    assert len(responses) == 1
    assert responses[0].content is not None
    assert _first_text(responses[0].content) == "ok"
    assert responses[0].model_version == "secondary"
