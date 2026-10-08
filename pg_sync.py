"""
pg_sync.py — Live Unifier REST → Postgres ingestion.

Fetches a project's (or every project's) Business-Process records straight from the
live Unifier API and upserts them into the pgstore `records` table with CDC
(content_hash), then embeds the new/changed records via pg_ingest. This fills the
store for projects the legacy SQLite cache never covered (e.g. 0000567), so counts
reflect real data instead of an incomplete backfill.

Record ids match sync_manager's scheme so live sync and the SQLite backfill converge
on the same rows (idempotent, no duplicates):
    project:  project_{project_number}_{bpname}_{record_no}
    company:  company_{bpname}_{record_no}
"""
import os
import time
import logging
from typing import Any, Dict, List, Optional, Callable

import pgstore
from record_utils import extract_records

logger = logging.getLogger("PgSync")

THROTTLE_MS = int(os.getenv("SYNC_THROTTLE_MS", "40"))


def _rec_fields(r: Dict[str, Any], project_number: str, bpname: str, scope: str) -> Dict[str, Any]:
    rec_no = str(r.get("record_no") or r.get("id") or r.get("record_id") or "").strip()
    title = str(r.get("title") or r.get("record_title") or r.get("name") or "")
    status = str(r.get("status") or "")
    creator = str(r.get("creator") or r.get("created_by") or "")
    assigned = str(r.get("assigned_to") or r.get("assignedto") or r.get("owner") or "")
    if scope == "project":
        rid = f"project_{project_number}_{bpname}_{rec_no}"
    else:
        rid = f"company_{bpname}_{rec_no}"
    return {
        "id": rid, "scope_type": scope,
        "project_number": project_number if scope == "project" else "",
        "bp_name": bpname, "record_no": rec_no, "title": title, "status": status,
        "creator": creator, "assigned_to": assigned, "raw": r,
        "content_hash": pgstore.content_hash(r),
    }


def sync_project(project_number: str, client: Any, embed: bool = True) -> Dict[str, Any]:
    """Pull one project's BP records from live Unifier into Postgres (CDC upsert).
    Returns {ok, project_number, bps, records, changed, embedded?, error?}."""
    pgstore.ensure_schema()
    ok, data, code, _ = client.get_project_bp_list(project_number)
    if not ok:
        return {"ok": False, "project_number": project_number, "error": f"HTTP {code}: {data}", "records": 0}
    bps = extract_records(data)
    total = changed = bp_count = 0
    for bp in bps:
        if not isinstance(bp, dict):
            continue
        bpname = str(bp.get("bp_name") or bp.get("bp_model_name") or "").strip()
        if not bpname:
            continue
        bp_count += 1
        ok2, rdata, code2, _ = client.get_project_bp_records(project_number, bpname)
        if not ok2:
            logger.warning("records fetch failed for %s/%s: HTTP %s", project_number, bpname, code2)
            continue
        for r in extract_records(rdata):
            if not isinstance(r, dict):
                continue
            rec = _rec_fields(r, project_number, bpname, "project")
            if not rec["record_no"]:
                continue
            if pgstore.upsert_record(rec):
                changed += 1
            total += 1
        if THROTTLE_MS:
            time.sleep(THROTTLE_MS / 1000.0)
    result = {"ok": True, "project_number": project_number, "bps": bp_count, "records": total, "changed": changed}
    if embed and changed:
        from pg_ingest import run_ingest
        result["embedded"] = run_ingest(project_number=project_number, only_changed=True).get("embedded", 0)
    return result


def sync_all(client: Any, max_projects: Optional[int] = None, embed: bool = True,
             progress: Optional[Callable[[int, int, str], None]] = None) -> Dict[str, Any]:
    """Pull records for every active project into Postgres, then embed once at the end.
    max_projects caps how many projects are walked (None = all)."""
    pgstore.ensure_schema()
    ok, data, code, _ = client.get_active_projects()
    if not ok:
        return {"ok": False, "error": f"HTTP {code}: {data}"}
    projects = extract_records(data)
    if max_projects:
        projects = projects[:max_projects]
    totals = {"projects": 0, "records": 0, "changed": 0, "failed": 0}
    n = len(projects)
    for i, p in enumerate(projects, 1):
        pn = str(p.get("project_number") or p.get("projectnumber") or p.get("shell_number") or "").strip()
        if not pn:
            continue
        res = sync_project(pn, client, embed=False)
        totals["projects"] += 1
        if res.get("ok"):
            totals["records"] += res.get("records", 0)
            totals["changed"] += res.get("changed", 0)
        else:
            totals["failed"] += 1
        if progress:
            progress(i, n, pn)
    if embed and totals["changed"]:
        from pg_ingest import run_ingest
        totals["embedded"] = run_ingest(only_changed=True).get("embedded", 0)
    totals["ok"] = True
    pgstore.set_ingest_state(key="live_sync", meta=totals)
    return totals


def main():
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    ap = argparse.ArgumentParser(description="Live Unifier → Postgres ingestion.")
    ap.add_argument("--project", default="", help="Sync a single project_number.")
    ap.add_argument("--all", action="store_true", help="Sync all active projects.")
    ap.add_argument("--max", type=int, default=None, help="Cap projects when using --all.")
    args = ap.parse_args()

    from unifier_client import UnifierClient
    client = UnifierClient(
        bearer_token=os.getenv("UNIFIER_BEARER_TOKEN", ""),
        base_url=os.getenv("UNIFIER_BASE_URL", ""),
    )
    if args.project:
        print(sync_project(args.project, client))
    elif args.all:
        print(sync_all(client, max_projects=args.max,
                       progress=lambda i, n, pn: logger.info("project %d/%d: %s", i, n, pn)))
    else:
        ap.error("pass --project <num> or --all")


if __name__ == "__main__":
    main()
