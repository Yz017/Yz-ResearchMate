"""Offline retrieval evaluation: Recall@K, MRR@K, nDCG@K.

Reads ground-truth annotations from ``eval/retrieval_groundtruth.json`` and runs
each query through :class:`KnowledgeRetriever`. Hit rule: a retrieved chunk is
considered correct when it matches any entry in ``gold_targets``. A target
matches by exact ``chunk_ids`` first, then by ``paper_id`` plus ``pages``.
Legacy cases using ``gold_paper_id`` + ``gold_pages`` are still accepted.

Examples
--------

Run all metrics with default K values::

    uv run python scripts/eval_retrieval.py

Pick a single metric::

    uv run python scripts/eval_retrieval.py --metric recall --k 5
    uv run python scripts/eval_retrieval.py --metric mrr --k 10
    uv run python scripts/eval_retrieval.py --metric ndcg --k 5

Run rerank ablation by toggling the environment variable::

    RERANK_BACKEND=none uv run python scripts/eval_retrieval.py --metric all

Per-case breakdown::

    uv run python scripts/eval_retrieval.py --verbose
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from researchmate.config import Settings, get_settings
from researchmate.services.documents import RetrievedChunk
from researchmate.services.query_expansion import (
    QueryExpansionError,
    SupportsSearch,
    build_query_retriever,
    generate_hyde_documents,
    generate_query_variants,
)
from researchmate.services.retriever import KnowledgeRetriever

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GROUNDTRUTH = ROOT / "eval" / "retrieval_groundtruth.json"
DEFAULT_VARIANTS_CACHE = ROOT / "eval" / "query_variants_cache.json"
DEFAULT_HYDE_CACHE = ROOT / "eval" / "hyde_cache.json"
DEFAULT_K_RECALL = (5, 10)
DEFAULT_K_MRR = 10
DEFAULT_K_NDCG = 5

console = Console()


@dataclass(frozen=True, slots=True)
class GoldTarget:
    paper_id: str
    pages: tuple[int, ...]
    chunk_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GroundTruthCase:
    qid: str
    query: str
    gold_targets: tuple[GoldTarget, ...]
    relevance_grades: dict[str, int]
    tags: tuple[str, ...]


@dataclass(slots=True)
class CaseResult:
    case: GroundTruthCase
    hit_ranks: list[int]
    first_hit_rank: int | None
    retrieved: list[RetrievedChunk]
    query_variants: list[str]
    hyde_documents: list[str]


class CachedVariantProvider:
    def __init__(
        self,
        *,
        path: Path,
        settings: Settings,
        refresh: bool,
    ) -> None:
        self.path = path
        self.settings = settings
        self.refresh = refresh
        self.cache = _load_variants_cache(path)
        self.used: dict[str, list[str]] = {}

    def __call__(self, query: str) -> list[str]:
        if query in self.used:
            return list(self.used[query])

        if not self.refresh and query in self.cache:
            variants = _normalize_cached_variants(
                query,
                self.cache[query],
                n_variants=self.settings.rag_multi_query_variants,
            )
            if not variants:
                msg = f"Cached query variants are empty for query: {query}"
                raise QueryExpansionError(msg)
            self.used[query] = variants
            return list(variants)

        variants = generate_query_variants(
            query,
            n_variants=self.settings.rag_multi_query_variants,
            settings=self.settings,
        )
        self.cache[query] = variants
        self.used[query] = variants
        self.write()
        return list(variants)

    def write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.cache, ensure_ascii=False, indent=2)
        tmp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        tmp_path.write_text(payload, encoding="utf-8")
        tmp_path.replace(self.path)


class CachedHydeProvider:
    def __init__(
        self,
        *,
        path: Path,
        settings: Settings,
        refresh: bool,
    ) -> None:
        self.path = path
        self.settings = settings
        self.refresh = refresh
        self.cache = _load_text_list_cache(path, label="HyDE cache")
        self.used: dict[str, list[str]] = {}

    def __call__(self, query: str) -> list[str]:
        if query in self.used:
            return list(self.used[query])

        if not self.refresh and query in self.cache:
            documents = _normalize_cached_documents(
                self.cache[query],
                n_docs=self.settings.rag_hyde_docs,
            )
            if not documents:
                msg = f"Cached HyDE documents are empty for query: {query}"
                raise QueryExpansionError(msg)
            self.used[query] = documents
            return list(documents)

        documents = generate_hyde_documents(
            query,
            n_docs=self.settings.rag_hyde_docs,
            settings=self.settings,
        )
        self.cache[query] = documents
        self.used[query] = documents
        self.write()
        return list(documents)

    def write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.cache, ensure_ascii=False, indent=2)
        tmp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        tmp_path.write_text(payload, encoding="utf-8")
        tmp_path.replace(self.path)


def _load_variants_cache(path: Path) -> dict[str, list[str]]:
    return _load_text_list_cache(path, label="Query variants cache")


def _load_text_list_cache(path: Path, *, label: str) -> dict[str, list[str]]:
    if not path.exists():
        return {}
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        msg = f"Invalid {label} JSON in {path}: {exc.msg}"
        raise ValueError(msg) from exc
    if not isinstance(payload, dict):
        msg = f"{label} must be a JSON object: {path}"
        raise ValueError(msg)

    raw_entries: Any = (
        payload.get("variants") if isinstance(payload.get("variants"), dict) else payload
    )
    if not isinstance(raw_entries, dict):
        msg = f"{label} entries must be a JSON object: {path}"
        raise ValueError(msg)

    cache: dict[str, list[str]] = {}
    for raw_query, raw_variants in raw_entries.items():
        if not isinstance(raw_query, str):
            msg = f"{label} contains a non-string query key: {path}"
            raise ValueError(msg)
        if not isinstance(raw_variants, list):
            msg = f"{label} value for {raw_query!r} must be a list"
            raise ValueError(msg)
        variants: list[str] = []
        for raw_variant in raw_variants:
            if not isinstance(raw_variant, str):
                msg = f"{label} value for {raw_query!r} contains a non-string item"
                raise ValueError(msg)
            variants.append(raw_variant)
        cache[raw_query] = variants
    return cache


def _normalize_cached_variants(
    query: str,
    variants: list[str],
    *,
    n_variants: int,
) -> list[str]:
    normalized: list[str] = []
    seen = {_cache_dedupe_key(query)}
    for variant in variants:
        clean = variant.strip()
        dedupe_key = _cache_dedupe_key(clean)
        if not clean or not dedupe_key or dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        normalized.append(clean)
        if len(normalized) >= n_variants:
            break
    return normalized


def _normalize_cached_documents(documents: list[str], *, n_docs: int) -> list[str]:
    normalized: list[str] = []
    for document in documents:
        clean = " ".join(document.strip().split())
        if not clean:
            continue
        normalized.append(clean)
        if len(normalized) >= n_docs:
            break
    return normalized


def _cache_dedupe_key(text: str) -> str:
    return " ".join(text.split()).casefold()


def load_groundtruth(path: Path) -> list[GroundTruthCase]:
    if not path.exists():
        msg = f"Ground-truth file not found: {path}"
        raise FileNotFoundError(msg)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        msg = f"Invalid JSON in {path}: line {exc.lineno}, column {exc.colno}: {exc.msg}"
        raise ValueError(msg) from exc
    raw_cases = payload.get("cases") if isinstance(payload, dict) else payload
    if not isinstance(raw_cases, list) or not raw_cases:
        msg = f"No cases in {path}"
        raise ValueError(msg)
    cases: list[GroundTruthCase] = []
    for index, raw in enumerate(raw_cases):
        if not isinstance(raw, dict):
            msg = f"Case #{index} is not an object"
            raise ValueError(msg)
        try:
            cases.append(
                GroundTruthCase(
                    qid=str(raw["qid"]),
                    query=str(raw["query"]),
                    gold_targets=_parse_gold_targets(raw, case_label=f"Case #{index}"),
                    relevance_grades={
                        str(k): int(v) for k, v in (raw.get("relevance_grades") or {}).items()
                    },
                    tags=tuple(str(t) for t in raw.get("tags", [])),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            msg = f"Case #{index} ({raw.get('qid', '?')}) is malformed: {exc}"
            raise ValueError(msg) from exc
    qids = [case.qid for case in cases]
    if len(set(qids)) != len(qids):
        msg = "Duplicate qid found in ground-truth"
        raise ValueError(msg)
    return cases


def _parse_gold_targets(raw: dict[str, Any], *, case_label: str) -> tuple[GoldTarget, ...]:
    """Parse preferred multi-target labels and legacy single-target labels."""
    if "gold_targets" in raw:
        raw_targets = raw["gold_targets"]
        if not isinstance(raw_targets, list) or not raw_targets:
            msg = f"{case_label} gold_targets must be a non-empty list"
            raise ValueError(msg)
        return tuple(
            _parse_gold_target(target, case_label=f"{case_label} gold_targets[{i}]")
            for i, target in enumerate(raw_targets)
        )

    legacy = {
        "paper_id": raw["gold_paper_id"],
        "pages": raw.get("gold_pages", []),
        "chunk_ids": raw.get("gold_chunk_ids", []),
    }
    return (_parse_gold_target(legacy, case_label=f"{case_label} legacy gold"),)


def _parse_gold_target(raw: Any, *, case_label: str) -> GoldTarget:
    if not isinstance(raw, dict):
        msg = f"{case_label} must be an object"
        raise ValueError(msg)
    try:
        paper_id = str(raw["paper_id"]).strip()
        pages = tuple(int(p) for p in raw.get("pages", []))
        chunk_ids = tuple(str(c) for c in raw.get("chunk_ids", []))
    except (KeyError, TypeError, ValueError) as exc:
        msg = f"{case_label} is malformed: {exc}"
        raise ValueError(msg) from exc
    if not paper_id:
        msg = f"{case_label} paper_id must not be empty"
        raise ValueError(msg)
    if not pages and not chunk_ids:
        msg = f"{case_label} must include at least one page or chunk_id"
        raise ValueError(msg)
    return GoldTarget(paper_id=paper_id, pages=pages, chunk_ids=chunk_ids)


def chunk_matches(chunk: RetrievedChunk, case: GroundTruthCase) -> bool:
    for target in case.gold_targets:
        if target.chunk_ids and chunk.id in target.chunk_ids:
            return True
    page = chunk.metadata.get("page")
    if not isinstance(page, int):
        return False
    for target in case.gold_targets:
        if chunk.paper_id == target.paper_id and page in target.pages:
            return True
    return False


def _ndcg_grade(chunk: RetrievedChunk, case: GroundTruthCase) -> tuple[int, str | None]:
    """Return ``(grade, dedup_key)`` for nDCG using explicit relevance_grades only.

    An exact chunk-id annotation scores per chunk (dedup key = chunk id). A
    page-level annotation (``"<paper_id>:p<page>"``) scores once per page (dedup
    key = that page key) so that multiple retrieved chunks belonging to the same
    gold page are not double-counted. Chunks without an explicit grade return
    ``(0, None)``. nDCG deliberately ignores the binary hit fallback so the DCG
    and the IDCG (built from the same relevance_grades) stay on one scale.
    """
    if chunk.id in case.relevance_grades:
        return case.relevance_grades[chunk.id], chunk.id
    page = chunk.metadata.get("page")
    if isinstance(page, int):
        key = f"{chunk.paper_id}:p{page}"
        if key in case.relevance_grades:
            return case.relevance_grades[key], key
    return 0, None


def evaluate_case(
    retriever: SupportsSearch,
    case: GroundTruthCase,
    *,
    top_k: int,
    variants_by_query: Mapping[str, list[str]] | None = None,
    hyde_by_query: Mapping[str, list[str]] | None = None,
) -> CaseResult:
    retrieved = retriever.search(case.query, top_k=top_k)
    hit_ranks = [rank for rank, c in enumerate(retrieved, start=1) if chunk_matches(c, case)]
    first_hit = hit_ranks[0] if hit_ranks else None
    return CaseResult(
        case=case,
        hit_ranks=hit_ranks,
        first_hit_rank=first_hit,
        retrieved=retrieved,
        query_variants=(
            [] if variants_by_query is None else list(variants_by_query.get(case.query, []))
        ),
        hyde_documents=[] if hyde_by_query is None else list(hyde_by_query.get(case.query, [])),
    )


def recall_at_k(results: list[CaseResult], k: int) -> float:
    if not results:
        return 0.0
    hits = sum(1 for r in results if r.first_hit_rank is not None and r.first_hit_rank <= k)
    return hits / len(results)


def mrr_at_k(results: list[CaseResult], k: int) -> float:
    if not results:
        return 0.0
    total = 0.0
    for r in results:
        if r.first_hit_rank is not None and r.first_hit_rank <= k:
            total += 1.0 / r.first_hit_rank
    return total / len(results)


def ndcg_at_k(results: list[CaseResult], k: int) -> tuple[float, int]:
    """Return (mean_ndcg, n_cases_with_grades).

    Cases without ``relevance_grades`` are skipped — nDCG needs graded labels.
    """
    scored = 0
    total = 0.0
    for r in results:
        if not r.case.relevance_grades:
            continue
        scored += 1
        dcg = 0.0
        seen_keys: set[str] = set()
        for i, chunk in enumerate(r.retrieved[:k]):
            grade, key = _ndcg_grade(chunk, r.case)
            if key is not None:
                if key in seen_keys:
                    continue
                seen_keys.add(key)
            if grade <= 0:
                continue
            dcg += (2**grade - 1) / math.log2(i + 2)
        ideal_grades = sorted(r.case.relevance_grades.values(), reverse=True)[:k]
        idcg = sum((2**g - 1) / math.log2(i + 2) for i, g in enumerate(ideal_grades))
        total += dcg / idcg if idcg > 0 else 0.0
    mean = (total / scored) if scored else 0.0
    return mean, scored


def render_summary(
    *,
    results: list[CaseResult],
    metrics: set[str],
    k_recall: tuple[int, ...],
    k_mrr: int,
    k_ndcg: int,
    rerank_backend: str,
    reranker_model: str,
    multi_query_enabled: bool,
    multi_query_variants: int,
    hyde_enabled: bool,
    hyde_docs: int,
) -> None:
    multi_query_label = "on" if multi_query_enabled else "off"
    hyde_label = "on" if hyde_enabled else "off"
    console.rule(
        "[bold]Retrieval Evaluation[/]  "
        f"(rerank={rerank_backend}, model={reranker_model}, "
        f"multi_query={multi_query_label}, variants={multi_query_variants}, "
        f"hyde={hyde_label}, hyde_docs={hyde_docs}, n={len(results)})"
    )
    table = Table(show_header=True, header_style="bold")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_column("Coverage", justify="right")
    if "recall" in metrics:
        for k in k_recall:
            value = recall_at_k(results, k)
            table.add_row(f"Recall@{k}", f"{value:.4f}", f"{len(results)}/{len(results)}")
    if "mrr" in metrics:
        value = mrr_at_k(results, k_mrr)
        table.add_row(f"MRR@{k_mrr}", f"{value:.4f}", f"{len(results)}/{len(results)}")
    if "ndcg" in metrics:
        value, scored = ndcg_at_k(results, k_ndcg)
        coverage = f"{scored}/{len(results)}"
        suffix = "" if scored == len(results) else "  (some cases lack relevance_grades)"
        table.add_row(f"nDCG@{k_ndcg}", f"{value:.4f}", coverage + suffix)
    console.print(table)


def render_per_case(results: list[CaseResult], *, k_top: int) -> None:
    table = Table(show_header=True, header_style="bold", title="Per-case detail")
    table.add_column("qid")
    table.add_column("query", overflow="fold")
    table.add_column("gold")
    table.add_column("first_hit", justify="right")
    table.add_column(f"top-{k_top} retrieved (paper:p)", overflow="fold")
    for r in results:
        gold = _format_gold_targets(r.case.gold_targets)
        first = "miss" if r.first_hit_rank is None else f"#{r.first_hit_rank}"
        retrieved_summary = ", ".join(
            f"{c.paper_id}:p{c.metadata.get('page', '?')}" for c in r.retrieved[:k_top]
        )
        table.add_row(
            r.case.qid,
            (r.case.query[:60] + "…") if len(r.case.query) > 60 else r.case.query,
            gold,
            first,
            retrieved_summary or "(empty)",
        )
    console.print(table)


def _format_gold_targets(targets: tuple[GoldTarget, ...]) -> str:
    parts = []
    for target in targets:
        labels = []
        if target.pages:
            labels.append(f"p{list(target.pages)}")
        if target.chunk_ids:
            labels.append(f"chunks={len(target.chunk_ids)}")
        parts.append(f"{target.paper_id} {' '.join(labels)}".strip())
    return "; ".join(parts)


def write_json_report(
    path: Path,
    *,
    results: list[CaseResult],
    metrics: set[str],
    k_recall: tuple[int, ...],
    k_mrr: int,
    k_ndcg: int,
    rerank_backend: str,
    reranker_model: str,
    multi_query_enabled: bool,
    multi_query_variants: int,
    hyde_enabled: bool,
    hyde_docs: int,
) -> None:
    payload: dict[str, Any] = {
        "n_cases": len(results),
        "rerank_backend": rerank_backend,
        "reranker_model": reranker_model,
        "multi_query": {
            "enabled": multi_query_enabled,
            "variants": multi_query_variants,
        },
        "hyde": {
            "enabled": hyde_enabled,
            "docs": hyde_docs,
        },
        "metrics": {},
        "cases": [
            {
                "qid": r.case.qid,
                "query": r.case.query,
                "variants": r.query_variants,
                "hyde_documents": r.hyde_documents,
                "gold_targets": [
                    {
                        "paper_id": target.paper_id,
                        "pages": list(target.pages),
                        "chunk_ids": list(target.chunk_ids),
                    }
                    for target in r.case.gold_targets
                ],
                "first_hit_rank": r.first_hit_rank,
                "hit_ranks": r.hit_ranks,
                "retrieved": [
                    {
                        "paper_id": c.paper_id,
                        "page": c.metadata.get("page"),
                        "score": c.score,
                        "rerank_score": c.rerank_score,
                    }
                    for c in r.retrieved
                ],
            }
            for r in results
        ],
    }
    if "recall" in metrics:
        payload["metrics"]["recall"] = {f"@{k}": recall_at_k(results, k) for k in k_recall}
    if "mrr" in metrics:
        payload["metrics"]["mrr"] = {f"@{k_mrr}": mrr_at_k(results, k_mrr)}
    if "ndcg" in metrics:
        value, scored = ndcg_at_k(results, k_ndcg)
        payload["metrics"]["ndcg"] = {f"@{k_ndcg}": value, "scored_cases": scored}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    console.print(f"[dim]Wrote JSON report to {path}[/]")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Offline retrieval evaluation for the ResearchMate RAG pipeline.",
    )
    parser.add_argument(
        "--groundtruth",
        type=Path,
        default=DEFAULT_GROUNDTRUTH,
        help=f"Ground-truth JSON path (default: {DEFAULT_GROUNDTRUTH.relative_to(ROOT)}).",
    )
    parser.add_argument(
        "--metric",
        choices=["recall", "mrr", "ndcg", "all"],
        default="all",
        help="Which metric(s) to compute.",
    )
    parser.add_argument(
        "--k",
        type=int,
        help="K for the selected single metric (recall/mrr/ndcg). Ignored when --metric=all.",
    )
    parser.add_argument(
        "--top-k-retrieval",
        type=int,
        default=20,
        help="How many chunks to pull from the retriever per query (default: 20).",
    )
    query_mode = parser.add_mutually_exclusive_group()
    query_mode.add_argument(
        "--single-query",
        action="store_true",
        help="Force baseline single-query retrieval, ignoring RAG_MULTI_QUERY_ENABLED.",
    )
    query_mode.add_argument(
        "--multi-query",
        action="store_true",
        help="Force multi-query retrieval, ignoring RAG_MULTI_QUERY_ENABLED.",
    )
    parser.add_argument(
        "--variants",
        type=int,
        choices=range(1, 9),
        metavar="N",
        help="Number of query variants for multi-query retrieval (1-8).",
    )
    parser.add_argument(
        "--variants-cache",
        type=Path,
        default=DEFAULT_VARIANTS_CACHE,
        help=(
            "Query variants cache path " f"(default: {DEFAULT_VARIANTS_CACHE.relative_to(ROOT)})."
        ),
    )
    parser.add_argument(
        "--refresh-variants",
        action="store_true",
        help="Regenerate query variants and overwrite cache entries.",
    )
    hyde_mode = parser.add_mutually_exclusive_group()
    hyde_mode.add_argument(
        "--hyde",
        action="store_true",
        help="Force HyDE retrieval, ignoring RAG_HYDE_ENABLED.",
    )
    hyde_mode.add_argument(
        "--no-hyde",
        action="store_true",
        help="Disable HyDE retrieval, ignoring RAG_HYDE_ENABLED.",
    )
    parser.add_argument(
        "--hyde-docs",
        type=int,
        choices=range(1, 5),
        metavar="N",
        help="Number of HyDE documents per query (1-4).",
    )
    parser.add_argument(
        "--hyde-cache",
        type=Path,
        default=DEFAULT_HYDE_CACHE,
        help=f"HyDE documents cache path (default: {DEFAULT_HYDE_CACHE.relative_to(ROOT)}).",
    )
    parser.add_argument(
        "--refresh-hyde",
        action="store_true",
        help="Regenerate HyDE documents and overwrite cache entries.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print per-case retrieval detail.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        help="Optional JSON report output path.",
    )
    return parser


def resolve_k_values(args: argparse.Namespace) -> tuple[tuple[int, ...], int, int]:
    if args.metric == "all":
        return DEFAULT_K_RECALL, DEFAULT_K_MRR, DEFAULT_K_NDCG
    if args.k is None:
        defaults = {
            "recall": DEFAULT_K_RECALL,
            "mrr": (DEFAULT_K_MRR,),
            "ndcg": (DEFAULT_K_NDCG,),
        }
        ks = defaults[args.metric]
        return ks, ks[0], ks[0]
    return (args.k,), args.k, args.k


def resolve_multi_query_override(args: argparse.Namespace) -> bool | None:
    if args.single_query:
        return False
    if args.multi_query:
        return True
    return None


def resolve_hyde_override(args: argparse.Namespace) -> bool | None:
    if args.no_hyde:
        return False
    if args.hyde:
        return True
    return None


def main() -> int:
    args = build_parser().parse_args()
    cases = load_groundtruth(args.groundtruth)
    k_recall, k_mrr, k_ndcg = resolve_k_values(args)
    metrics = {"recall", "mrr", "ndcg"} if args.metric == "all" else {args.metric}

    settings = get_settings()
    if args.variants is not None:
        settings = settings.model_copy(update={"rag_multi_query_variants": args.variants})
    if args.hyde_docs is not None:
        settings = settings.model_copy(update={"rag_hyde_docs": args.hyde_docs})

    enabled_override = resolve_multi_query_override(args)
    hyde_override = resolve_hyde_override(args)
    multi_query_enabled = (
        settings.rag_multi_query_enabled if enabled_override is None else enabled_override
    )
    hyde_enabled = settings.rag_hyde_enabled if hyde_override is None else hyde_override
    multi_query_variants = settings.rag_multi_query_variants if multi_query_enabled else 0
    hyde_docs = settings.rag_hyde_docs if hyde_enabled else 0
    top_k = max(args.top_k_retrieval, max(*k_recall, k_mrr, k_ndcg))
    if multi_query_enabled and settings.rag_multi_query_pool_k < top_k:
        console.print(
            "[red]RAG_MULTI_QUERY_POOL_K must be >= the evaluation retrieval depth "
            f"({settings.rag_multi_query_pool_k} < {top_k}).[/]"
        )
        return 2
    if hyde_enabled and settings.rag_hyde_pool_k < top_k:
        console.print(
            "[red]RAG_HYDE_POOL_K must be >= the evaluation retrieval depth "
            f"({settings.rag_hyde_pool_k} < {top_k}).[/]"
        )
        return 2

    base_retriever = KnowledgeRetriever.from_settings(settings)
    rerank_backend = base_retriever.reranker.backend_name
    reranker_model = base_retriever.reranker.model_id
    variant_provider = (
        CachedVariantProvider(
            path=args.variants_cache,
            settings=settings,
            refresh=args.refresh_variants,
        )
        if multi_query_enabled
        else None
    )
    hyde_provider = (
        CachedHydeProvider(
            path=args.hyde_cache,
            settings=settings,
            refresh=args.refresh_hyde,
        )
        if hyde_enabled
        else None
    )
    retriever = build_query_retriever(
        base_retriever,
        settings,
        enabled=enabled_override,
        hyde_enabled=hyde_override,
        variant_provider=variant_provider,
        hyde_provider=hyde_provider,
    )

    results: list[CaseResult] = []
    try:
        for case in cases:
            results.append(
                evaluate_case(
                    retriever,
                    case,
                    top_k=top_k,
                    variants_by_query=None if variant_provider is None else variant_provider.used,
                    hyde_by_query=None if hyde_provider is None else hyde_provider.used,
                )
            )
    except QueryExpansionError as exc:
        console.print(f"[red]Query expansion failed:[/] {exc}")
        return 2

    render_summary(
        results=results,
        metrics=metrics,
        k_recall=k_recall,
        k_mrr=k_mrr,
        k_ndcg=k_ndcg,
        rerank_backend=rerank_backend,
        reranker_model=reranker_model,
        multi_query_enabled=multi_query_enabled,
        multi_query_variants=multi_query_variants,
        hyde_enabled=hyde_enabled,
        hyde_docs=hyde_docs,
    )
    if args.verbose:
        render_per_case(results, k_top=min(5, top_k))
    if args.report:
        write_json_report(
            args.report,
            results=results,
            metrics=metrics,
            k_recall=k_recall,
            k_mrr=k_mrr,
            k_ndcg=k_ndcg,
            rerank_backend=rerank_backend,
            reranker_model=reranker_model,
            multi_query_enabled=multi_query_enabled,
            multi_query_variants=multi_query_variants,
            hyde_enabled=hyde_enabled,
            hyde_docs=hyde_docs,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
