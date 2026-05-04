# Performance Baseline

- Generated at: `2026-05-04T00:00:00+08:00`
- Python: `3.12.3`
- Torch installed: `True`
- CUDA available: `False`
- Runtime mode: `CPU`
- Device: `cpu`
- EMBEDDING_DEVICE: `auto`
- EMBEDDING_BACKEND: `auto` with cached BGE preferred and offline fallback
- RERANK_BACKEND: `auto` with cached BGE preferred and lexical fallback

## M1 RAG Baseline

- RAG extra dependencies installed: `torch`, `sentence-transformers`, `FlagEmbedding`, `transformers<5`
- CUDA status: unavailable on this machine because the installed NVIDIA driver is too old for the synced torch CUDA build
- Model cache status: `BAAI/bge-m3` and `BAAI/bge-reranker-v2-m3` are cached locally via `https://hf-mirror.com`
- Active embedding path: `BAAI/bge-m3` on CPU
- Active rerank path: `BAAI/bge-reranker-v2-m3` on CPU
- Embedding sanity check: related cosine `0.5190`, unrelated cosine `0.2781`
- Rerank sanity check: related pair `0.6654`, unrelated pair `0.0000`
- Sample ingest verification: 3 generated PDFs, 9 chunks total in local Chroma
- Retrieval verification query: `grounded citation answers` returned top chunk `[source: rag_basics, p.1]`
- Low-confidence query check: `image classification` returned `NONE`
- ADK Runner verification: `scripts/check_m1_rag_agent.py` passed and produced `[source: rag_basics, p.1]`
