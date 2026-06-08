from __future__ import annotations

import importlib
import re
from collections.abc import Callable
from typing import Any, Protocol

from researchmate.config import Settings
from researchmate.services.documents import MetadataValue, RetrievedChunk


class QueryExpansionError(RuntimeError):
    """Raised when query expansion cannot produce usable variants."""


class LlmCaller(Protocol):
    def __call__(self, messages: list[dict[str, str]], *, settings: Settings) -> str: ...


class SupportsSearch(Protocol):
    def search(
        self,
        query: str,
        *,
        filters: dict[str, MetadataValue] | None = None,
        top_k: int | None = None,
    ) -> list[RetrievedChunk]: ...


VariantProvider = Callable[[str], list[str]]

_LINE_PREFIX_RE = re.compile(
    r"^\s*(?:[-*]+|[0-9]+[\).\:：、]|[（(]?[0-9]+[）)]|[A-Za-z][\).\:：、])\s*"
)
_WHITESPACE_RE = re.compile(r"\s+")


def generate_query_variants(
    query: str,
    *,
    n_variants: int,
    settings: Settings,
    llm_caller: LlmCaller | None = None,
) -> list[str]:
    if n_variants < 1:
        msg = "n_variants must be >= 1"
        raise ValueError(msg)
    if not settings.has_deepseek_api_key:
        msg = "DEEPSEEK_API_KEY is required for multi-query expansion."
        raise QueryExpansionError(msg)

    clean_query = query.strip()
    messages = [
        {
            "role": "user",
            "content": (
                "把下面的检索问题改写成 "
                f"{n_variants} 个语义等价但措辞不同的版本,用于扩大文档检索召回。\n"
                "要求:① 保留全部专有名词、符号、缩写;② 不要添加原问题没有的信息;\n"
                "③ 不要回答问题;④ 每行一个,只输出改写,不要编号或解释。\n"
                f"问题:{clean_query}"
            ),
        }
    ]
    caller = llm_caller or _call_llm
    try:
        raw_output = caller(messages, settings=settings)
    except QueryExpansionError:
        raise
    except Exception as exc:
        msg = f"Query expansion LLM call failed: {type(exc).__name__}: {exc}"
        raise QueryExpansionError(msg) from exc

    variants = _clean_variants(raw_output, original_query=clean_query, n_variants=n_variants)
    if not variants:
        msg = "Query expansion returned no usable variants."
        raise QueryExpansionError(msg)
    return variants


def generate_hyde_documents(
    query: str,
    *,
    n_docs: int,
    settings: Settings,
    llm_caller: LlmCaller | None = None,
) -> list[str]:
    if n_docs < 1:
        msg = "n_docs must be >= 1"
        raise ValueError(msg)
    if not settings.has_deepseek_api_key:
        msg = "DEEPSEEK_API_KEY is required for HyDE generation."
        raise QueryExpansionError(msg)

    clean_query = query.strip()
    messages = [
        {
            "role": "user",
            "content": (
                "你是该领域专家。针对下面的问题,写一段 3–5 句、像教材正文的"
                '"理想答案",仅用于检索匹配。\n'
                "要求:① 只用通用领域术语,可笼统;② 严禁编造具体公式编号、定理名、数值、API 名;\n"
                "③ 用与问题相同的语言作答(中文问题→中文)。\n"
                f"问题:{clean_query}"
            ),
        }
    ]
    caller = llm_caller or _call_llm
    try:
        raw_output = caller(messages, settings=settings)
    except QueryExpansionError:
        raise
    except Exception as exc:
        msg = f"HyDE LLM call failed: {type(exc).__name__}: {exc}"
        raise QueryExpansionError(msg) from exc

    documents = _clean_hyde_documents(raw_output, n_docs=n_docs)
    if not documents:
        msg = "HyDE generation returned no usable documents."
        raise QueryExpansionError(msg)
    return documents


