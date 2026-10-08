"""
retrieval.py — Curated structured (SQL) + semantic retrieval.

Backend-switched: when ``POSTGRES_DSN`` is configured the structured queries and
semantic/hybrid search run against the dedicated Postgres + pgvector store
(``pgstore``) — one consistent transactional store, exact SQL for
counts/filters/aggregations, and dense+sparse hybrid retrieval for fuzzy / "why"
questions. When Postgres is NOT configured it transparently falls back to the
legacy SQLite cache + ChromaDB, so existing deployments and the test suite keep
working unchanged.

All SQL is parameterized. Filters map to columns on the records table:
    project_number, bp_name, record_no, title, status, creator, assigned_to, raw(_json)
"""
from typing import Any, Dict, List, Optional

import pgstore

# Reuse the single DB/vector accessors from sync_manager (no duplicate connections).
# These SQLite-backed helpers are the FALLBACK when Postgres isn't configured.
from sync_manager import (
    get_db_connection,
    query_vector_search,
    query_records_cross_project as _sqlite_cross_project,
    query_records_status_summary as _sqlite_status_summary,
)


def query_records_cross_project(status: str = "", bp_name: str = "", assigned_to: str = "",
                                keyword: str = "", project_number: str = "", limit: int = 50):
    """Capped example rows across projects/BPs. Postgres when configured (same store as the
    counts), else the SQLite cache."""
    if _use_pg():
        return pgstore.records_cross_project(status=status, bp_name=bp_name, assigned_to=assigned_to,
                                             keyword=keyword, project_number=project_number, limit=limit)
    return _sqlite_cross_project(status=status, bp_name=bp_name, assigned_to=assigned_to,
                                 keyword=keyword, project_number=project_number, limit=limit)


def query_records_status_summary(bp_name: str = "", project_number: str = ""):
    """BP x status breakdown. Postgres when configured so it can NEVER disagree with
    count_records; else the SQLite cache."""
    if _use_pg():
        return pgstore.records_status_summary(bp_name=bp_name, project_number=project_number)
    return _sqlite_status_summary(bp_name=bp_name, project_number=project_number)


def _use_pg() -> bool:
    """True when the Postgres+pgvector store is configured (checked live, so the
    env var may be set after import — and tests without it use SQLite)."""
    return pgstore.is_configured()


_PG_EMBEDDER = None


def _embed_query(text: str) -> Optional[List[float]]:
    """Embed a query with the same model used for ingestion (all-MiniLM-L6-v2).
    Returns None if the embedder can't load (so semantic search degrades, never crashes)."""
    global _PG_EMBEDDER
    try:
        if _PG_EMBEDDER is None:
            from pg_ingest import get_embedder
            _PG_EMBEDDER = get_embedder()
        return _PG_EMBEDDER.encode([text])[0].tolist()
    except Exception:
        return None



# Columns a caller may filter on. Anything else is rejected to keep SQL safe/predictable.
_FILTERABLE = {
    "project_number": "exact",
    "bp_name": "like",
    "record_no": "like",
    "status": "like",
    "creator": "like",
    "assigned_to": "like",
    "title": "like",
    "keyword": "keyword",   # matches title OR raw_json
}

# Columns that may be grouped on / selected as distinct values.
_GROUPABLE = {"project_number", "bp_name", "status", "creator", "assigned_to"}


def _build_where(filters: Dict[str, str]):
    """Return (where_sql, params) for the supported filters, ignoring blanks."""
    clauses: List[str] = []
    params: List[Any] = []
    for key, raw in (filters or {}).items():
        if key not in _FILTERABLE:
            continue
        val = (raw or "").strip()
        if not val:
            continue
        kind = _FILTERABLE[key]
        if kind == "exact":
            clauses.append(f"{key} = ?")
            params.append(val)
        elif kind == "like":
            clauses.append(f"{key} LIKE ?")
            params.append(f"%{val}%")
        elif kind == "keyword":
            clauses.append("(title LIKE ? OR raw_json LIKE ?)")
            params.extend([f"%{val}%", f"%{val}%"])
    where_sql = (" AND " + " AND ".join(clauses)) if clauses else ""
    return where_sql, params


def count_records(**filters: str) -> int:
    """Exact count of BP records matching the given filters."""
    if _use_pg():
        return pgstore.count_records(**filters)
    where_sql, params = _build_where(filters)
    conn = get_db_connection()
    try:
        row = conn.execute(
            f"SELECT COUNT(*) FROM cached_bp_records WHERE 1=1{where_sql}", params
        ).fetchone()
        return int(row[0]) if row else 0
    finally:
        conn.close()


