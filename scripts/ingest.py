from __future__ import annotations

import argparse
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from researchmate.config import get_settings
from researchmate.services.embeddings import create_embedding_backend
from researchmate.services.pdf_parser import parse_pdf_to_chunks
from researchmate.services.vector_store import KnowledgeVectorStore

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class IngestResult:
    path: Path
    paper_id: str
    chunks: int


def _batched(items: Sequence[T], batch_size: int) -> Iterable[Sequence[T]]:
    for start in range(0, len(items), batch_size):
        yield items[start : start + batch_size]


def ingest_pdf_paths(
    paths: Sequence[str | Path],
    *,
    paper_id: str | None = None,
    title: str | None = None,
    reset: bool = False,
    chroma_dir: str | Path | None = None,
    collection_name: str | None = None,
) -> list[IngestResult]:
    settings = get_settings()
    store = KnowledgeVectorStore(
        persist_directory=chroma_dir or settings.chroma_dir,
        collection_name=collection_name or settings.kb_collection,
    )
    if reset:
        store.reset()
    embedder = create_embedding_backend(settings)
    results: list[IngestResult] = []
    for raw_path in paths:
        pdf_path = Path(raw_path)
        chunks = parse_pdf_to_chunks(pdf_path, paper_id=paper_id, title=title)
        existing_ids = store.get_existing_ids([chunk.id for chunk in chunks])
        inserted_ids: list[str] = []
        try:
            for batch in _batched(chunks, settings.embedding_batch_size):
                embeddings = embedder.encode([chunk.text for chunk in batch])
                store.upsert_chunks(batch, embeddings, embedding_model=embedder.model_id)
                inserted_ids.extend(chunk.id for chunk in batch if chunk.id not in existing_ids)
        except Exception:
            store.delete_ids(inserted_ids)
            raise
        resolved_paper_id = chunks[0].paper_id if chunks else (paper_id or pdf_path.stem)
        results.append(
            IngestResult(
                path=pdf_path,
                paper_id=resolved_paper_id,
                chunks=len(chunks),
            )
        )
    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ingest local PDF files into Chroma.")
    parser.add_argument("pdf", nargs="+", help="PDF path(s) to ingest.")
    parser.add_argument("--paper-id", help="Override paper_id. Use only for one PDF.")
    parser.add_argument("--title", help="Override title. Use only for one PDF.")
    parser.add_argument(
        "--reset", action="store_true", help="Reset the kb collection before ingest."
    )
    parser.add_argument("--chroma-dir", help="Override Chroma persist directory.")
    parser.add_argument("--collection", help="Override Chroma collection name.")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if len(args.pdf) > 1 and (args.paper_id or args.title):
        parser.error("--paper-id/--title can only be used with one PDF")
    results = ingest_pdf_paths(
        args.pdf,
        paper_id=args.paper_id,
        title=args.title,
        reset=bool(args.reset),
        chroma_dir=args.chroma_dir,
        collection_name=args.collection,
    )
    for result in results:
        print(f"{result.path}: paper_id={result.paper_id} chunks={result.chunks}")


if __name__ == "__main__":
    main()