def rrf_merge(
    result_lists: list[list[RetrievedChunk]],
    *,
    k: int = 60,
    top_k: int,
) -> list[RetrievedChunk]:
    if top_k <= 0:
        return []

    scores: dict[str, float] = {}
    representatives: dict[str, RetrievedChunk] = {}
    best_rank: dict[str, int] = {}
    first_seen: dict[str, int] = {}
    seen_index = 0

    for results in result_lists:
        for rank, chunk in enumerate(results, start=1):
            chunk_id = chunk.id
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
            if chunk_id not in representatives:
                representatives[chunk_id] = chunk
                best_rank[chunk_id] = rank
                first_seen[chunk_id] = seen_index
                seen_index += 1
            elif rank < best_rank[chunk_id]:
                representatives[chunk_id] = chunk
                best_rank[chunk_id] = rank

    ranked_ids = sorted(
        scores,
        key=lambda chunk_id: (-scores[chunk_id], best_rank[chunk_id], first_seen[chunk_id]),
    )
    merged: list[RetrievedChunk] = []
    for chunk_id in ranked_ids[:top_k]:
        chunk = representatives[chunk_id]
        merged.append(
            RetrievedChunk(
                id=chunk.id,
                text=chunk.text,
                metadata=chunk.metadata,
                score=scores[chunk_id],
                dense_rank=chunk.dense_rank,
                sparse_rank=chunk.sparse_rank,
                rerank_score=chunk.rerank_score,
            )
        )
    return merged


class MultiQueryRetriever:
    """Duck-typed wrapper exposing the same ``search`` method as KnowledgeRetriever."""

    def __init__(
        self,
        base: SupportsSearch,
        *,
        settings: Settings,
        variant_provider: VariantProvider | None = None,
        hyde_provider: VariantProvider | None = None,
        use_multi_query: bool | None = None,
        use_hyde: bool | None = None,
    ) -> None:
        self.base = base
        self.settings = settings
        self.variant_provider = variant_provider
        self.hyde_provider = hyde_provider
        self.use_multi_query = (
            settings.rag_multi_query_enabled if use_multi_query is None else use_multi_query
        )
        self.use_hyde = settings.rag_hyde_enabled if use_hyde is None else use_hyde
        self.n_variants = settings.rag_multi_query_variants
        self.n_docs = settings.rag_hyde_docs
        self.pool_k = settings.rag_multi_query_pool_k
        self.hyde_pool_k = settings.rag_hyde_pool_k
        self.final_k = int(getattr(base, "final_k", settings.rag_final_k))

    def search(
        self,
        query: str,
        *,
        filters: dict[str, MetadataValue] | None = None,
        top_k: int | None = None,
    ) -> list[RetrievedChunk]:
        clean_query = query.strip()
        if not clean_query:
            return []
        query_specs = [(clean_query, self._original_pool_k())]
        if self.use_multi_query:
            query_specs.extend((variant, self.pool_k) for variant in self._variants(clean_query))
        if self.use_hyde:
            query_specs.extend(
                (document, self.hyde_pool_k) for document in self._hyde_docs(clean_query)
            )
        pools = [self.base.search(q, top_k=pool_k, filters=filters) for q, pool_k in query_specs]
        return rrf_merge(pools, top_k=top_k or self.final_k)

    def _original_pool_k(self) -> int:
        pool_sizes: list[int] = []
        if self.use_multi_query:
            pool_sizes.append(self.pool_k)
        if self.use_hyde:
            pool_sizes.append(self.hyde_pool_k)
        return max(pool_sizes) if pool_sizes else self.final_k

    def _variants(self, query: str) -> list[str]:
        if self.variant_provider is not None:
            variants = self.variant_provider(query)
        else:
            variants = generate_query_variants(
                query,
                n_variants=self.n_variants,
                settings=self.settings,
            )
        if not variants:
            msg = "Query expansion returned no usable variants."
            raise QueryExpansionError(msg)
        return variants[: self.n_variants]

    def _hyde_docs(self, query: str) -> list[str]:
        if self.hyde_provider is not None:
            documents = self.hyde_provider(query)
        else:
            documents = generate_hyde_documents(
                query,
                n_docs=self.n_docs,
                settings=self.settings,
            )
        if not documents:
            msg = "HyDE generation returned no usable documents."
            raise QueryExpansionError(msg)
        return documents[: self.n_docs]


