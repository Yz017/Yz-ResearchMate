from __future__ import annotations

import importlib
import math
import os
import re
import warnings
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import blake2b
from pathlib import Path
from typing import Any, Protocol

from researchmate.config import Settings, get_settings

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]")


@dataclass(frozen=True, slots=True)
class EmbeddingDiagnostics:
    backend: str
    model_id: str
    dimension: int
    device: str
    notes: str = ""


class EmbeddingBackend(Protocol):
    @property
    def backend_name(self) -> str: ...

    @property
    def model_id(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    def encode(self, texts: Sequence[str]) -> list[list[float]]: ...


class Reranker(Protocol):
    @property
    def backend_name(self) -> str: ...

    @property
    def model_id(self) -> str: ...

    def score(self, query: str, documents: Sequence[str]) -> list[float]: ...


@contextmanager
def _offline_hf_context(enabled: bool) -> Iterator[None]:
    if not enabled:
        yield
        return
    keys = ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        for key in keys:
            os.environ[key] = "1"
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _resolve_cached_model_path(model_name: str, *, allow_download: bool) -> str:
    if allow_download or Path(model_name).exists():
        return model_name
    cached_path = _find_cached_model_path(model_name)
    if cached_path is not None:
        return cached_path
    return model_name


def _find_cached_model_path(model_name: str) -> str | None:
    try:
        module = importlib.import_module("huggingface_hub")
        snapshot_download = module.snapshot_download
        return str(snapshot_download(model_name, local_files_only=True))
    except Exception:
        return None


def detect_embedding_device(requested: str) -> str:
    if requested != "auto":
        return requested
    try:
        torch = importlib.import_module("torch")
    except Exception:
        return "cpu"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        cuda_available = bool(getattr(torch.cuda, "is_available", lambda: False)())
    if cuda_available:
        return "cuda"
    return "cpu"


def estimate_token_count(text: str) -> int:
    return max(1, len(_TOKEN_RE.findall(text)))


def _tokenize(text: str) -> list[str]:
    return [token.lower() for token in _TOKEN_RE.findall(text)]


class HashingEmbeddingBackend:
    """Stable local embedding backend with no external dependencies."""

    def __init__(self, *, dimension: int = 1024) -> None:
        self._dimension = dimension

    @property
    def backend_name(self) -> str:
        return "hashing"

    @property
    def model_id(self) -> str:
        return f"hashing:{self._dimension}"

    @property
    def dimension(self) -> int:
        return self._dimension

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._encode_one(text) for text in texts]

    def _encode_one(self, text: str) -> list[float]:
        vector = [0.0] * self._dimension
        tokens = _tokenize(text)
        if not tokens:
            return vector
        for token in tokens:
            digest = blake2b(token.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "big") % self._dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            weight = 1.0 + math.log1p(len(token))
            vector[index] += sign * weight
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0.0:
            return vector
        return [value / norm for value in vector]


