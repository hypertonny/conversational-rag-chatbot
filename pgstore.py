"""
pgstore.py — Dedicated Postgres + pgvector store for the Unifier Hybrid RAG system.

Single transactional store holding BOTH the structured record copy (exact SQL for
counts/filters/aggregations) AND the embeddings (pgvector, for semantic/hybrid retrieval).
This removes the structured-vs-vector drift of the old two-store (SQLite + Chroma) design.

Phase 1 scope: connection pool, schema, and the structured data-access layer.
Embeddings columns/indexes are created now; the ingestion pipeline (Phase 2) fills them.
"""
import os
import json
import logging
import contextlib
from typing import Any, Dict, List, Optional

logger = logging.getLogger("PgStore")

EMBED_DIM = 384  # all-MiniLM-L6-v2

_pool = None


def dsn() -> str:
    return os.getenv("POSTGRES_DSN", "").strip()


def is_configured() -> bool:
    return bool(dsn())


class _Connector:
    """Lightweight connection factory with a .connection() context manager.
    Uses a fresh autocommit connection per operation — robust and simple. (A pool /
    pgbouncer is a Phase-5 scalability item; correctness first.)"""
    def __init__(self, conninfo: str):
        self._conninfo = conninfo

    @contextlib.contextmanager
    def connection(self):
        import psycopg
        conn = psycopg.connect(self._conninfo, autocommit=True, connect_timeout=10)
        try:
            yield conn
        finally:
            conn.close()


def get_pool():
    """Return the connection factory, or None if POSTGRES_DSN is unset."""
    global _pool
    if not is_configured():
        return None
    if _pool is None:
        _pool = _Connector(dsn())
    return _pool


