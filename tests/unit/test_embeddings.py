from __future__ import annotations

import pytest

from researchmate.config import Settings
from researchmate.services import embeddings


def test_flag_reranker_does_not_fall_back_when_model_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        RERANK_BACKEND="flag",
        RERANKER_MODEL="BAAI/bge-reranker-v2-m3",
        RERANK_ALLOW_DOWNLOAD=False,
    )
    monkeypatch.setattr(embeddings, "_find_cached_model_path", lambda model_name: None)

    with pytest.raises(RuntimeError, match="Refusing to fall back to lexical"):
        embeddings.create_reranker(settings)


def test_flag_reranker_uses_dedicated_device_and_batch_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class DummyFlagReranker:
        def __init__(
            self,
            *,
            model_name: str,
            device: str,
            allow_download: bool,
            batch_size: int,
        ) -> None:
            captured["model_name"] = model_name
            captured["device"] = device
            captured["allow_download"] = allow_download
            captured["batch_size"] = batch_size

    settings = Settings(
        RERANK_BACKEND="flag",
        RERANKER_MODEL="BAAI/bge-reranker-v2-m3",
        RERANK_ALLOW_DOWNLOAD=False,
        RERANK_DEVICE="cpu",
        RERANK_BATCH_SIZE=1,
    )
    monkeypatch.setattr(
        embeddings,
        "_find_cached_model_path",
        lambda model_name: "/models/bge-reranker-v2-m3",
    )
    monkeypatch.setattr(embeddings, "FlagEmbeddingReranker", DummyFlagReranker)

    embeddings.create_reranker(settings)

    assert captured == {
        "model_name": "BAAI/bge-reranker-v2-m3",
        "device": "cpu",
        "allow_download": False,
        "batch_size": 1,
    }
