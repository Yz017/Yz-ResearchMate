from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.base_llm import BaseLlm
from google.adk.models.lite_llm import LiteLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from loguru import logger
from pydantic import PrivateAttr

from researchmate.config import Settings, get_settings


def _dedupe_models(models: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for model in models:
        clean = model.strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        deduped.append(clean)
    return deduped


def _part_text(part: types.Part) -> str:
    text = getattr(part, "text", None)
    if text:
        return str(text)
    function_call = getattr(part, "function_call", None)
    if function_call is not None:
        name = getattr(function_call, "name", "")
        args = getattr(function_call, "args", {})
        return f"{name} {json.dumps(args, ensure_ascii=False, default=str)}".strip()
    function_response = getattr(part, "function_response", None)
    if function_response is not None:
        name = getattr(function_response, "name", "")
        response = getattr(function_response, "response", {})
        return f"{name} {json.dumps(response, ensure_ascii=False, default=str)}".strip()
    return ""


def estimate_content_tokens(content: types.Content) -> int:
    total = 0
    for part in content.parts or []:
        text = _part_text(part)
        if not text:
            continue
        total += max(1, len(text) // 4)
    return total or 1


def estimate_request_tokens(llm_request: LlmRequest) -> int:
    return sum(estimate_content_tokens(content) for content in llm_request.contents)


def truncate_request_history(
    llm_request: LlmRequest,
    *,
    soft_limit: int,
    keep_recent: int,
) -> dict[str, int]:
    before_tokens = estimate_request_tokens(llm_request)
    if before_tokens <= soft_limit or not llm_request.contents:
        return {
            "before_tokens": before_tokens,
            "after_tokens": before_tokens,
            "removed_messages": 0,
            "kept_messages": len(llm_request.contents),
        }

    original_contents = list(llm_request.contents)
    content_tokens = [estimate_content_tokens(content) for content in original_contents]
    kept_contents = list(original_contents)
    kept_tokens = list(content_tokens)
    removed_messages = 0

    while len(kept_contents) > keep_recent and sum(kept_tokens) > soft_limit:
        kept_contents.pop(0)
        kept_tokens.pop(0)
        removed_messages += 1

    while len(kept_contents) > 1 and sum(kept_tokens) > soft_limit:
        kept_contents.pop(0)
        kept_tokens.pop(0)
        removed_messages += 1

    llm_request.contents = kept_contents
    return {
        "before_tokens": before_tokens,
        "after_tokens": sum(kept_tokens),
        "removed_messages": removed_messages,
        "kept_messages": len(kept_contents),
    }


def classify_llm_error(error: Exception) -> tuple[str, str, bool]:
    try:
        from litellm.exceptions import (
            APIConnectionError,
            InternalServerError,
            RateLimitError,
            ServiceUnavailableError,
        )
    except Exception:
        return (f"{type(error).__name__.upper()}", f"{type(error).__name__}: {error}", False)

    if isinstance(error, RateLimitError):
        return ("LLM_RATE_LIMITED", f"{type(error).__name__}: {error}", True)
    if isinstance(error, ServiceUnavailableError):
        return ("LLM_SERVICE_UNAVAILABLE", f"{type(error).__name__}: {error}", True)
    if isinstance(error, InternalServerError):
        return ("LLM_PROVIDER_ERROR", f"{type(error).__name__}: {error}", True)
    if isinstance(error, APIConnectionError):
        return ("LLM_CONNECTION_ERROR", f"{type(error).__name__}: {error}", True)
    status_code = getattr(error, "status_code", None)
    if status_code in {429, 503}:
        code = "LLM_RATE_LIMITED" if status_code == 429 else "LLM_SERVICE_UNAVAILABLE"
        return (code, f"{type(error).__name__}: {error}", True)
    return ("LLM_FAILED", f"{type(error).__name__}: {error}", False)


def make_llm_chain(settings: Settings | None = None) -> list[str]:
    settings = settings or get_settings()
    chain = [settings.researchmate_llm_model, *settings.llm_fallback_models]
    return _dedupe_models(chain)


def build_agent_llm(settings: Settings | None = None) -> FallbackLiteLlm:
    chain = make_llm_chain(settings)
    if not chain:
        chain = ["deepseek/deepseek-chat"]
    return FallbackLiteLlm(model=chain[0], fallback_models=tuple(chain[1:]))


def before_model_callback(
    callback_context: CallbackContext,
    llm_request: LlmRequest,
) -> LlmResponse | None:
    settings = get_settings()
    policy = truncate_request_history(
        llm_request,
        soft_limit=settings.llm_token_soft_limit,
        keep_recent=settings.llm_context_keep_recent,
    )
    callback_context.state["rm:llm_context_policy"] = policy
    if policy["removed_messages"] > 0:
        logger.bind(
            event="llm_context_trimmed",
            agent=callback_context.agent_name,
            invocation_id=callback_context.invocation_id,
            user_id=callback_context.user_id,
            removed_messages=policy["removed_messages"],
            before_tokens=policy["before_tokens"],
            after_tokens=policy["after_tokens"],
        ).warning("llm request history trimmed")
    return None


def after_model_callback(
    callback_context: CallbackContext,
    llm_response: LlmResponse,
) -> LlmResponse | None:
    usage = llm_response.usage_metadata
    if usage is None:
        return None

    prompt_tokens = int(getattr(usage, "prompt_token_count", 0) or 0)
    completion_tokens = int(getattr(usage, "candidates_token_count", 0) or 0)
    total_tokens = int(getattr(usage, "total_token_count", 0) or 0)
    cached_tokens = int(getattr(usage, "cached_content_token_count", 0) or 0)
    thought_tokens = int(getattr(usage, "thoughts_token_count", 0) or 0)
    totals = callback_context.state.get("rm:llm_usage_totals")
    if not isinstance(totals, dict):
        totals = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cached_tokens": 0,
            "thought_tokens": 0,
        }
    totals["prompt_tokens"] = int(totals.get("prompt_tokens", 0)) + prompt_tokens
    totals["completion_tokens"] = int(totals.get("completion_tokens", 0)) + completion_tokens
    totals["total_tokens"] = int(totals.get("total_tokens", 0)) + total_tokens
    totals["cached_tokens"] = int(totals.get("cached_tokens", 0)) + cached_tokens
    totals["thought_tokens"] = int(totals.get("thought_tokens", 0)) + thought_tokens
    callback_context.state["rm:llm_usage_totals"] = totals
    callback_context.state["rm:last_llm_usage"] = {
        "model": llm_response.model_version or "",
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "cached_tokens": cached_tokens,
        "thought_tokens": thought_tokens,
    }
    logger.bind(
        event="llm_usage",
        agent=callback_context.agent_name,
        invocation_id=callback_context.invocation_id,
        user_id=callback_context.user_id,
        model=llm_response.model_version,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        cached_tokens=cached_tokens,
        thought_tokens=thought_tokens,
    ).info("llm usage recorded")
    return None


def on_model_error_callback(
    callback_context: CallbackContext,
    llm_request: LlmRequest,
    error: Exception,
) -> LlmResponse | None:
    code, message, retryable = classify_llm_error(error)
    callback_context.state["rm:last_llm_error"] = {
        "code": code,
        "message": message,
        "retryable": retryable,
        "model": llm_request.model or "",
    }
    logger.bind(
        event="llm_error",
        agent=callback_context.agent_name,
        invocation_id=callback_context.invocation_id,
        user_id=callback_context.user_id,
        code=code,
        retryable=retryable,
        model=llm_request.model,
    ).warning("llm call failed")
    return None


class FallbackLiteLlm(BaseLlm):
    fallback_models: tuple[str, ...] = ()

    _clients: list[Any] = PrivateAttr(default_factory=list)

    def __init__(
        self,
        model: str,
        *,
        fallback_models: tuple[str, ...] = (),
        **kwargs: Any,
    ) -> None:
        super().__init__(model=model, **kwargs)
        self.fallback_models = fallback_models
        chain = _dedupe_models([model, *fallback_models])
        self._clients = [LiteLlm(model=item) for item in chain]

    @property
    def model_chain(self) -> tuple[str, ...]:
        return tuple(client.model for client in self._clients)

    async def generate_content_async(
        self,
        llm_request: LlmRequest,
        stream: bool = False,
    ) -> AsyncGenerator[LlmResponse, None]:
        last_error: Exception | None = None
        for index, client in enumerate(self._clients):
            request = llm_request.model_copy(deep=True)
            request.model = client.model
            yielded = False
            try:
                async for response in client.generate_content_async(request, stream=stream):
                    yielded = True
                    yield response
                return
            except Exception as exc:
                last_error = exc
                if yielded or index == len(self._clients) - 1:
                    raise
                logger.bind(
                    event="llm_fallback",
                    model=client.model,
                    fallback_to=self._clients[index + 1].model,
                ).warning("falling back after model failure: {}", exc)
        if last_error is not None:
            raise last_error
        return