def group_records(group_by: str, **filters: str) -> List[Dict[str, Any]]:
    """Record counts grouped by a single column, most-frequent first."""
    if _use_pg():
        return pgstore.group_records(group_by, **filters)
    if group_by not in _GROUPABLE:
        raise ValueError(f"group_by must be one of {sorted(_GROUPABLE)}, got '{group_by}'")
    where_sql, params = _build_where(filters)
    conn = get_db_connection()
    try:
        rows = conn.execute(
            f"SELECT {group_by} AS value, COUNT(*) AS record_count "
            f"FROM cached_bp_records WHERE 1=1{where_sql} "
            f"GROUP BY {group_by} ORDER BY record_count DESC",
            params,
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def list_records(limit: int = 25, offset: int = 0, **filters: str) -> Dict[str, Any]:
    """Paginated record listing plus the true total, so callers can page beyond the
    first screenful instead of being blind past a hard-coded slice."""
    if _use_pg():
        return pgstore.list_records(limit=limit, offset=offset, **filters)
    where_sql, params = _build_where(filters)
    conn = get_db_connection()
    try:
        total = int(conn.execute(
            f"SELECT COUNT(*) FROM cached_bp_records WHERE 1=1{where_sql}", params
        ).fetchone()[0])
        page = conn.execute(
            "SELECT project_number, bp_name, record_no, title, status, creator, assigned_to "
            f"FROM cached_bp_records WHERE 1=1{where_sql} "
            "ORDER BY project_number, bp_name, record_no LIMIT ? OFFSET ?",
            [*params, max(1, int(limit)), max(0, int(offset))],
        ).fetchall()
        return {"total": total, "offset": offset, "rows": [dict(r) for r in page]}
    finally:
        conn.close()


def distinct_values(field: str, **filters: str) -> List[str]:
    """Distinct non-empty values for a groupable column (e.g. all statuses)."""
    if _use_pg():
        return pgstore.distinct_values(field, **filters)
    if field not in _GROUPABLE:
        raise ValueError(f"field must be one of {sorted(_GROUPABLE)}, got '{field}'")
    where_sql, params = _build_where(filters)
    conn = get_db_connection()
    try:
        rows = conn.execute(
            f"SELECT DISTINCT {field} AS value FROM cached_bp_records "
            f"WHERE {field} != '' AND {field} IS NOT NULL{where_sql} ORDER BY {field}",
            params,
        ).fetchall()
        return [r["value"] for r in rows]
    finally:
        conn.close()


def semantic_search(
    query_text: str,
    project_number: Optional[str] = None,
    bp_name: Optional[str] = None,
    n_results: int = 8,
) -> List[Dict[str, Any]]:
    """Semantic / hybrid similarity search for fuzzy / 'why' questions.

    On Postgres this runs dense (pgvector) + sparse (tsvector) hybrid retrieval with
    reciprocal-rank fusion, scoped by project/BP metadata when provided. Falls back
    to the ChromaDB vector store when Postgres isn't configured. Results are mapped
    to a stable shape: {document, metadata{scope_type, project_number, bp_name,
    record_no}, distance}."""
    if _use_pg():
        emb = _embed_query(query_text)
        if emb is not None:
            hits = pgstore.hybrid_search(
                query_text=query_text, embedding=emb,
                project_number=project_number or "", bp_name=bp_name or "", k=n_results,
            )
            out: List[Dict[str, Any]] = []
            for h in hits:
                out.append({
                    "document": h.get("content", ""),
                    "metadata": {
                        "scope_type": "project" if h.get("project_number") else "company",
                        "project_number": h.get("project_number", ""),
                        "bp_name": h.get("bp_name", ""),
                        "record_no": h.get("record_no", ""),
                    },
                    "distance": None,
                })
            return out
        # embedder unavailable → degrade to Chroma below
    return query_vector_search(
        query_text=query_text,
        project_number=project_number or None,
        bp_name=bp_name or None,
        n_results=n_results,
    )


def find_projects(query: str, limit: int = 10) -> Dict[str, Any]:
    """Resolve a project by number or name.

    Project numbers are literal strings and are NOT zero-pad equivalent ('001',
    '0001', '000001' are three different projects), so this returns an EXACT
    project_number match separately from fuzzy candidates and never pads/reformats.
    Returns {'exact': {...}|None, 'candidates': [...]}.
    """
    if _use_pg():
        return pgstore.find_projects(query, limit=limit)
    q = (query or "").strip()
    conn = get_db_connection()
    try:
        exact_row = conn.execute(
            "SELECT project_number, project_name, status, project_type FROM cached_projects "
            "WHERE project_number = ?", (q,)
        ).fetchone()
        exact = dict(exact_row) if exact_row else None

        cand_rows = conn.execute(
            "SELECT project_number, project_name, status, project_type FROM cached_projects "
            "WHERE project_number = ? OR project_name LIKE ? "
            "ORDER BY (project_number = ?) DESC, project_number LIMIT ?",
            (q, f"%{q}%", q, int(limit)),
        ).fetchall()
        candidates = [dict(r) for r in cand_rows]
        return {"exact": exact, "candidates": candidates}
    finally:
        conn.close()


def is_company_bp(bpname: str) -> bool:
    """True if bpname is registered in the Company BP catalog (case-insensitive)."""
    if _use_pg():
        return pgstore.is_company_bp(bpname)
    if not bpname:
        return False
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT 1 FROM cached_company_bps WHERE LOWER(bp_name) = LOWER(?) LIMIT 1", (bpname.strip(),)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def aggregate_amounts(**filters: str) -> List[Dict[str, Any]]:
    """Exact monetary totals grouped BY CURRENCY (never summed across currencies).

    Postgres-only capability (reads amount + currency verbatim from records.raw).
    Returns [] when Postgres isn't configured, so the caller reports 'no amounts'
    rather than fabricating a cross-currency total."""
    if _use_pg():
        return pgstore.aggregate_amounts(**filters)
    return []


__all__ = [
    "count_records",
    "group_records",
    "list_records",
    "distinct_values",
    "semantic_search",
    "find_projects",
    "is_company_bp",
    "query_records_cross_project",
    "query_records_status_summary",
]
