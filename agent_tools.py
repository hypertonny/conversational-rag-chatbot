"""
agent_tools.py — LangChain tools for the Unifier RAG agent.

Tools are defined once at module scope (not rebuilt per request). The per-request
Unifier client and conversation memory are read from a ContextVar set by the
orchestrator before each agent invocation, which keeps the compiled agent reusable
across requests while remaining thread-safe.
"""
import contextvars
from dataclasses import dataclass
from typing import Any, List, Optional

from langchain_core.tools import tool

from record_utils import extract_records, format_record
import retrieval


@dataclass
class RequestContext:
    client: Any = None            # UnifierClient for this request (may be None)
    memory: Any = None            # ConversationMemory for this conversation


_request_ctx: "contextvars.ContextVar[Any]" = contextvars.ContextVar(
    "unifier_request_ctx", default=None
)


def set_request_context(client: Any = None, memory: Any = None) -> contextvars.Token:
    return _request_ctx.set(RequestContext(client=client, memory=memory))


def reset_request_context(token: contextvars.Token) -> None:
    try:
        _request_ctx.reset(token)
    except Exception:
        pass


def _ctx() -> RequestContext:
    ctx = _request_ctx.get()
    return ctx if isinstance(ctx, RequestContext) else RequestContext()


def _client() -> Any:
    return _ctx().client


def _memory() -> Any:
    return _ctx().memory


def _record_list_state(scope: str, bpname: str, project_number: str, shown: int, total: int) -> None:
    """Remember what list was just shown so a 'show more' follow-up can page it."""
    mem = _memory()
    if mem is not None:
        try:
            mem.set_list_state(scope=scope, bpname=bpname, project_number=project_number, shown=shown, total=total)
        except Exception:
            pass


def _project_bp_names(client: Any, project_number: str) -> Optional[list]:
    """Live list of BP names available for a project, or None if it can't be determined."""
    if client is None:
        return None
    try:
        ok, data, _code, _ = client.get_project_bp_list(project_number)
        if not ok:
            return None
        names = [str(r.get("bp_name") or r.get("bp_model_name") or "")
                 for r in extract_records(data) if isinstance(r, dict)]
        return [n for n in names if n]
    except Exception:
        return None


def _company_bp_records_text(client: Any, bpname: str, header_note: str = "") -> str:
    """Shared formatter for Company BP records (live API, cache fallback). ``header_note``
    is prepended so callers can explain WHY they're showing company-scoped data. Also records
    pagination state so a 'show more' follow-up can page the same BP."""
    prefix = (header_note + "\n\n") if header_note else ""
    if client is not None:
        success, data, status_code, _ = client.get_company_bp_records(bpname=bpname)
        if success:
            records = extract_records(data)
            if not records:
                _record_list_state("company", bpname, "", 0, 0)
                return f"{prefix}No records found in Company BP '{bpname}'."
            total = len(records)
            field_keys = list(records[0].keys()) if isinstance(records[0], dict) else []
            lines = [
                f"{prefix}Company BP '{bpname}' (live API): {total} total records",
                f"Fields available: {', '.join(field_keys)}",
                "", "Records (first 20 — say 'show more' to page, or use count_matching_records for exact counts):",
            ]
            for i, r in enumerate(records[:20]):
                lines.append(f"  Record {i+1}: {format_record(r) if isinstance(r, dict) else r}")
            if total > 20:
                lines.append(f"  ... and {total - 20} more records — say 'show more' to see the next 20.")
            _record_list_state("company", bpname, "", min(20, total), total)
            return "\n".join(lines)
    from sync_manager import query_cached_bp_records
    rows = query_cached_bp_records(bpname=bpname)
    if rows:
        total = len(rows)
        lines = [f"{prefix}Company BP '{bpname}' (local cache fallback): {total} records found", ""]
        for i, r in enumerate(rows[:20], 1):
            lines.append(f"  Record {i}: #{r['record_no']} | Title: {r['title']} | Status: {r['status']} | Creator: {r['creator']} | Assigned: {r['assigned_to']}")
        _record_list_state("company", bpname, "", min(20, total), total)
        return "\n".join(lines)
    _record_list_state("company", bpname, "", 0, 0)
    return f"{prefix}No records found in Company BP '{bpname}'."


# ============================ RETRIEVAL TOOLS ============================

@tool
def query_active_projects() -> str:
    """Fetch ALL active project shells from Unifier (name, number, status, type)."""
    client = _client()
    try:
        if client is not None:
            success, data, status_code, _ = client.get_active_projects()
            if success:
                records = extract_records(data)
                if not records:
                    return "No active projects found in the database."
                field_keys = list(records[0].keys()) if isinstance(records[0], dict) else []
                lines = [
                    f"Total active projects (live API): {len(records)}",
                    f"Available fields per project: {', '.join(field_keys)}",
                    "", "Project listing (first 50):",
                ]
                for i, r in enumerate(records[:50]):
                    if isinstance(r, dict):
                        name = r.get("projectname") or r.get("name") or "N/A"
                        num = r.get("projectnumber") or r.get("project_number") or "N/A"
                        status = r.get("status") or r.get("projectstatus") or "N/A"
                        ptype = r.get("type") or r.get("projecttype") or "N/A"
                        lines.append(f"  {i+1}. Name: {name} | Number: {num} | Status: {status} | Type: {ptype}")
                if len(records) > 50:
                    lines.append(f"  ... and {len(records) - 50} more projects.")
                return "\n".join(lines)
        # Cache fallback
        from sync_manager import query_cached_projects
        rows = [r for r in query_cached_projects() if str(r.get("status", "")).lower() == "active"] or query_cached_projects()
        if rows:
            lines = [f"Total projects (local cache fallback): {len(rows)}", "", "Project listing:"]
            for i, r in enumerate(rows[:50], 1):
                lines.append(f"  {i}. Name: {r['project_name']} | Number: {r['project_number']} | Status: {r['status']} | Type: {r['project_type']}")
            return "\n".join(lines)
        return "No active projects could be retrieved from the Unifier API."
    except Exception as e:
        return f"Error querying active projects: {e}"
