# Performance Baseline

- Generated at: `2026-05-25T14:40:43+00:00`
- Python: `3.12.3`
- Torch installed: `True`
- CUDA available: `True`
- Runtime mode: `GPU`
- Device: `NVIDIA GeForce RTX 2060`
- EMBEDDING_DEVICE: `cuda`

Runtime detection records the current Python/Torch mode. RAG-specific embedding and retrieval notes are appended in docs/perf_baseline.md.

## RAG Runtime Notes

- `EMBEDDING_BACKEND=auto` prefers cached `BAAI/bge-m3`; if unavailable, it falls back to the local hashing backend.
- `RERANK_BACKEND=auto` prefers cached `BAAI/bge-reranker-v2-m3`; if unavailable, it falls back to lexical reranking.
- Supported ingest formats are `.pdf`, `.txt`, `.md`, `.markdown`, `.docx`, `.html`, and `.htm`.
- Scanned PDFs still need OCR before ingest; HTML ingest parses local file content only and does not crawl linked pages.