def build_query_retriever(
    base: SupportsSearch,
    settings: Settings,
    *,
    enabled: bool | None = None,
    hyde_enabled: bool | None = None,
    variant_provider: VariantProvider | None = None,
    hyde_provider: VariantProvider | None = None,
) -> SupportsSearch:
    use_multi_query = settings.rag_multi_query_enabled if enabled is None else enabled
    use_hyde = settings.rag_hyde_enabled if hyde_enabled is None else hyde_enabled
    if not use_multi_query and not use_hyde:
        return base
    return MultiQueryRetriever(
        base,
        settings=settings,
        variant_provider=variant_provider,
        hyde_provider=hyde_provider,
        use_multi_query=use_multi_query,
        use_hyde=use_hyde,
    )


def _call_llm(messages: list[dict[str, str]], *, settings: Settings) -> str:
    if not settings.has_deepseek_api_key:
        msg = "DEEPSEEK_API_KEY is required for multi-query expansion."
        raise QueryExpansionError(msg)
    try:
        litellm = importlib.import_module("litellm")
    except Exception as exc:
        msg = f"litellm is unavailable: {type(exc).__name__}: {exc}"
        raise QueryExpansionError(msg) from exc

    last_error: Exception | None = None
    for model in _llm_model_chain(settings):
        try:
            kwargs: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "temperature": 0.3,
                "max_tokens": 256,
            }
            if model.startswith("deepseek/") and settings.deepseek_api_key is not None:
                kwargs["api_key"] = settings.deepseek_api_key.get_secret_value()
            response = litellm.completion(**kwargs)
        except Exception as exc:
            last_error = exc
            continue
        return _extract_response_text(response)

    if last_error is None:
        msg = "No LLM models configured for query expansion."
        raise QueryExpansionError(msg)
    msg = f"Query expansion LLM failed for all models: {type(last_error).__name__}: {last_error}"
    raise QueryExpansionError(msg) from last_error


def _llm_model_chain(settings: Settings) -> list[str]:
    seen: set[str] = set()
    models: list[str] = []
    for model in [settings.researchmate_llm_model, *settings.llm_fallback_models]:
        clean = model.strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        models.append(clean)
    return models


def _extract_response_text(response: Any) -> str:
    choices = _get_attr_or_key(response, "choices")
    if not isinstance(choices, list) or not choices:
        return ""
    message = _get_attr_or_key(choices[0], "message")
    content = _get_attr_or_key(message, "content")
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return str(content)


def _get_attr_or_key(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _clean_variants(raw_output: str, *, original_query: str, n_variants: int) -> list[str]:
    variants: list[str] = []
    seen: set[str] = {_normalize_for_dedupe(original_query)}
    for raw_line in raw_output.splitlines():
        line = _clean_variant_line(raw_line)
        if not line:
            continue
        dedupe_key = _normalize_for_dedupe(line)
        if not dedupe_key or dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        variants.append(line)
        if len(variants) >= n_variants:
            break
    return variants


def _clean_hyde_documents(raw_output: str, *, n_docs: int) -> list[str]:
    clean_output = raw_output.strip()
    if not clean_output:
        return []
    if n_docs == 1:
        document = _clean_hyde_document(clean_output)
        return [document] if document else []

    documents: list[str] = []
    seen: set[str] = set()
    for paragraph in re.split(r"(?:\r?\n\s*){2,}", clean_output):
        document = _clean_hyde_document(paragraph)
        dedupe_key = _normalize_for_dedupe(document)
        if not document or not dedupe_key or dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        documents.append(document)
        if len(documents) >= n_docs:
            break
    return documents


def _clean_hyde_document(document: str) -> str:
    clean = _LINE_PREFIX_RE.sub("", document.strip().strip("\"'"))
    lines = [line.strip() for line in clean.splitlines() if line.strip()]
    return _WHITESPACE_RE.sub(" ", " ".join(lines)).strip()


def _clean_variant_line(line: str) -> str:
    clean = line.strip().strip("\"'")
    previous = None
    while clean and clean != previous:
        previous = clean
        clean = _LINE_PREFIX_RE.sub("", clean).strip().strip("\"'")
    return clean


def _normalize_for_dedupe(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip().casefold()