class SentenceTransformerEmbeddingBackend:
    """BGE/SentenceTransformer backed embedding runtime."""

    def __init__(
        self,
        *,
        model_name: str,
        device: str,
        batch_size: int,
        allow_download: bool,
        dimension: int = 1024,
    ) -> None:
        self._model_name = model_name
        self._device = device
        self._batch_size = batch_size
        self._allow_download = allow_download
        self._dimension = dimension
        self._model: Any | None = None

    @property
    def backend_name(self) -> str:
        return "sentence-transformers"

    @property
    def model_id(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._dimension

    def _load_model(self) -> Any:
        if self._model is None:
            module = importlib.import_module("sentence_transformers")
            sentence_transformer = module.SentenceTransformer
            local_files_only = not self._allow_download
            model_name_or_path = _resolve_cached_model_path(
                self._model_name,
                allow_download=self._allow_download,
            )
            with _offline_hf_context(local_files_only):
                self._model = sentence_transformer(
                    model_name_or_path,
                    device=self._device,
                    local_files_only=local_files_only,
                    model_kwargs={"local_files_only": local_files_only},
                    config_kwargs={"local_files_only": local_files_only},
                )
        return self._model

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        model = self._load_model()
        embeddings = model.encode(
            list(texts),
            batch_size=self._batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [[float(value) for value in row] for row in embeddings]


class AutoEmbeddingBackend:
    """Prefer a transformer backend when available, otherwise fall back locally."""

    def __init__(
        self,
        *,
        primary: EmbeddingBackend | None,
        fallback: EmbeddingBackend,
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._last_error: str | None = None

    @property
    def backend_name(self) -> str:
        if self._primary is not None and self._last_error is None:
            return self._primary.backend_name
        return self._fallback.backend_name

    @property
    def model_id(self) -> str:
        if self._primary is not None and self._last_error is None:
            return self._primary.model_id
        if self._last_error:
            return f"{self._fallback.model_id} (fallback from {self._last_error})"
        return self._fallback.model_id

    @property
    def dimension(self) -> int:
        if self._primary is not None and self._last_error is None:
            return self._primary.dimension
        return self._fallback.dimension

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        if self._primary is not None and self._last_error is None:
            try:
                return self._primary.encode(texts)
            except Exception as exc:
                self._last_error = f"{type(exc).__name__}: {exc}"
        return self._fallback.encode(texts)


class LexicalReranker:
    """Fast local reranker based on token overlap."""

    def __init__(self) -> None:
        self._backend_name = "lexical"

    @property
    def backend_name(self) -> str:
        return self._backend_name

    @property
    def model_id(self) -> str:
        return "lexical-overlap"

    def score(self, query: str, documents: Sequence[str]) -> list[float]:
        query_tokens = _tokenize(query)
        if not query_tokens:
            return [0.0 for _ in documents]
        query_counts: dict[str, int] = {}
        for token in query_tokens:
            query_counts[token] = query_counts.get(token, 0) + 1
        scores: list[float] = []
        for document in documents:
            document_tokens = _tokenize(document)
            if not document_tokens:
                scores.append(0.0)
                continue
            doc_counts: dict[str, int] = {}
            for token in document_tokens:
                doc_counts[token] = doc_counts.get(token, 0) + 1
            overlap = 0.0
            for token, q_count in query_counts.items():
                overlap += float(min(q_count, doc_counts.get(token, 0)))
            scores.append(overlap / math.sqrt(len(query_counts) * len(doc_counts)))
        return scores


class FlagEmbeddingReranker:
    """Optional transformer reranker."""

    def __init__(
        self,
        *,
        model_name: str,
        device: str,
        allow_download: bool,
        batch_size: int = 1,
    ) -> None:
        module = importlib.import_module("FlagEmbedding")
        reranker_class = module.FlagReranker
        local_files_only = not allow_download
        model_name_or_path = _resolve_cached_model_path(
            model_name,
            allow_download=allow_download,
        )
        with _offline_hf_context(local_files_only):
            self._model = reranker_class(
                model_name_or_path,
                use_fp16=device == "cuda",
                local_files_only=local_files_only,
            )
        self._backend_name = "flagembedding"
        self._model_name = model_name
        self._batch_size = batch_size

    @property
    def backend_name(self) -> str:
        return self._backend_name

    @property
    def model_id(self) -> str:
        return self._model_name

    def score(self, query: str, documents: Sequence[str]) -> list[float]:
        all_scores: list[float] = []
        for start in range(0, len(documents), self._batch_size):
            batch = documents[start : start + self._batch_size]
            pairs = [(query, document) for document in batch]
            scores = self._model.compute_score(pairs, normalize=True)
            if isinstance(scores, int | float):
                all_scores.append(float(scores))
                continue
            all_scores.extend(float(score) for score in scores)
        return all_scores


class NoReranker:
    @property
    def backend_name(self) -> str:
        return "none"

    @property
    def model_id(self) -> str:
        return "none"

    def score(self, query: str, documents: Sequence[str]) -> list[float]:
        del query
        return [0.0 for _ in documents]


def create_embedding_backend(settings: Settings | None = None) -> EmbeddingBackend:
    settings = settings or get_settings()
    fallback = HashingEmbeddingBackend()
    if settings.embedding_backend == "hashing":
        return fallback
    if settings.embedding_backend == "sentence-transformers":
        return SentenceTransformerEmbeddingBackend(
            model_name=settings.embedding_model,
            device=detect_embedding_device(settings.embedding_device),
            batch_size=settings.embedding_batch_size,
            allow_download=settings.embedding_allow_download,
            dimension=1024,
        )
    try:
        importlib.import_module("sentence_transformers")
    except Exception:
        return fallback
    if (
        not settings.embedding_allow_download
        and _find_cached_model_path(settings.embedding_model) is None
    ):
        return fallback
    primary = SentenceTransformerEmbeddingBackend(
        model_name=settings.embedding_model,
        device=detect_embedding_device(settings.embedding_device),
        batch_size=settings.embedding_batch_size,
        allow_download=settings.embedding_allow_download,
        dimension=1024,
    )
    return AutoEmbeddingBackend(primary=primary, fallback=fallback)


def create_reranker(settings: Settings | None = None) -> Reranker:
    settings = settings or get_settings()
    device = detect_embedding_device(
        settings.embedding_device if settings.rerank_device == "auto" else settings.rerank_device
    )
    if settings.rerank_backend == "none":
        return NoReranker()
    if settings.rerank_backend == "lexical":
        return LexicalReranker()
    if settings.rerank_backend == "flag":
        if (
            not settings.rerank_allow_download
            and _find_cached_model_path(settings.reranker_model) is None
        ):
            msg = (
                f"RERANK_BACKEND=flag requires {settings.reranker_model} to be cached "
                "locally, or RERANK_ALLOW_DOWNLOAD=true. Refusing to fall back to lexical."
            )
            raise RuntimeError(msg)
        return FlagEmbeddingReranker(
            model_name=settings.reranker_model,
            device=device,
            allow_download=settings.rerank_allow_download,
            batch_size=settings.rerank_batch_size,
        )
    try:
        importlib.import_module("FlagEmbedding")
    except Exception:
        return LexicalReranker()
    if (
        not settings.rerank_allow_download
        and _find_cached_model_path(settings.reranker_model) is None
    ):
        return LexicalReranker()
    try:
        return FlagEmbeddingReranker(
            model_name=settings.reranker_model,
            device=device,
            allow_download=settings.rerank_allow_download,
            batch_size=settings.rerank_batch_size,
        )
    except Exception:
        return LexicalReranker()


def build_embedding_diagnostics(
    *,
    backend: EmbeddingBackend,
    device: str,
) -> EmbeddingDiagnostics:
    return EmbeddingDiagnostics(
        backend=backend.backend_name,
        model_id=backend.model_id,
        dimension=backend.dimension,
        device=device,
    )