_SCHEMA = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS projects (
    project_number TEXT PRIMARY KEY,
    project_name   TEXT,
    status         TEXT,
    project_type   TEXT,
    raw            JSONB NOT NULL DEFAULT '{}',
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS company_bps (
    bp_name       TEXT PRIMARY KEY,
    bp_model_name TEXT,
    studio_source TEXT,
    raw           JSONB NOT NULL DEFAULT '{}',
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS users (
    login       TEXT PRIMARY KEY,
    name        TEXT,
    first_name  TEXT,
    last_name   TEXT,
    email       TEXT,
    status      TEXT,
    raw         JSONB NOT NULL DEFAULT '{}',
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS records (
    id             TEXT PRIMARY KEY,
    scope_type     TEXT NOT NULL,
    project_number TEXT NOT NULL DEFAULT '',
    bp_name        TEXT NOT NULL,
    record_no      TEXT NOT NULL,
    title          TEXT,
    status         TEXT,
    creator        TEXT,
    assigned_to    TEXT,
    raw            JSONB NOT NULL DEFAULT '{}',
    content_hash   TEXT NOT NULL DEFAULT '',
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_records_proj_bp ON records (project_number, bp_name);
CREATE INDEX IF NOT EXISTS idx_records_bp      ON records (bp_name);
CREATE INDEX IF NOT EXISTS idx_records_status  ON records (status);

CREATE TABLE IF NOT EXISTS record_chunks (
    chunk_id       TEXT PRIMARY KEY,
    record_id      TEXT NOT NULL REFERENCES records(id) ON DELETE CASCADE,
    scope_type     TEXT,
    project_number TEXT,
    bp_name        TEXT,
    record_no      TEXT,
    content        TEXT NOT NULL,
    tsv            tsvector,
    embedding      vector(%(dim)s),
    content_hash   TEXT,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_chunks_proj_bp ON record_chunks (project_number, bp_name);
CREATE INDEX IF NOT EXISTS idx_chunks_tsv     ON record_chunks USING GIN (tsv);
CREATE INDEX IF NOT EXISTS idx_chunks_vec     ON record_chunks USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS ingest_state (
    key        TEXT PRIMARY KEY,
    watermark  TEXT,
    last_run   TIMESTAMPTZ,
    meta       JSONB NOT NULL DEFAULT '{}'
);
""" % {"dim": EMBED_DIM}


def ensure_schema() -> None:
    pool = get_pool()
    if pool is None:
        raise RuntimeError("POSTGRES_DSN is not configured.")
    with pool.connection() as conn:
        conn.execute(_SCHEMA)
    logger.info("pgstore schema ready (pgvector).")
# __APPEND__

# ── Structured filter builder (parameterized; mirrors retrieval.py semantics) ──
_FILTERABLE = {
    "project_number": "exact",
    "bp_name": "ilike",
    "record_no": "ilike",  # case-insensitive match for record numbers (e.g. rep-00030 matches REP-00030)
    "status": "ilike",
    "creator": "ilike",
    "assigned_to": "ilike",
    "title": "ilike",
    "keyword": "keyword",
}
_GROUPABLE = {"project_number", "bp_name", "status", "creator", "assigned_to"}


def _where(filters: Dict[str, str]):
    clauses, params = [], []
    for key, raw in (filters or {}).items():
        if key not in _FILTERABLE:
            continue
        val = (raw or "").strip()
        if not val:
            continue
        kind = _FILTERABLE[key]
        if kind == "exact":
            clauses.append(f"{key} = %s"); params.append(val)
        elif kind == "ilike":
            clauses.append(f"{key} ILIKE %s"); params.append(f"%{val}%")
        elif kind == "keyword":
            clauses.append("(title ILIKE %s OR raw::text ILIKE %s)"); params += [f"%{val}%", f"%{val}%"]
    return ((" AND " + " AND ".join(clauses)) if clauses else ""), params


def count_records(**filters: str) -> int:
    where, params = _where(filters)
    with get_pool().connection() as conn:
        row = conn.execute(f"SELECT COUNT(*) FROM records WHERE 1=1{where}", params).fetchone()
        return int(row[0]) if row else 0


def group_records(group_by: str, **filters: str) -> List[Dict[str, Any]]:
    if group_by not in _GROUPABLE:
        raise ValueError(f"group_by must be one of {sorted(_GROUPABLE)}")
    where, params = _where(filters)
    with get_pool().connection() as conn:
        rows = conn.execute(
            f"SELECT {group_by} AS value, COUNT(*) AS record_count FROM records WHERE 1=1{where} "
            f"GROUP BY {group_by} ORDER BY record_count DESC", params
        ).fetchall()
        return [{"value": r[0], "record_count": int(r[1])} for r in rows]


def list_records(limit: int = 25, offset: int = 0, **filters: str) -> Dict[str, Any]:
    where, params = _where(filters)
    with get_pool().connection() as conn:
        total = int(conn.execute(f"SELECT COUNT(*) FROM records WHERE 1=1{where}", params).fetchone()[0])
        rows = conn.execute(
            "SELECT project_number, bp_name, record_no, title, status, creator, assigned_to "
            f"FROM records WHERE 1=1{where} ORDER BY project_number, bp_name, record_no LIMIT %s OFFSET %s",
            [*params, max(1, int(limit)), max(0, int(offset))]
        ).fetchall()
        cols = ["project_number", "bp_name", "record_no", "title", "status", "creator", "assigned_to"]
        return {"total": total, "offset": offset, "rows": [dict(zip(cols, r)) for r in rows]}


def distinct_values(field: str, **filters: str) -> List[str]:
    if field not in _GROUPABLE:
        raise ValueError(f"field must be one of {sorted(_GROUPABLE)}")
    where, params = _where(filters)
    with get_pool().connection() as conn:
        rows = conn.execute(
            f"SELECT DISTINCT {field} AS v FROM records WHERE {field} <> '' AND {field} IS NOT NULL{where} ORDER BY {field}",
            params
        ).fetchall()
        return [r[0] for r in rows]


def find_projects(query: str, limit: int = 10) -> Dict[str, Any]:
    q = (query or "").strip()
    with get_pool().connection() as conn:
        exact = conn.execute(
            "SELECT project_number, project_name, status, project_type FROM projects WHERE project_number = %s", (q,)
        ).fetchone()
        cands = conn.execute(
            "SELECT project_number, project_name, status, project_type FROM projects "
            "WHERE project_number = %s OR project_name ILIKE %s "
            "ORDER BY (project_number = %s) DESC, project_number LIMIT %s",
            (q, f"%{q}%", q, int(limit))
        ).fetchall()
        cols = ["project_number", "project_name", "status", "project_type"]
        return {
            "exact": dict(zip(cols, exact)) if exact else None,
            "candidates": [dict(zip(cols, r)) for r in cands],
        }


def is_company_bp(bpname: str) -> bool:
    if not bpname:
        return False
    with get_pool().connection() as conn:
        return conn.execute("SELECT 1 FROM company_bps WHERE LOWER(bp_name)=LOWER(%s) LIMIT 1", (bpname.strip(),)).fetchone() is not None


def stats() -> Dict[str, int]:
    with get_pool().connection() as conn:
        g = lambda sql: int(conn.execute(sql).fetchone()[0])
        return {
            "projects": g("SELECT COUNT(*) FROM projects"),
            "company_bps": g("SELECT COUNT(*) FROM company_bps"),
            "records": g("SELECT COUNT(*) FROM records"),
            "users": g("SELECT COUNT(*) FROM users"),
            "embeddings": g("SELECT COUNT(*) FROM record_chunks WHERE embedding IS NOT NULL"),
        }
# __APPEND2__

import hashlib


def content_hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode("utf-8")).hexdigest()


# ── Upserts (idempotent; used by backfill + the Phase-2 ingestion pipeline) ──
def upsert_project(p: Dict[str, Any]) -> None:
    with get_pool().connection() as conn:
        conn.execute(
            "INSERT INTO projects (project_number, project_name, status, project_type, raw, updated_at) "
            "VALUES (%s,%s,%s,%s,%s, now()) ON CONFLICT (project_number) DO UPDATE SET "
            "project_name=EXCLUDED.project_name, status=EXCLUDED.status, project_type=EXCLUDED.project_type, raw=EXCLUDED.raw, updated_at=now()",
            (p["project_number"], p.get("project_name"), p.get("status"), p.get("project_type"), json.dumps(p.get("raw", {})))
        )


def upsert_company_bp(b: Dict[str, Any]) -> None:
    with get_pool().connection() as conn:
        conn.execute(
            "INSERT INTO company_bps (bp_name, bp_model_name, studio_source, raw, updated_at) "
            "VALUES (%s,%s,%s,%s, now()) ON CONFLICT (bp_name) DO UPDATE SET "
            "bp_model_name=EXCLUDED.bp_model_name, studio_source=EXCLUDED.studio_source, raw=EXCLUDED.raw, updated_at=now()",
            (b["bp_name"], b.get("bp_model_name"), b.get("studio_source"), json.dumps(b.get("raw", {})))
        )


def upsert_user(u: Dict[str, Any]) -> None:
    with get_pool().connection() as conn:
        conn.execute(
            "INSERT INTO users (login, name, first_name, last_name, email, status, raw, updated_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s, now()) ON CONFLICT (login) DO UPDATE SET "
            "name=EXCLUDED.name, first_name=EXCLUDED.first_name, last_name=EXCLUDED.last_name, "
            "email=EXCLUDED.email, status=EXCLUDED.status, raw=EXCLUDED.raw, updated_at=now()",
            (u["login"], u.get("name"), u.get("first_name"), u.get("last_name"), u.get("email"), u.get("status"), json.dumps(u.get("raw", {})))
        )


def upsert_record(rec: Dict[str, Any]) -> bool:
    """Insert/update a record. Returns True if content changed (needs re-embedding)."""
    rid = rec["id"]
    chash = rec.get("content_hash") or content_hash(rec.get("raw", {}))
    with get_pool().connection() as conn:
        existing = conn.execute("SELECT content_hash FROM records WHERE id=%s", (rid,)).fetchone()
        if existing and existing[0] == chash:
            return False  # unchanged → skip re-embed (incremental CDC)
        conn.execute(
            "INSERT INTO records (id, scope_type, project_number, bp_name, record_no, title, status, creator, assigned_to, raw, content_hash, updated_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, now()) ON CONFLICT (id) DO UPDATE SET "
            "scope_type=EXCLUDED.scope_type, project_number=EXCLUDED.project_number, bp_name=EXCLUDED.bp_name, "
            "record_no=EXCLUDED.record_no, title=EXCLUDED.title, status=EXCLUDED.status, creator=EXCLUDED.creator, "
            "assigned_to=EXCLUDED.assigned_to, raw=EXCLUDED.raw, content_hash=EXCLUDED.content_hash, updated_at=now()",
            (rid, rec.get("scope_type", ""), rec.get("project_number", ""), rec.get("bp_name", ""), rec.get("record_no", ""),
             rec.get("title"), rec.get("status"), rec.get("creator"), rec.get("assigned_to"),
             json.dumps(rec.get("raw", {})), chash)
        )
        return True


def upsert_chunk(chunk_id: str, record_id: str, meta: Dict[str, Any], content: str,
                 embedding: List[float], chash: str = "") -> None:
    from pgvector.psycopg import register_vector
    with get_pool().connection() as conn:
        register_vector(conn)
        conn.execute(
            "INSERT INTO record_chunks (chunk_id, record_id, scope_type, project_number, bp_name, record_no, content, tsv, embedding, content_hash, updated_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s, to_tsvector('english', %s), %s, %s, now()) "
            "ON CONFLICT (chunk_id) DO UPDATE SET content=EXCLUDED.content, tsv=EXCLUDED.tsv, "
            "embedding=EXCLUDED.embedding, content_hash=EXCLUDED.content_hash, updated_at=now()",
            (chunk_id, record_id, meta.get("scope_type"), meta.get("project_number"), meta.get("bp_name"),
             meta.get("record_no"), content, content, embedding, chash)
        )


def records_to_embed(project_number: str = "", only_changed: bool = True, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Return records that need (re-)embedding (CDC).

    A record needs embedding when it has NO chunk whose content_hash matches the
    record's current content_hash — i.e. a brand-new record, or one whose raw
    content changed since it was last embedded. With ``only_changed=False`` every
    record is returned (full re-embed)."""
    cols = ["id", "scope_type", "project_number", "bp_name", "record_no", "title",
            "status", "creator", "assigned_to", "raw", "content_hash"]
    sql = f"SELECT {', '.join('r.' + c for c in cols)} FROM records r"
    params: List[Any] = []
    if only_changed:
        sql += (" WHERE NOT EXISTS (SELECT 1 FROM record_chunks c "
                "WHERE c.record_id = r.id AND c.content_hash = r.content_hash)")
    if project_number:
        sql += (" AND" if only_changed else " WHERE") + " r.project_number = %s"
        params.append(project_number)
    sql += " ORDER BY r.project_number, r.bp_name, r.record_no"
    if limit:
        sql += " LIMIT %s"; params.append(int(limit))
    with get_pool().connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    out = []
    for r in rows:
        d = dict(zip(cols, r))
        raw = d.get("raw")
        d["raw"] = raw if isinstance(raw, dict) else (json.loads(raw) if raw else {})
        out.append(d)
    return out


def upsert_chunks_batch(rows: List[Dict[str, Any]]) -> int:
    """Bulk insert/update chunks in ONE connection (fast path for ingestion).

    Each row dict: chunk_id, record_id, scope_type, project_number, bp_name,
    record_no, content, content_hash, embedding (list[float])."""
    if not rows:
        return 0
    from pgvector.psycopg import register_vector
    sql = ("INSERT INTO record_chunks (chunk_id, record_id, scope_type, project_number, bp_name, record_no, content, tsv, embedding, content_hash, updated_at) "
           "VALUES (%s,%s,%s,%s,%s,%s,%s, to_tsvector('english', %s), %s, %s, now()) "
           "ON CONFLICT (chunk_id) DO UPDATE SET content=EXCLUDED.content, tsv=EXCLUDED.tsv, "
           "embedding=EXCLUDED.embedding, content_hash=EXCLUDED.content_hash, updated_at=now()")
    payload = [
        (r["chunk_id"], r["record_id"], r.get("scope_type"), r.get("project_number"), r.get("bp_name"),
         r.get("record_no"), r["content"], r["content"], r["embedding"], r.get("content_hash", ""))
        for r in rows
    ]
    with get_pool().connection() as conn:
        register_vector(conn)
        conn.cursor().executemany(sql, payload)
    return len(rows)


def set_ingest_state(key: str, watermark: str = "", meta: Optional[Dict[str, Any]] = None) -> None:
    with get_pool().connection() as conn:
        conn.execute(
            "INSERT INTO ingest_state (key, watermark, last_run, meta) VALUES (%s,%s, now(), %s) "
            "ON CONFLICT (key) DO UPDATE SET watermark=EXCLUDED.watermark, last_run=now(), meta=EXCLUDED.meta",
            (key, watermark, json.dumps(meta or {}))
        )


def get_ingest_state(key: str) -> Optional[Dict[str, Any]]:
    with get_pool().connection() as conn:
        row = conn.execute("SELECT key, watermark, last_run, meta FROM ingest_state WHERE key=%s", (key,)).fetchone()
        if not row:
            return None
        return {"key": row[0], "watermark": row[1], "last_run": row[2], "meta": row[3]}


# ── Currency-safe aggregation (EXACT; never sums across currencies) ──
_NUMERIC_RE = r'^-?[0-9]+(\.[0-9]+)?$'


def aggregate_amounts(amount_field: str = "amount", currency_field: str = "currencyid", **filters: str) -> List[Dict[str, Any]]:
    """Sum a numeric record field grouped by currency — NEVER across currencies.

    Reads the value verbatim from records.raw JSONB (e.g. raw->>'amount') and the
    currency label from raw->>'currencyid' ('United States Dollar (USD)', etc.).
    Rows whose amount is missing/non-numeric are counted separately under
    'non_numeric' so nothing is silently dropped or coerced. Returns one row per
    currency: {currency, record_count, total}. The caller must present each
    currency separately and state the currency filter."""
    # amount_field/currency_field are identifiers from a fixed allowlist to keep SQL safe.
    if not amount_field.replace("_", "").isalnum() or not currency_field.replace("_", "").isalnum():
        raise ValueError("invalid field name")
    where, params = _where(filters)
    amt = f"raw->>'{amount_field}'"
    cur = f"COALESCE(NULLIF(raw->>'{currency_field}', ''), '(no currency)')"
    with get_pool().connection() as conn:
        rows = conn.execute(
            f"SELECT {cur} AS currency, COUNT(*) AS n, "
            f"       SUM(CASE WHEN {amt} ~ %s THEN ({amt})::numeric ELSE 0 END) AS total, "
            f"       SUM(CASE WHEN {amt} ~ %s THEN 0 ELSE 1 END) AS non_numeric "
            f"FROM records WHERE 1=1{where} GROUP BY {cur} ORDER BY total DESC NULLS LAST",
            [_NUMERIC_RE, _NUMERIC_RE, *params]
        ).fetchall()
        out = []
        for r in rows:
            out.append({
                "currency": r[0],
                "record_count": int(r[1]),
                "total": float(r[2]) if r[2] is not None else 0.0,
                "non_numeric_rows": int(r[3]),
            })
        return out


# ── Semantic + hybrid retrieval (Phase 3 wires these into the agent) ──
def _vec_literal(embedding: List[float]) -> str:
    """pgvector text input format: '[0.1,0.2,...]'. Combined with a %s::vector cast
    this is adaptation-independent (works whether or not register_vector ran)."""
    return "[" + ",".join(repr(float(x)) for x in embedding) + "]"


def semantic_search(embedding: List[float], project_number: str = "", bp_name: str = "", k: int = 8) -> List[Dict[str, Any]]:
    vec = _vec_literal(embedding)
    where, params = [], []
    if project_number:
        where.append("project_number = %s"); params.append(project_number)
    if bp_name:
        where.append("bp_name ILIKE %s"); params.append(f"%{bp_name}%")
    wsql = (" WHERE " + " AND ".join(where)) if where else ""
    with get_pool().connection() as conn:
        rows = conn.execute(
            f"SELECT record_no, bp_name, project_number, content, 1 - (embedding <=> %s::vector) AS score "
            f"FROM record_chunks{wsql} ORDER BY embedding <=> %s::vector LIMIT %s",
            [vec, *params, vec, int(k)]
        ).fetchall()
        cols = ["record_no", "bp_name", "project_number", "content", "score"]
        return [dict(zip(cols, r)) for r in rows]


def hybrid_search(query_text: str, embedding: List[float], project_number: str = "", bp_name: str = "", k: int = 8) -> List[Dict[str, Any]]:
    """Reciprocal-rank fusion of dense (vector) + sparse (tsvector) results."""
    q = (query_text or "").strip()
    if not q:
        return semantic_search(embedding, project_number=project_number, bp_name=bp_name, k=k)
    vec = _vec_literal(embedding)
    where, params = [], []
    if project_number:
        where.append("project_number = %s"); params.append(project_number)
    if bp_name:
        where.append("bp_name ILIKE %s"); params.append(f"%{bp_name}%")
    wsql = (" AND " + " AND ".join(where)) if where else ""
    try:
        with get_pool().connection() as conn:
            sql = f"""
            WITH dense AS (
              SELECT chunk_id, record_no, bp_name, project_number, content,
                     ROW_NUMBER() OVER (ORDER BY embedding <=> %s::vector) AS rnk
              FROM record_chunks WHERE 1=1{wsql} ORDER BY embedding <=> %s::vector LIMIT 40
            ), sparse AS (
              SELECT chunk_id, record_no, bp_name, project_number, content,
                     ROW_NUMBER() OVER (ORDER BY ts_rank(tsv, plainto_tsquery('english', %s)) DESC) AS rnk
              FROM record_chunks WHERE tsv @@ plainto_tsquery('english', %s){wsql} LIMIT 40
            )
            SELECT COALESCE(d.record_no,s.record_no) record_no, COALESCE(d.bp_name,s.bp_name) bp_name,
                   COALESCE(d.project_number,s.project_number) project_number, COALESCE(d.content,s.content) content,
                   (COALESCE(1.0/(60+d.rnk),0) + COALESCE(1.0/(60+s.rnk),0)) AS rrf
            FROM dense d FULL OUTER JOIN sparse s USING (chunk_id)
            ORDER BY rrf DESC LIMIT %s
            """
            args = [vec, *params, vec, q, q, *params, int(k)]
            rows = conn.execute(sql, args).fetchall()
            cols = ["record_no", "bp_name", "project_number", "content", "rrf"]
            return [dict(zip(cols, r)) for r in rows]
    except Exception:
        # Sparse query can fail on odd input — degrade to dense-only rather than erroring.
        return semantic_search(embedding, project_number=project_number, bp_name=bp_name, k=k)
# __APPEND3__

def backfill_from_sqlite(sqlite_path: str = "data/unifier_cache.db") -> Dict[str, int]:
    """One-time structured backfill from the legacy SQLite cache into Postgres.
    Copies projects, company BPs, users, and records (no embeddings — that's Phase 2).
    Uses ONE connection + batched executemany for speed (bulk, not per-row)."""
    import sqlite3
    ensure_schema()
    s = sqlite3.connect(sqlite_path)
    s.row_factory = sqlite3.Row
    counts = {"projects": 0, "company_bps": 0, "users": 0, "records": 0}
    BATCH = 1000
    try:
        with get_pool().connection() as conn:
            cur = conn.cursor()

            def flush(sql, rows):
                if rows:
                    cur.executemany(sql, rows)

            # Projects
            sql_p = ("INSERT INTO projects (project_number, project_name, status, project_type, raw, updated_at) "
                     "VALUES (%s,%s,%s,%s,%s, now()) ON CONFLICT (project_number) DO UPDATE SET "
                     "project_name=EXCLUDED.project_name, status=EXCLUDED.status, project_type=EXCLUDED.project_type, raw=EXCLUDED.raw, updated_at=now()")
            batch = []
            for r in s.execute("SELECT * FROM cached_projects"):
                batch.append((r["project_number"], r["project_name"], r["status"], r["project_type"], r["raw_json"] or "{}"))
                if len(batch) >= BATCH:
                    flush(sql_p, batch); counts["projects"] += len(batch); batch = []
            flush(sql_p, batch); counts["projects"] += len(batch)

            # Company BPs
            sql_b = ("INSERT INTO company_bps (bp_name, bp_model_name, studio_source, raw, updated_at) "
                     "VALUES (%s,%s,%s,'{}', now()) ON CONFLICT (bp_name) DO UPDATE SET "
                     "bp_model_name=EXCLUDED.bp_model_name, studio_source=EXCLUDED.studio_source, updated_at=now()")
            cur.executemany(sql_b, [(r["bp_name"], r["bp_model_name"], r["studio_source"]) for r in s.execute("SELECT * FROM cached_company_bps")])
            counts["company_bps"] = cur.rowcount if cur.rowcount and cur.rowcount > 0 else counts["company_bps"]

            # Users
            sql_u = ("INSERT INTO users (login, name, first_name, last_name, email, status, raw, updated_at) "
                     "VALUES (%s,%s,%s,%s,%s,%s,'{}', now()) ON CONFLICT (login) DO UPDATE SET "
                     "name=EXCLUDED.name, first_name=EXCLUDED.first_name, last_name=EXCLUDED.last_name, email=EXCLUDED.email, status=EXCLUDED.status, updated_at=now()")
            urows = [(r["user_name"], f"{r['first_name']} {r['last_name']}".strip() or r["user_name"], r["first_name"], r["last_name"], r["email"], r["status"]) for r in s.execute("SELECT * FROM cached_users")]
            cur.executemany(sql_u, urows); counts["users"] = len(urows)

            # Records (with content hash for CDC)
            sql_r = ("INSERT INTO records (id, scope_type, project_number, bp_name, record_no, title, status, creator, assigned_to, raw, content_hash, updated_at) "
                     "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, now()) ON CONFLICT (id) DO UPDATE SET "
                     "scope_type=EXCLUDED.scope_type, project_number=EXCLUDED.project_number, bp_name=EXCLUDED.bp_name, record_no=EXCLUDED.record_no, "
                     "title=EXCLUDED.title, status=EXCLUDED.status, creator=EXCLUDED.creator, assigned_to=EXCLUDED.assigned_to, raw=EXCLUDED.raw, content_hash=EXCLUDED.content_hash, updated_at=now()")
            batch = []
            for r in s.execute("SELECT * FROM cached_bp_records"):
                raw = r["raw_json"] or "{}"
                batch.append((r["id"], r["scope_type"], r["project_number"] or "", r["bp_name"], r["record_no"],
                              r["title"], r["status"], r["creator"], r["assigned_to"], raw,
                              hashlib.sha256(raw.encode("utf-8")).hexdigest()))
                if len(batch) >= BATCH:
                    flush(sql_r, batch); counts["records"] += len(batch); batch = []
            flush(sql_r, batch); counts["records"] += len(batch)

        return counts
    finally:
        s.close()


# ── Breakdown / cross-project listing (single-source: same store as the counts) ──
def records_status_summary(bp_name: str = "", project_number: str = "") -> List[Dict[str, Any]]:
    """BP x status record-count breakdown. Same store/semantics as count_records so the
    big breakdown can never disagree with a targeted count."""
    where, params = _where({"bp_name": bp_name, "project_number": project_number})
    with get_pool().connection() as conn:
        rows = conn.execute(
            f"SELECT bp_name, status, COUNT(*) AS record_count FROM records WHERE 1=1{where} "
            f"GROUP BY bp_name, status ORDER BY bp_name, record_count DESC", params
        ).fetchall()
        return [{"bp_name": r[0], "status": r[1], "record_count": int(r[2])} for r in rows]


def records_cross_project(status: str = "", bp_name: str = "", assigned_to: str = "",
                          keyword: str = "", project_number: str = "", limit: int = 50) -> List[Dict[str, Any]]:
    """Capped example rows across all projects/BPs (NOT a count — use count_records for totals)."""
    where, params = _where({"status": status, "bp_name": bp_name, "assigned_to": assigned_to,
                            "keyword": keyword, "project_number": project_number})
    with get_pool().connection() as conn:
        rows = conn.execute(
            "SELECT project_number, bp_name, record_no, title, status, assigned_to "
            f"FROM records WHERE 1=1{where} ORDER BY project_number, bp_name, record_no LIMIT %s",
            [*params, max(1, int(limit))]
        ).fetchall()
        cols = ["project_number", "bp_name", "record_no", "title", "status", "assigned_to"]
        return [dict(zip(cols, r)) for r in rows]


def distinct_bp_matches(bp_name: str, project_number: str = "", **filters: str) -> List[Dict[str, Any]]:
    """Which distinct BPs a bp_name filter actually matches (+counts). Used to disclose
    when a loose term like 'change order' spans several BPs (Change Order vs Potential Change Order)."""
    f = {"bp_name": bp_name, "project_number": project_number, **filters}
    where, params = _where(f)
    with get_pool().connection() as conn:
        rows = conn.execute(
            f"SELECT bp_name, COUNT(*) FROM records WHERE 1=1{where} GROUP BY bp_name ORDER BY COUNT(*) DESC", params
        ).fetchall()
        return [{"bp_name": r[0], "record_count": int(r[1])} for r in rows]



