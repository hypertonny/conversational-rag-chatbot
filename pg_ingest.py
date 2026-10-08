"""
pg_ingest.py — Phase 2: batch embedding ingestion + CDC into Postgres/pgvector.

Pipeline per record:  records(raw) → canonicalize to text → embed (all-MiniLM-L6-v2,
384-dim) → upsert into record_chunks (vector + tsvector) with the record's
content_hash. Incremental by default: only records whose content changed (or were
never embedded) are re-processed, so re-runs are cheap (CDC via content_hash).

Usage:
    python pg_ingest.py                 # embed everything that needs it
    python pg_ingest.py --project 001   # only one project
    python pg_ingest.py --all           # force full re-embed
"""
import os
import logging
import argparse
from typing import Dict, List, Optional, Callable

import pgstore
from record_utils import format_record_text

logger = logging.getLogger("PgIngest")

_EMBEDDER = None
_MODEL_NAME = os.getenv("EMBED_MODEL", "all-MiniLM-L6-v2")


def get_embedder():
    """Load the SentenceTransformer once (same model as the legacy Chroma store)."""
    global _EMBEDDER
    if _EMBEDDER is None:
        from sentence_transformers import SentenceTransformer
        logger.info("Loading embedding model %s ...", _MODEL_NAME)
        _EMBEDDER = SentenceTransformer(_MODEL_NAME)
    return _EMBEDDER


def record_to_text(rec: Dict) -> str:
    """Build embedding-friendly text for a record.

    Lead with the high-signal identity fields (so they survive the model's token
    window) then append the flattened raw scalar fields.
    """
    head_bits = []
    for key in ("record_no", "bp_name", "title", "status", "project_number", "creator", "assigned_to"):
        v = rec.get(key)
        if v:
            head_bits.append(f"{key}: {v}")
    head = " | ".join(head_bits)
    body = format_record_text(rec.get("raw") or {})
    text = (head + " | " + body) if body else head
    return text.strip() or (rec.get("record_no") or rec.get("id") or "")


def _embed_texts(texts: List[str]) -> List[List[float]]:
    model = get_embedder()
    vecs = model.encode(texts, batch_size=64, show_progress_bar=False, normalize_embeddings=False)
    return [v.tolist() for v in vecs]


def run_ingest(
    project_number: str = "",
    only_changed: bool = True,
    batch: int = 256,
    progress: Optional[Callable[[int, int], None]] = None,
) -> Dict[str, int]:
    """Embed records needing it and upsert their chunks. Returns a stats dict."""
    if not pgstore.is_configured():
        raise RuntimeError("POSTGRES_DSN is not configured.")
    pgstore.ensure_schema()

    pending = pgstore.records_to_embed(project_number=project_number, only_changed=only_changed)
    total = len(pending)
    logger.info("Records needing embedding: %d (project=%s, only_changed=%s)", total, project_number or "ALL", only_changed)
    done = 0
    for i in range(0, total, batch):
        slice_ = pending[i:i + batch]
        texts = [record_to_text(r) for r in slice_]
        vecs = _embed_texts(texts)
        rows = []
        for r, text, vec in zip(slice_, texts, vecs):
            rid = r["id"]
            rows.append({
                "chunk_id": f"{rid}#0",
                "record_id": rid,
                "scope_type": r.get("scope_type"),
                "project_number": r.get("project_number"),
                "bp_name": r.get("bp_name"),
                "record_no": r.get("record_no"),
                "content": text,
                "content_hash": r.get("content_hash", ""),
                "embedding": vec,
            })
        pgstore.upsert_chunks_batch(rows)
        done += len(slice_)
        if progress:
            progress(done, total)
        logger.info("Embedded %d/%d", done, total)

    emb = pgstore.stats().get("embeddings", 0)
    pgstore.set_ingest_state(
        key=f"embed:{project_number or 'ALL'}",
        watermark=str(emb),
        meta={"embedded_this_run": done, "total_embeddings": emb, "only_changed": only_changed},
    )
    return {"pending": total, "embedded": done, "total_embeddings": emb}


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    ap = argparse.ArgumentParser(description="Embed Unifier records into Postgres/pgvector.")
    ap.add_argument("--project", default="", help="Only embed this project_number (exact).")
    ap.add_argument("--all", action="store_true", help="Force full re-embed (ignore content_hash).")
    ap.add_argument("--batch", type=int, default=256)
    args = ap.parse_args()
    stats = run_ingest(project_number=args.project, only_changed=not args.all, batch=args.batch)
    print(f"Ingest complete: {stats}")


if __name__ == "__main__":
    main()
