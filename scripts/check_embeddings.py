from __future__ import annotations

import math
from collections.abc import Sequence

from researchmate.config import get_settings
from researchmate.services.embeddings import (
    LexicalReranker,
    create_embedding_backend,
    create_reranker,
    detect_embedding_device,
)


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    numerator = sum(left * right for left, right in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(value * value for value in a))
    norm_b = math.sqrt(sum(value * value for value in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return numerator / (norm_a * norm_b)


def main() -> None:
    settings = get_settings()
    device = detect_embedding_device(settings.embedding_device)
    embedder = create_embedding_backend(settings)
    sentences = [
        "retrieval augmented generation answers questions with grounded citations",
        "RAG systems retrieve relevant chunks before generation",
        "strawberry cake recipes use sugar and flour",
        "科研助手需要基于本地论文片段给出带引用的回答",
        "论文方法部分描述了检索、重排和生成流程",
    ]
    embeddings = embedder.encode(sentences)
    print(f"embedding_backend={embedder.backend_name}")
    print(f"embedding_model={embedder.model_id}")
    print(f"embedding_device={device}")
    print(f"embedding_dimension={len(embeddings[0])}")
    print(f"cosine_related={cosine(embeddings[0], embeddings[1]):.4f}")
    print(f"cosine_unrelated={cosine(embeddings[0], embeddings[2]):.4f}")

    reranker = create_reranker(settings)
    query = "RAG citation retrieval"
    documents = sentences[:3]
    scores = reranker.score(query, documents) if hasattr(reranker, "score") else []
    ranked = sorted(zip(documents, scores, strict=True), key=lambda item: item[1], reverse=True)
    print(f"rerank_backend={getattr(reranker, 'backend_name', LexicalReranker().backend_name)}")
    for index, (document, score) in enumerate(ranked, start=1):
        print(f"rerank_{index}={score:.4f} {document}")


if __name__ == "__main__":
    main()
