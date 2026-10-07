"""Sync the knowledge index with the corpus files (idempotent). Prints COUNTS only.

Usage: python -m app.rag_ingest [--dir PATH]
Needs OPENROUTER_API_KEY (embeddings). Never prints the key, embeddings or document text.
"""
import argparse
import json
import sys
from pathlib import Path

from app import rag
from app.config import load_settings
from app.db import connect


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Ingest knowledge/*.md into pgvector")
    parser.add_argument("--dir", help="corpus directory (default: RAG_KNOWLEDGE_DIR)")
    args = parser.parse_args(argv)
    settings = load_settings()
    provider = rag.provider_from_settings(settings)
    if provider is None:
        print("rag_ingest: OPENROUTER_API_KEY is not configured", file=sys.stderr)
        return 2
    directory = Path(args.dir or settings.rag_knowledge_dir)
    try:
        with connect(settings, autocommit=True) as conn:
            report = rag.ingest(conn, provider, directory)
    except rag.RagError as exc:
        print(f"rag_ingest failed: {exc.code}: {exc}", file=sys.stderr)
        return 1
    print("rag_ingest " + json.dumps({"model": provider.model, **report.as_dict()}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