@tool
def query_company_bp_catalog() -> str:
    """List all Company-level Business Processes (BPs) available in Unifier."""
    client = _client()
    try:
        if client is not None:
            success, data, status_code, _ = client.get_company_bp_list()
            if success:
                records = extract_records(data)
                if not records:
                    return "No Company Business Processes found."
                lines = [f"Total Company Business Processes (live API): {len(records)}", "", "Full BP list:"]
                for i, r in enumerate(records):
                    if isinstance(r, dict):
                        bp_name = r.get("bp_name") or r.get("bp_model_name") or str(r)
                        model = r.get("bp_model_name") or ""
                        source = r.get("studio_source") or r.get("source") or ""
                        extra = (f" | Model: {model}" if model else "") + (f" | Source: {source}" if source else "")
                        lines.append(f"  {i+1}. {bp_name}{extra}")
                return "\n".join(lines)
        from sync_manager import get_db_connection
        conn = get_db_connection()
        try:
            rows = conn.execute("SELECT bp_name, bp_model_name, studio_source FROM cached_company_bps").fetchall()
        finally:
            conn.close()
        if rows:
            lines = [f"Total Company Business Processes (local cache fallback): {len(rows)}", "", "Full BP list:"]
            for i, r in enumerate(rows, 1):
                lines.append(f"  {i}. {r['bp_name']} | Model: {r['bp_model_name']} | Source: {r['studio_source']}")
            return "\n".join(lines)
        return "No Company Business Processes available from the Unifier API."
    except Exception as e:
        return f"Error querying company BP catalog: {e}"


