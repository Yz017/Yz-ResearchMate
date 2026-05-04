from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from researchmate.config import get_settings
from researchmate.services.knowledge_base import IngestedDocument, KnowledgeBaseService
from researchmate.services.vector_store import KnowledgeVectorStore


def ingest_pdf_paths(
    paths: Sequence[str | Path],
    *,
    paper_id: str | None = None,
    title: str | None = None,
    reset: bool = False,
    chroma_dir: str | Path | None = None,
    collection_name: str | None = None,
) -> list[IngestedDocument]:
    settings = get_settings()
    service = KnowledgeBaseService.from_settings(settings)
    if chroma_dir is not None or collection_name is not None:
        service = KnowledgeBaseService(
            settings=settings,
            store=KnowledgeVectorStore(
                persist_directory=chroma_dir or settings.chroma_dir,
                collection_name=collection_name or settings.kb_collection,
            ),
        )
    if reset:
        service.store.reset()
    results: list[IngestedDocument] = []
    for raw_path in paths:
        pdf_path = Path(raw_path)
        results.append(
            service.ingest_pdf(
                pdf_path,
                paper_id=paper_id,
                title=title,
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
        print(f"{result.source_path}: paper_id={result.doc_id} chunks={result.chunks}")


if __name__ == "__main__":
    main()
