# Performance Baseline

- Generated at: `2026-05-03T09:06:48+00:00`
- Python: `3.12.3`
- Torch installed: `True`
- CUDA available: `False`
- Runtime mode: `CPU`
- Device: `cpu`
- EMBEDDING_DEVICE: `auto`
- EMBEDDING_BACKEND: `auto` with offline fallback
- RERANK_BACKEND: `auto` with lexical fallback

## M1 RAG Baseline

- RAG extra dependencies installed: `torch`, `sentence-transformers`, `FlagEmbedding`
- CUDA status: unavailable on this machine because the installed NVIDIA driver is too old for the synced torch CUDA build
- Model cache status: `BAAI/bge-m3` and `BAAI/bge-reranker-v2-m3` are not cached locally; HuggingFace access returned `Errno 101 Network is unreachable`
- Active embedding path: `hashing:1024`
- Active rerank path: `lexical-overlap`
- Embedding sanity check: related cosine `0.1590`, unrelated cosine `0.0000`
- Sample ingest verification: 3 generated PDFs, 9 chunks total in local Chroma
- Retrieval verification query: `grounded citation answers` returned top chunk `[source: rag_basics, p.1]`
- ADK Runner verification: `scripts/check_m1_rag_agent.py` passed and produced `[source: rag_basics, p.1]`