@tool
def query_project_bp_catalog(project_number: str) -> str:
    """Fetch the Business Processes CONFIGURED/AVAILABLE for a project/shell (the live catalog).

    IMPORTANT: this is the count of BPs *set up* for the project — it is usually LARGER than
    the number of BPs that actually have records. For "how many BPs have data" use the cached
    record counts (count_matching_records / query_records_status_summary). Always say
    "configured/available" when quoting this number so it isn't confused with populated BPs.

    Args:
        project_number: The project shell number (e.g. '000001').
    """
    client = _client()
    try:
        if client is None:
            return f"No Unifier connection provided to fetch BPs for project '{project_number}'."
        success, data, status_code, _ = client.get_project_bp_list(project_number)
        if not success:
            return f"⚠️ Unifier API Request Failed (HTTP {status_code}): {data}. Please check your Bearer Token or permissions in the sidebar."
        records = extract_records(data)
        if not records:
            return f"No Business Processes configured for project {project_number}."
        # How many of those BPs actually have records cached (matches the DB-graph view).
        with_records = 0
        try:
            from sync_manager import get_db_connection
            conn = get_db_connection()
            try:
                with_records = conn.execute(
                    "SELECT COUNT(DISTINCT bp_name) c FROM cached_bp_records WHERE project_number=?",
                    (project_number,)
                ).fetchone()["c"]
            finally:
                conn.close()
        except Exception:
            pass
        lines = [
            f"Project '{project_number}': {len(records)} Business Processes CONFIGURED (available). "
            f"Of these, {with_records} currently have records in the local store.",
            "",
        ]
        for i, r in enumerate(records):
            bp_name = (r.get("bp_name") or r.get("bp_model_name") or str(r)) if isinstance(r, dict) else str(r)
            lines.append(f"  {i+1}. {bp_name}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error querying project BP catalog: {e}"
@tool
def query_company_bp_records(bpname: str) -> str:
    """Fetch records inside a Company-level Business Process (sample rows + true total).

    Args:
        bpname: The exact BP name (e.g. 'Vendor', 'Contract').
    """
    try:
        return _company_bp_records_text(_client(), bpname)
    except Exception as e:
        return f"Error querying company BP records for '{bpname}': {e}"


@tool
def query_specific_company_bp_record(bpname: str, record_no: str) -> str:
    """Fetch a single Company BP record by its record number.
    Live API first; falls back to the local database if the live call fails or returns empty."""
    client = _client()
    try:
        if client is not None:
            success, data, status_code, _ = client.get_company_bp_records(bpname=bpname, filter_condition=f"record_no={record_no}")
            if not success:
                return f"⚠️ Unifier API Request Failed (HTTP {status_code}): {data}. Please check your Bearer Token or permissions in the sidebar."
            records = extract_records(data)
            if records:
                r = records[0]
                if isinstance(r, dict):
                    return f"Company BP '{bpname}' | Record '{record_no}' (live):\n{format_record(r, max_fields=100)}"
                return str(r)

        # Fallback to local DB cache (case-insensitive) if live API missed it due to case sensitivity or if client is None.
        res = retrieval.list_records(limit=1, project_number="", bp_name=bpname, record_no=record_no)
        if not res["rows"]:
            res = retrieval.list_records(limit=1, project_number="", record_no=record_no)
            if res["rows"]:
                bpname = res["rows"][0]["bp_name"]

        if res["rows"]:
            r = res["rows"][0]
            dup_note = ""
            try:
                # Record Number repeats across BPs — never silently pick one.
                dup_total = retrieval.count_records(record_no=record_no)
                if dup_total > 1:
                    dups = retrieval.list_records(limit=5, record_no=record_no).get("rows", [])
                    bps = sorted({d.get("bp_name", "") for d in dups if d.get("bp_name")})
                    dup_note = (f"\n⚠️ `Record Number` repeats in this dataset ({dup_total} rows share '{record_no}'"
                                f"{f' e.g. in: ' + ', '.join(bps) if bps else ''}). Showing 1 match for BP '{bpname}' — "
                                f"specify project + BP to disambiguate; rows are NOT deduplicated.")
            except Exception:
                pass
            import pgstore
            if pgstore.is_configured():
                with pgstore.get_pool().connection() as conn:
                    row = conn.execute("SELECT raw FROM records WHERE scope_type='company' AND bp_name ILIKE %s AND record_no ILIKE %s LIMIT 1",
                                       (f"%{bpname}%", f"%{record_no}%")).fetchone()
                    if row:
                        import json
                        raw = row[0] if isinstance(row[0], dict) else json.loads(row[0])
                        return f"Company BP '{bpname}' | Record '{record_no}' (cached):\n{format_record(raw, max_fields=100)}{dup_note}"
            return f"Company BP '{bpname}' | Record '{record_no}' (cached summary):\n{format_record(r, max_fields=100)}{dup_note}"

        return f"Record '{record_no}' not found in Company BP '{bpname}' (neither live nor cached)."
    except Exception as e:
        return f"Error fetching specific record '{record_no}' from BP '{bpname}': {e}"
@tool
def query_project_bp_records(project_number: str, bpname: str) -> str:
    """Fetch records inside a Business Process for a specific project (sample + true total).

    Guards against a common error: some BPs (e.g. 'Vendor') are COMPANY-level, not
    project-scoped. Asking for them "for a project" would otherwise return the company-wide
    list falsely labelled as project-specific. If the BP isn't in this project's live
    catalog but is a Company BP, this returns the company records with a clear note instead.
    """
    import retrieval
    client = _client()
    try:
        # Scope guard: only trust project attribution if the BP is actually in this
        # project's catalog. If not, and it's a Company BP, show company data honestly.
        project_bps = _project_bp_names(client, project_number)
        in_project_catalog = project_bps is not None and any(
            b.lower() == bpname.lower() for b in project_bps
        )
        if not in_project_catalog and retrieval.is_company_bp(bpname):
            note = (f"Note: '{bpname}' is a **company-level** business process — it is not scoped "
                    f"to a project, so it has no records specific to project '{project_number}'. "
                    f"Showing the company-wide '{bpname}' records instead.")
            return _company_bp_records_text(client, bpname, header_note=note)
        if project_bps is not None and not in_project_catalog and not retrieval.is_company_bp(bpname):
            return (f"'{bpname}' is not an available business process for project '{project_number}'. "
                    f"Available BPs for this project: {', '.join(project_bps[:30]) or '(none returned)'}.")

        if client is not None:
            success, data, status_code, _ = client.get_project_bp_records(project_number=project_number, bpname=bpname)
            if success:
                records = extract_records(data)
                if not records:
                    return f"No records found in BP '{bpname}' for project '{project_number}'."
                total = len(records)
                field_keys = list(records[0].keys()) if isinstance(records[0], dict) else []
                lines = [
                    f"Project '{project_number}' | BP '{bpname}' (live API): {total} total records",
                    f"Fields available: {', '.join(field_keys)}",
                    "", "Records (first 20 — say 'show more' to page, or use count_matching_records for exact counts):",
                ]
                for i, r in enumerate(records[:20]):
                    lines.append(f"  Record {i+1}: {format_record(r) if isinstance(r, dict) else r}")
                if total > 20:
                    lines.append(f"  ... and {total - 20} more records — say 'show more' to see the next 20.")
                _record_list_state("project", bpname, project_number, min(20, total), total)
                return "\n".join(lines)
        from sync_manager import query_cached_bp_records
        rows = query_cached_bp_records(project_number=project_number, bpname=bpname)
        if rows:
            total = len(rows)
            lines = [f"Project '{project_number}' | BP '{bpname}' (local cache fallback): {total} records found", ""]
            for i, r in enumerate(rows[:20], 1):
                lines.append(f"  Record {i}: #{r['record_no']} | Title: {r['title']} | Status: {r['status']} | Creator: {r['creator']} | Assigned: {r['assigned_to']}")
            _record_list_state("project", bpname, project_number, min(20, total), total)
            return "\n".join(lines)
        return f"No records found in BP '{bpname}' for project '{project_number}'."
    except Exception as e:
        return f"Error querying project BP records for project '{project_number}' BP '{bpname}': {e}"


@tool
def query_specific_project_bp_record(project_number: str, bpname: str, record_no: str) -> str:
    """Fetch a single Project BP record by its record number.
    Live API first; falls back to the local database if the live call fails or returns empty."""
    client = _client()
    try:
        if client is not None:
            success, data, status_code, _ = client.get_project_bp_records(project_number=project_number, bpname=bpname, filter_condition=f"record_no={record_no}")
            if not success:
                return f"⚠️ Unifier API Request Failed (HTTP {status_code}): {data}. Please check your Bearer Token or permissions in the sidebar."
            records = extract_records(data)
            if records:
                r = records[0]
                if isinstance(r, dict):
                    return f"Project '{project_number}' | BP '{bpname}' | Record '{record_no}' (live):\n{format_record(r, max_fields=100)}"
                return str(r)

        # Fallback to local DB cache (case-insensitive) if live API missed it due to case sensitivity or if client is None.
        res = retrieval.list_records(limit=1, project_number=project_number, bp_name=bpname, record_no=record_no)
        if not res["rows"]:
            # Maybe the user made a typo in the BP name (e.g. "report utiliti"). Try searching just by record_no in this project.
            res = retrieval.list_records(limit=1, project_number=project_number, record_no=record_no)
            if res["rows"]:
                bpname = res["rows"][0]["bp_name"] # Fix the BP name

        if res["rows"]:
            r = res["rows"][0]
            dup_note = ""
            try:
                dup_total = retrieval.count_records(project_number=project_number, record_no=record_no)
                if dup_total > 1:
                    dups = retrieval.list_records(limit=5, project_number=project_number, record_no=record_no).get("rows", [])
                    bps = sorted({d.get("bp_name", "") for d in dups if d.get("bp_name")})
                    dup_note = (f"\n⚠️ `Record Number` repeats in project '{project_number}' ({dup_total} rows share '{record_no}'"
                                f"{f' e.g. in: ' + ', '.join(bps) if bps else ''}). Showing 1 match for BP '{bpname}' — "
                                f"specify the exact BP; rows are NOT deduplicated.")
            except Exception:
                pass
            # Fetch the full raw record from pgstore directly to get all fields, not just the summary columns.
            import pgstore
            if pgstore.is_configured():
                with pgstore.get_pool().connection() as conn:
                    row = conn.execute("SELECT raw FROM records WHERE project_number=%s AND bp_name ILIKE %s AND record_no ILIKE %s LIMIT 1",
                                       (project_number, f"%{bpname}%", f"%{record_no}%")).fetchone()
                    if row:
                        import json
                        raw = row[0] if isinstance(row[0], dict) else json.loads(row[0])
                        return f"Project '{project_number}' | BP '{bpname}' | Record '{record_no}' (cached):\n{format_record(raw, max_fields=100)}{dup_note}"
            return f"Project '{project_number}' | BP '{bpname}' | Record '{record_no}' (cached summary):\n{format_record(r, max_fields=100)}{dup_note}"

        return f"Record '{record_no}' not found in BP '{bpname}' for project '{project_number}' (neither live nor cached)."
    except Exception as e:
        return f"Error fetching specific record '{record_no}' from project '{project_number}' BP '{bpname}': {e}"
@tool
def query_user_directory() -> str:
    """Fetch users from the Unifier user administration directory (active users).
    Live API first; falls back to the local cache only if the live call fails."""
    from record_utils import normalize_user
    client = _client()
    try:
        if client is not None:
            success, data, status_code, _ = client.get_users()  # defaults to active users
            if success:
                records = [normalize_user(r) for r in extract_records(data) if isinstance(r, dict)]
                if records:
                    lines = [
                        f"Total active users in Unifier directory (live API): {len(records)}",
                        "", "| # | Name | Login | Email | Status |", "|---|---|---|---|---|",
                    ]
                    for i, u in enumerate(records[:60], 1):
                        lines.append(f"| {i} | {u['name']} | {u['login']} | {u['email'] or '—'} | {u['status']} |")
                    if len(records) > 60:
                        lines.append(f"\n_Showing 60 of {len(records)} — ask to filter by name/email to narrow._")
                    return "\n".join(lines)
            else:
                # Only fall back to cache when the LIVE call actually failed.
                from sync_manager import query_cached_users
                rows = query_cached_users()
                if rows:
                    lines = [
                        f"⚠️ Live user API failed (HTTP {status_code}); showing {len(rows)} cached users.",
                        "", "| # | Name | Login | Email | Status |", "|---|---|---|---|---|",
                    ]
                    for i, r in enumerate(rows[:60], 1):
                        full = f"{r['first_name']} {r['last_name']}".strip() or r['user_name']
                        lines.append(f"| {i} | {full} | {r['user_name']} | {r['email'] or '—'} | {r['status']} |")
                    return "\n".join(lines)
                return f"⚠️ Unifier user API failed (HTTP {status_code}) and no users are cached yet."
        from sync_manager import query_cached_users
        rows = query_cached_users()
        if rows:
            lines = [f"Users (local cache): {len(rows)}", "", "| # | Name | Login | Email | Status |", "|---|---|---|---|---|"]
            for i, r in enumerate(rows[:60], 1):
                full = f"{r['first_name']} {r['last_name']}".strip() or r['user_name']
                lines.append(f"| {i} | {full} | {r['user_name']} | {r['email'] or '—'} | {r['status']} |")
            return "\n".join(lines)
        return "No Unifier connection provided and no users cached. Enter a Bearer Token to load the directory."
    except Exception as e:
        return f"Error querying user directory: {e}"


@tool
def query_users_filtered(filter_value: str) -> str:
    """Search users by name, email, login, or employee ID (partial, case-insensitive).
    Fetches the active-user directory and matches locally, so a bare first name like
    'rahul' works. Live API first; cache fallback only if the live call fails."""
    from record_utils import normalize_user
    client = _client()
    q = (filter_value or "").strip().lower()
    try:
        users = []
        source = "live API"
        if client is not None:
            success, data, status_code, _ = client.get_users()  # active users
            if success:
                users = [normalize_user(r) for r in extract_records(data) if isinstance(r, dict)]
        if not users:
            # Live returned nothing or failed → try cache.
            from sync_manager import query_cached_users
            users = [{"name": f"{r['first_name']} {r['last_name']}".strip() or r['user_name'],
                      "login": r['user_name'], "email": r['email'], "status": r['status'],
                      "first_name": r['first_name'], "last_name": r['last_name'], "emp_id": "",
                      "title": "", "company": "", "phone": ""} for r in query_cached_users()]
            source = "local cache"
        if not users:
            return "The user directory could not be loaded from the live API or the cache. Check the Bearer Token, then try again."

        def hay(u):
            return " ".join([u["name"], u["login"], u["email"], u["first_name"], u["last_name"], u["emp_id"]]).lower()
        matches = [u for u in users if q in hay(u)] if q else users
        if not matches:
            return (f"No user matches '{filter_value}' among the {len(users)} active users ({source}). "
                    f"Try a different spelling, a partial name, or an email/employee ID.")
        lines = [
            f"Found {len(matches)} user(s) matching '{filter_value}' ({source}):",
            "", "| # | Name | Login | Email | Title | Status |", "|---|---|---|---|---|---|",
        ]
        for i, u in enumerate(matches[:30], 1):
            lines.append(f"| {i} | {u['name']} | {u['login']} | {u['email'] or '—'} | {u['title'] or '—'} | {u['status']} |")
        if len(matches) > 30:
            lines.append(f"\n_Showing 30 of {len(matches)} matches._")
        return "\n".join(lines)
    except Exception as e:
        return f"Error searching users for '{filter_value}': {e}"
@tool
def query_project_users(project_number: str) -> str:
    """Find users/people assigned within a specific project.

    Checks the local cache first (instant); falls back to a bounded live scan.
    """
    client = _client()
    try:
        from sync_manager import get_db_connection
        conn = get_db_connection()
        try:
            rows = conn.execute(
                """
                SELECT bp_name, 'creator' AS field, creator AS value FROM cached_bp_records WHERE project_number=? AND creator != ''
                UNION
                SELECT bp_name, 'assigned_to' AS field, assigned_to AS value FROM cached_bp_records WHERE project_number=? AND assigned_to != ''
                """,
                (project_number, project_number),
            ).fetchall()
        finally:
            conn.close()
        if rows:
            lines = [
                f"### Users found in Project '{project_number}' (local cache)",
                f"Found {len(rows)} user assignment records.\n",
                "| Business Process | Field | Assigned User/Value |", "|---|---|---|",
            ]
            for r in rows[:50]:
                lines.append(f"| {r['bp_name']} | {r['field']} | {r['value']} |")
            return "\n".join(lines)

        if client is None:
            return f"No Unifier connection and no cached user records for project '{project_number}'."
        ok, bp_data, code, _ = client.get_project_bp_list(project_number)
        if not ok:
            return f"⚠️ Unifier API Request Failed (HTTP {code}): {bp_data}. Please check your Bearer Token or permissions in the sidebar."
        bp_names = [str(r.get("bp_name") or r.get("bp_model_name") or "") for r in extract_records(bp_data) if isinstance(r, dict)]
        bp_names = [n for n in bp_names if n]
        USER_FIELDS = {"assigned_to", "assignedto", "creator", "created_by", "createdby", "owner", "owner_id", "manager", "project_manager", "responsible", "user", "user_name", "username", "modified_by", "modifiedby"}
        found = []
        for bp_name in bp_names[:3]:  # bounded to avoid live timeout
            try:
                ok2, rec_data, _, _ = client.get_project_bp_records(project_number=project_number, bpname=bp_name)
                if not ok2:
                    continue
                for rec in extract_records(rec_data)[:5]:
                    if isinstance(rec, dict):
                        for k, v in rec.items():
                            if k.lower().replace("-", "_") in USER_FIELDS and v:
                                found.append((bp_name, k, str(v)))
            except Exception:
                continue
        if not found:
            return f"Project '{project_number}': checked initial BPs, no user assignment fields found (or token unauthorized)."
        lines = [f"### Users found in Project '{project_number}'", "| Business Process | Field | Assigned User/Value |", "|---|---|---|"]
        for bp_name, k, v in found[:30]:
            lines.append(f"| {bp_name} | {k} | {v} |")
        return "\n".join(lines)
    except Exception as e:
        return f"Error scanning project '{project_number}' for users: {e}"
# ============================ STRUCTURED ANALYTICS TOOLS ============================

@tool
def show_more_records(page_size: int = 20) -> str:
    """Show/continue the records for whatever the conversation is currently about. Call this
    for 'show', 'show it', 'show more', 'next', 'continue', or "show those". It pages the
    most recently listed BP, or — if nothing was listed yet — lists the ACTIVE business
    process from the conversation context (so 'how many change orders?' then 'show' works).
    """
    import retrieval
    mem = _memory()
    state = getattr(mem, "list_state", None) or {}
    bpname = state.get("bpname") or (getattr(mem, "active_bp_name", "") if mem else "")
    project_number = state.get("project_number") or (getattr(mem, "active_project_number", "") if mem else "")
    scope = state.get("scope", "project")
    exact = bool(state.get("exact", False))  # a real prior listing pages exact; a derived one uses LIKE
    shown = int(state.get("shown", 0))
    if not bpname:
        return ("There's no active list yet. Tell me which records to show — e.g. "
                "'show the Change Order records' or 'list Contract records for project 001'.")
    try:
        if exact:
            from sync_manager import query_cached_bp_records
            allrows = query_cached_bp_records(project_number=project_number, bpname=bpname)
            total = len(allrows)
            page = allrows[shown:shown + max(1, int(page_size))]
        else:
            res = retrieval.list_records(limit=max(1, int(page_size)), offset=shown,
                                         bp_name=bpname, project_number=project_number)
            total = res["total"]
            page = res["rows"]
        if not page:
            if shown == 0:
                return f"No cached records found for '{bpname}'{f' in project {project_number}' if project_number else ''}. Try a sync, or check the BP name."
            return f"That's all {total} record(s) for '{bpname}'. Nothing more to show."
        scope_lbl = "company-wide" if scope == "company" else (f"project {project_number}" if project_number else "all projects")
        lines = [
            f"'{bpname}' ({scope_lbl}) — records {shown + 1}-{shown + len(page)} of {total}:",
            "| Project | BP | Record # | Title | Status |", "|---|---|---|---|---|",
        ]
        for r in page:
            lines.append(f"| {r.get('project_number','')} | {r.get('bp_name', bpname)} | {r['record_no']} | {r['title']} | {r['status']} |")
        new_shown = shown + len(page)
        if mem is not None:
            try:
                mem.set_list_state(scope=scope, bpname=bpname, project_number=project_number,
                                   shown=new_shown, total=total, exact=exact)
            except Exception:
                pass
        lines.append(f"\n_{total - new_shown} more — say 'show more' to continue._" if new_shown < total else "\n_End of records._")
        return "\n".join(lines)
    except Exception as e:
        return f"Error paging records for '{bpname}': {e}"


@tool
def resolve_project(query: str) -> str:
    """Resolve a project by NUMBER or NAME to its canonical project_number before any
    project-scoped call. Project numbers are exact strings and are NOT zero-pad equivalent:
    '001', '0001', and '000001' are DIFFERENT projects. Never pad/reformat a number yourself —
    use this tool, then use the exact project_number it returns.

    Args:
        query: A project number (e.g. '001') or a project name fragment (e.g. 'Datamato').
    """
    import retrieval
    try:
        res = retrieval.find_projects(query, limit=10)
        exact, cands = res["exact"], res["candidates"]
        if exact:
            out = [f"Exact match — project_number '{exact['project_number']}': {exact['project_name']} "
                   f"(Status: {exact['status']}, Type: {exact['project_type']}). Use this exact number."]
            others = [c for c in cands if c["project_number"] != exact["project_number"]]
            if others:
                out.append("\nSimilar (DIFFERENT) projects — do not confuse with the exact match:")
                for c in others[:8]:
                    out.append(f"  - '{c['project_number']}': {c['project_name']}")
            return "\n".join(out)
        if cands:
            lines = [f"No project has the exact number/name '{query}'. Candidates (pick the intended "
                     f"project_number — they are distinct, not zero-pad variants of each other):"]
            for c in cands[:10]:
                lines.append(f"  - '{c['project_number']}': {c['project_name']} (Status: {c['status']})")
            return "\n".join(lines)
        return (f"No project matches '{query}' in the cache. Ask the user to confirm the exact "
                f"project number or name, or run a sync if the catalog may be stale.")
    except Exception as e:
        return f"Error resolving project '{query}': {e}"


@tool
def count_matching_records(status: str = "", bp_name: str = "", project_number: str = "",
                           assigned_to: str = "", creator: str = "", keyword: str = "") -> str:
    """EXACT count of BP records matching the filters. Use for any 'how many' question.
    All args optional; blanks are ignored. Partial match on status/bp_name/assignee/creator/keyword."""
    try:
        n = retrieval.count_records(status=status, bp_name=bp_name, project_number=project_number,
                                    assigned_to=assigned_to, creator=creator, keyword=keyword)
        applied = {k: v for k, v in dict(status=status, bp_name=bp_name, project_number=project_number,
                                          assigned_to=assigned_to, creator=creator, keyword=keyword).items() if v}
        filt = ", ".join(f"{k}={v}" for k, v in applied.items()) or "no filters"
        # Completeness guard: a 0 for a specific project may mean "that project's records were
        # never ingested", NOT a confirmed zero. Distinguish the two so we never present an
        # incomplete-store 0 as fact.
        if project_number and n == 0:
            proj_total = retrieval.count_records(project_number=project_number)
            if proj_total == 0:
                res = retrieval.find_projects(project_number)
                if res.get("exact"):
                    name = res["exact"].get("project_name", "")
                    return (f"NOT A CONFIRMED ZERO: project {project_number} ({name}) exists but has NO "
                            f"records ingested in the database yet, so a real count is unavailable. Tell the "
                            f"user this plainly and offer to ingest it now via sync_project_records "
                            f"(project_number='{project_number}'). Do NOT report '0 {bp_name or 'records'}'.")
                return (f"No project with the exact number '{project_number}' is in the database. Call "
                        f"resolve_project to find the intended project; do not report a count of 0.")
        # Disclosure: a loose bp_name term can span several distinct BPs (e.g. 'change order'
        # matches both 'Change Order' and 'Potential Change Order'). Surface the split so the
        # count never silently conflates BPs and can't disagree with a per-BP breakdown.
        if bp_name and n > 0:
            try:
                by_bp = retrieval.group_records("bp_name", status=status, project_number=project_number,
                                                assigned_to=assigned_to, creator=creator, keyword=keyword, bp_name=bp_name)
                distinct = [r for r in by_bp if (r.get("value") or "").strip()]
                if len(distinct) > 1:
                    split = "; ".join(f"{r['value']}={r['record_count']}" for r in distinct)
                    return (f"Exact count: {n} ({filt}). NOTE: this term matches {len(distinct)} DISTINCT business "
                            f"processes — {split}. Report the {n} total AND this per-BP split so the user can see "
                            f"the composition; if they meant only one BP, use its exact name.")
            except Exception:
                pass
        return f"Exact count of matching records: {n} ({filt})."
    except Exception as e:
        return f"Error counting records: {e}"


@tool
def group_records_by(group_by: str, status: str = "", bp_name: str = "", project_number: str = "",
                     assigned_to: str = "", creator: str = "") -> str:
    """Counts grouped by a single column. group_by must be one of:
    project_number, bp_name, status, creator, assigned_to. Returns a Markdown table."""
    try:
        rows = retrieval.group_records(group_by, status=status, bp_name=bp_name,
                                       project_number=project_number, assigned_to=assigned_to, creator=creator)
        if not rows:
            return "No matching records to group. Try triggering a sync or broadening filters."
        lines = [f"| {group_by} | count |", "|---|---|"]
        for r in rows:
            lines.append(f"| {r['value'] or '(blank)'} | {r['record_count']} |")
        table = "\n".join(lines)
        # Weak models sometimes describe the table without pasting it — make the table the
        # explicit deliverable so it ends up verbatim in the user-facing answer.
        return ("Present EXACTLY this Markdown table to the user (do not just describe it; include every row):\n\n"
                + table)
    except ValueError as ve:
        return str(ve)
    except Exception as e:
        return f"Error grouping records: {e}"


@tool
def list_matching_records(limit: int = 25, offset: int = 0, status: str = "", bp_name: str = "",
                          project_number: str = "", assigned_to: str = "", creator: str = "", keyword: str = "") -> str:
    """Paginated record listing plus the TRUE total, so you can page beyond the first screen.
    Use offset to fetch subsequent pages. All filters optional."""
    try:
        res = retrieval.list_records(limit=limit, offset=offset, status=status, bp_name=bp_name,
                                     project_number=project_number, assigned_to=assigned_to, creator=creator, keyword=keyword)
        rows = res["rows"]
        if not rows:
            return f"No matching records (total={res['total']}). Try broadening filters or triggering a sync."
        lines = [
            f"Showing rows {res['offset'] + 1}-{res['offset'] + len(rows)} of {res['total']} total.",
            "| Project | BP | Record # | Title | Status | Creator | Assigned |", "|---|---|---|---|---|---|---|",
        ]
        for r in rows:
            lines.append(f"| {r['project_number']} | {r['bp_name']} | {r['record_no']} | {r['title']} | {r['status']} | {r['creator']} | {r['assigned_to']} |")
        if res["offset"] + len(rows) < res["total"]:
            lines.append(f"\n_More rows available — call again with offset={res['offset'] + len(rows)}._")
        return "\n".join(lines)
    except Exception as e:
        return f"Error listing records: {e}"


@tool
def list_distinct_values(field: str, status: str = "", bp_name: str = "", project_number: str = "") -> str:
    """Distinct non-empty values for a column (e.g. every status or BP name in use).
    field must be one of: project_number, bp_name, status, creator, assigned_to."""
    try:
        vals = retrieval.distinct_values(field, status=status, bp_name=bp_name, project_number=project_number)
        if not vals:
            return f"No distinct '{field}' values found for those filters."
        return f"Distinct {field} values ({len(vals)}): " + ", ".join(vals)
    except ValueError as ve:
        return str(ve)
    except Exception as e:
        return f"Error listing distinct values: {e}"


@tool
def aggregate_amounts_by_currency(bp_name: str = "", project_number: str = "", status: str = "",
                                  creator: str = "", assigned_to: str = "", keyword: str = "") -> str:
    """EXACT monetary totals from the database, grouped BY CURRENCY — never summed across
    currencies. Use for any 'total/sum of amount/value' question (e.g. 'total approved change
    order value in project 001'). Reads the amount verbatim from each record and its currency
    label; reports one subtotal per currency (USD/EUR/JPY/...). All filters optional/partial-match.
    Present each currency separately and state the filter; do NOT add different currencies together."""
    try:
        rows = retrieval.aggregate_amounts(bp_name=bp_name, project_number=project_number, status=status,
                                           creator=creator, assigned_to=assigned_to, keyword=keyword)
        applied = {k: v for k, v in dict(bp_name=bp_name, project_number=project_number, status=status,
                                         creator=creator, assigned_to=assigned_to, keyword=keyword).items() if v}
        filt = ", ".join(f"{k}={v}" for k, v in applied.items()) or "no filters"
        if not rows:
            return f"No matching records with amounts in the database ({filt})."
        lines = [f"Exact amount totals BY CURRENCY ({filt}) — currencies are NOT combined:",
                 "| Currency | Records | Total (this currency only) |", "|---|---|---|"]
        for r in rows:
            total = f"{r['total']:,.2f}"
            note = f" (+{r['non_numeric_rows']} rows had no numeric amount)" if r.get("non_numeric_rows") else ""
            lines.append(f"| {r['currency']} | {r['record_count']} | {total}{note} |")
        if any(r.get("non_numeric_rows") for r in rows):
            lines.append("\n_Blanks are not zero: rows with blank/non-numeric amounts are counted separately and excluded from totals._")
        return "\n".join(lines)
    except Exception as e:
        return f"Error aggregating amounts: {e}"
@tool
def get_current_date() -> str:
    """Current UTC date (as-of date) for overdue / date-window questions.

    Call this before answering anything about past-due, overdue, or "last N months"
    so the answer states the exact as-of date and date basis used. Never use a
    silent system date — declare it, e.g. "as of 2026-10-08 using Due Date"."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    return (f"Current UTC date: {now.date().isoformat()} (as-of date). "
            f"State this date in the answer and name the date field used (e.g. Due Date, Effective Date). "
            f"Call something overdue only when its due date is before this date AND status does not show completion.")


@tool
def query_records_across_projects(status: str = "", bp_name: str = "", assigned_to: str = "",
                                   keyword: str = "", project_number: str = "") -> str:
    """Search cached BP records across ALL projects/BPs at once. Good for broad requests like
    'my open tasks', 'pending change orders', 'vendor records'. All args optional.
    NOTE: this returns at most 50 example rows — it is NOT a count. For a total, use
    count_matching_records; never infer the total from the number of rows shown here."""
    try:
        total = retrieval.count_records(status=status, bp_name=bp_name, assigned_to=assigned_to,
                                        keyword=keyword, project_number=project_number)
        rows = retrieval.query_records_cross_project(status=status, bp_name=bp_name, assigned_to=assigned_to,
                                                     keyword=keyword, project_number=project_number, limit=50)
        if not rows:
            return f"No matching records in the local cache for those filters (exact total: {total})."
        from datetime import datetime, timezone
        as_of = datetime.now(timezone.utc).date().isoformat()
        lines = [f"Exact total matching: {total}. Showing {len(rows)} example row(s) (capped at 50 — NOT the total). As-of date: {as_of}.", ""]
        for r in rows:
            lines.append(f"  Project {r['project_number']} | {r['bp_name']} | #{r['record_no']} | {r['title']} | Status: {r['status']} | Assigned: {r['assigned_to'] or 'n/a'}")
        if (keyword or bp_name) and any(k in f"{keyword} {bp_name}".lower() for k in ("vendor", "nd builders")):
            lines.append("\n_Note: a shared vendor NAME match does not prove a parent-document relationship. "
                         "Cross-document links need a validated exact join key; see the evidence table._")
        return "\n".join(lines)
    except Exception as e:
        return f"Error searching records across projects: {e}"


@tool
def query_records_status_summary(bp_name: str = "", project_number: str = "") -> str:
    """Record counts grouped by Business Process and status across projects — for health /
    bottleneck / executive-summary requests. Cost, budget, and dates are NOT tracked here."""
    try:
        rows = retrieval.query_records_status_summary(bp_name=bp_name, project_number=project_number)
        if not rows:
            return "No cached records match those filters. Try a sync or broaden the filters."
        lines = ["BP / Status breakdown (record counts):", ""]
        for r in rows:
            lines.append(f"  {r['bp_name']} — {r['status']}: {r['record_count']}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error summarizing record status: {e}"


# ============================ SEMANTIC & META TOOLS ============================

@tool
def semantic_search_unifier(query: str, project_number: str = "", bp_name: str = "") -> str:
    """Semantic similarity search over the cached vector store. Use for open-ended / 'why'
    questions like 'find change orders related to concrete' or 'why was the contract delayed'."""
    try:
        results = retrieval.semantic_search(query_text=query, project_number=project_number or None,
                                            bp_name=bp_name or None, n_results=8)
        if not results:
            return "No matching semantic results in the local vector store. Try live querying or a sync."
        lines = [f"Found {len(results)} relevant vector matches:"]
        for idx, r in enumerate(results, 1):
            doc = r.get("document", "")
            meta = r.get("metadata", {})
            dist = r.get("distance")
            score = f" (distance: {dist:.3f})" if dist is not None else ""
            lines.append(f"  {idx}. [{meta.get('scope_type', 'record')}] {doc[:600]}{score}")
        return "\n".join(lines)
    except Exception as e:
        return f"Vector search error: {e}"


@tool
def sync_project_records(project_number: str) -> str:
    """Ingest ONE project's Business-Process records from the live Unifier API into the
    grounded Postgres store, then embed them. Use this when a project exists but has no
    records in the database yet (so counts would be an incomplete '0'), or when the user
    asks to refresh/sync a specific project. After it runs, counts for that project are real."""
    if not project_number or not project_number.strip():
        return "Provide the exact project_number to sync (e.g. '0000567')."
    client = _client()
    try:
        import pg_sync
        res = pg_sync.sync_project(project_number.strip(), client, embed=True)
        if not res.get("ok"):
            return (f"⚠️ Could not sync project {project_number}: {res.get('error', 'unknown error')}. "
                    "Check the Bearer Token / permissions in the sidebar.")
        return (f"Synced project {project_number}: {res.get('records', 0)} records across "
                f"{res.get('bps', 0)} business processes ({res.get('changed', 0)} new/changed, "
                f"{res.get('embedded', 0)} embedded). Counts for this project are now grounded in the database.")
    except Exception as e:
        return f"Error syncing project {project_number}: {e}"


@tool
def trigger_local_data_sync() -> str:
    """Sync remote Unifier REST data into the local SQLite cache and ChromaDB vector store.
    Use when the user asks to 'sync data', 'refresh database', or 'update the cache'."""
    client = _client()
    try:
        from sync_manager import SyncManager
        res = SyncManager(client=client).sync_all()
        return f"Sync complete! Total records synced: {res.get('total_records_synced', 0)} in {res.get('elapsed_ms', 0):.1f}ms."
    except Exception as e:
        return f"Sync error: {e}"
@tool
def query_full_database_summary() -> str:
    """Overview counts across the whole cache (projects, BPs, records, users, embeddings) plus a live active-project count."""
    lines = ["=== FULL UNIFIER DATABASE SUMMARY ===", ""]
    try:
        from sync_manager import get_sync_stats
        stats = get_sync_stats()
        lines += [
            f"📁 Cached Projects: {stats.get('cached_projects', 0)}",
            f"🗂️  Cached Company BPs: {stats.get('cached_company_bps', 0)}",
            f"📄 Cached BP Records: {stats.get('cached_bp_records', 0)}",
            f"👥 Cached Users: {stats.get('cached_users', 0)}",
            f"🔍 Vector Embeddings Index: {stats.get('vector_embeddings', 0)}",
            "",
        ]
    except Exception:
        pass
    client = _client()
    if client is not None:
        try:
            ok, data, code, _ = client.get_active_projects()
            lines.append(f"📁 Live Active Projects: {len(extract_records(data)) if ok else 0} (HTTP {code})")
        except Exception as e:
            lines.append(f"📁 Active Projects: {e}")
    return "\n".join(lines)


@tool
def query_oracle_documentation_guides() -> str:
    """Official Oracle Primavera Unifier v26 documentation links and BP field schema mapping."""
    return (
        "### 📚 Official Oracle Primavera Unifier v26 Reference Guides & Schema\n\n"
        "- 🔗 [Integration Interface Guide](https://docs.oracle.com/en/industries/construction-engineering/primavera-unifier/26/integration-interface/introduction-10280474a.html)\n"
        "- 🔗 [Data Reference Guide](http://docs.oracle.com/en/industries/construction-engineering/primavera-unifier/26/reference/introduction-10289477a.html)\n"
        "- 🔗 [Business Processes User Guide](https://docs.oracle.com/en/industries/construction-engineering/primavera-unifier/26/business-process/workingwithbusinessprocesses-10292605a.html)\n"
        "- 🔗 [uDesigner User Guide](https://docs.oracle.com/en/industries/construction-engineering/primavera-unifier/26/udesigner/introducingunifierudesigner-77633a.html)\n"
        "- 🔗 [General User Guide](https://docs.oracle.com/en/industries/construction-engineering/primavera-unifier/26/general-user/gettingstartedwithgeneraloperations-73021a.html)\n\n"
        "#### Business Process (BP) Field Schema Mapping\n"
        "| Field Name | Description |\n|---|---|\n"
        "| `bp_model_name` | The BP Model ID (unique identifier) |\n"
        "| `bp_name` | The BP display name (unique) |\n"
        "| `studio_source` | The BP type / studio source (simple, database, etc.) |\n"
        "| `no_workflow` | Whether the BP is non-workflow |\n"
    )


# ============================ TOOL REGISTRY ============================

ALL_TOOLS = [
    query_active_projects,
    resolve_project,
    query_company_bp_catalog,
    query_project_bp_catalog,
    query_company_bp_records,
    query_specific_company_bp_record,
    query_project_bp_records,
    query_specific_project_bp_record,
    query_user_directory,
    query_users_filtered,
    query_project_users,
    count_matching_records,
    group_records_by,
    list_matching_records,
    list_distinct_values,
    aggregate_amounts_by_currency,
    query_records_across_projects,
    query_records_status_summary,
    show_more_records,
    get_current_date,
    semantic_search_unifier,
    sync_project_records,
    trigger_local_data_sync,
    query_full_database_summary,
    query_oracle_documentation_guides,
]


def build_tools() -> List[Any]:
    """Return the module-level tool list (defined once; per-request state via ContextVar)."""
    return ALL_TOOLS
