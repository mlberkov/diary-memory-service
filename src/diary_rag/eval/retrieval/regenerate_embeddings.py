"""Refresh ``eval/retrieval/embeddings_cache.json`` (D-038).

Operator-only ritual. Pins query embeddings to a specific
``text-embedding-3-large`` point-in-time output so the Postgres-mode
baseline run is reproducible across operator runs without contacting
OpenAI for the query side.

Regenerating invalidates prior baseline snapshots — the script refuses
to overwrite an existing cache file without ``--force``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from diary_rag.adapters.embeddings.factory import build_embedding_client
from diary_rag.config import Settings
from diary_rag.eval.retrieval.harness import load_gold

DEFAULT_GOLD = Path("eval/retrieval/gold.json")
DEFAULT_CACHE = Path("eval/retrieval/embeddings_cache.json")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m diary_rag.eval.retrieval.regenerate_embeddings",
    )
    p.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    p.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    p.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing cache file (invalidates prior baselines).",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.cache.exists() and not args.force:
        print(
            f"refusing to overwrite existing cache at {args.cache} — pass --force "
            f"to invalidate the prior baseline snapshot.",
            file=sys.stderr,
        )
        return 2

    if not os.environ.get("OPENAI_API_KEY"):
        print(
            "OPENAI_API_KEY is required to regenerate query embeddings.",
            file=sys.stderr,
        )
        return 2

    # Force the OpenAI backend regardless of the operator's local .env so
    # this script always pins against the canonical contour.
    settings = Settings(embedding_backend="openai")
    client = build_embedding_client(settings)

    gold = load_gold(args.gold)
    distinct_queries: list[str] = []
    seen: set[str] = set()
    for gq in gold.queries:
        if gq.query not in seen:
            distinct_queries.append(gq.query)
            seen.add(gq.query)

    vectors = client.embed(distinct_queries)
    embeddings = {q: v for q, v in zip(distinct_queries, vectors, strict=True)}

    payload = {
        "model_name": client.model_name,
        "dimension": client.dimension,
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "embeddings": embeddings,
    }
    args.cache.parent.mkdir(parents=True, exist_ok=True)
    args.cache.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        f"wrote {len(embeddings)} embeddings to {args.cache} "
        f"(model_name={client.model_name}, dimension={client.dimension})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
