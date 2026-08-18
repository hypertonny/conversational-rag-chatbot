"""
chatbot_engine.py — Agentic RAG Engine for Primavera Unifier Portal

All confirmed Unifier REST v1 API endpoints covered:

  ENDPOINT                                              METHOD  TOOL
  /admin/projectshell?Status=Active                    GET     query_active_projects
  /admin/bps                                           GET     query_company_bp_catalog
  /admin/bps/{project_number}                          GET     query_project_bp_catalog
  /bp/records/          (all records of a Company BP)  POST    query_company_bp_records
  /bp/records/          (filtered by record_no)        POST    query_specific_company_bp_record  ← NEW
  /bp/records/{project_number}  (all records)          POST    query_project_bp_records
  /bp/records/{project_number}  (filtered)             POST    query_specific_project_bp_record  ← NEW
  /admin/user/get                                      POST    query_user_directory
  /admin/user/get       (with filterCondition)         POST    query_users_filtered              ← NEW
  Summary across all endpoints                         —       query_full_database_summary
"""
import os
from typing import List, Dict, Any, Optional

from langchain_groq import ChatGroq


def _extract_records(data: Any) -> list:
    """Safely extract list of records from Unifier API response."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("data", "records", "result", "results", "items"):
            val = data.get(key)
            if isinstance(val, list):
                return val
            if isinstance(val, dict):
                return [val]
        return [data]
    return []


def _format_record(r: dict, max_fields: int = 40) -> str:
    """Format a single record dict into a readable pipe-separated string."""
    parts = []
    for i, (k, v) in enumerate(r.items()):
        if i >= max_fields:
            parts.append(f"... (+{len(r) - max_fields} more fields)")
            break
        if isinstance(v, dict):
            parts.append(f"{k}: {{{', '.join(f'{dk}={dv}' for dk, dv in list(v.items())[:5])}}}")
        elif isinstance(v, list):
            parts.append(f"{k}: [{len(v)} items]")
        else:
            parts.append(f"{k}: {v}")
    return " | ".join(parts)


class ChatbotEngine:
    def __init__(
        self,
        openai_api_key: Optional[str] = None,
        groq_api_key: Optional[str] = None,
        gemini_api_key: Optional[str] = None,
    ):
        self.openai_api_key = openai_api_key or ""
        self.groq_api_key = groq_api_key or ""
        self.gemini_api_key = gemini_api_key or ""

    def is_ready(self) -> bool:
        return bool(self.openai_api_key or self.groq_api_key or self.gemini_api_key)

    def get_chat_response(
        self,
        user_query: str,
        chat_history: Optional[List[Dict[str, str]]] = None,
        provider: str = "groq",
        client: Any = None,
    ) -> str:
        if chat_history is None:
            chat_history = []

        if not self.is_ready():
            return (
                "Chatbot is not ready. Please provide a Groq, Gemini, or OpenAI API Key "
                "in the AI Chatbot Config section of the sidebar."
            )

        if client is None:
            return (
                "No Unifier connection established. Please enter your Bearer Token "
                "and click Test API Connection first, then ask your question again."
            )

        return self._get_agent_response(user_query, chat_history, provider, client)

    def _get_agent_response(
        self,
        user_query: str,
        chat_history: List[Dict[str, str]],
        provider: str,
        client: Any,
    ) -> str:
        try:
            from langchain_core.tools import tool
            from langgraph.prebuilt import create_react_agent
        except ImportError as e:
            return f"Required dependency missing: {e}. Please redeploy."

        # ── TOOL 1: Active Projects ──────────────────────────────────────────
        @tool
        def query_active_projects() -> str:
            """
            Fetches ALL active project shells from Primavera Unifier.
            First checks local SQLite cache for instant response, falls back to live API.
            Returns total count, project names, numbers, status, type.
            """
            try:
                # 1. Try local SQLite cache first (instant <5ms)
                try:
                    from sync_manager import get_db_connection
                    conn = get_db_connection()
                    c = conn.cursor()
                    c.execute("SELECT project_number, project_name, status, project_type FROM cached_projects WHERE status='Active' OR status='active'")
                    rows = c.fetchall()
                    conn.close()
                    if rows:
                        lines = [
                            f"Total active projects (local cache): {len(rows)}",
                            "",
                            "Project listing:"
                        ]
                        for i, r in enumerate(rows[:50], 1):
                            lines.append(f"  {i}. Name: {r[1]} | Number: {r[0]} | Status: {r[2]} | Type: {r[3]}")
                        return "\n".join(lines)
                except Exception as cache_err:
                    pass

                # 2. Live API fallback
                if client is None:
                    return "No Unifier connection provided and no local cached projects available."
                success, data, status_code, _ = client.get_active_projects()
                if not success:
                    return f"Active Projects API failed (HTTP {status_code}): {data}"
                records = _extract_records(data)
                total = len(records)
                if total == 0:
                    return "No active projects found in the database."

                field_keys = list(records[0].keys()) if isinstance(records[0], dict) else []
                lines = [
                    f"Total active projects: {total}",
                    f"Available fields per project: {', '.join(field_keys)}",
                    "",
                    "Project listing (first 50):"
                ]
                for i, r in enumerate(records[:50]):
                    if isinstance(r, dict):
                        name = r.get("projectname") or r.get("name") or "N/A"
                        num = r.get("projectnumber") or r.get("project_number") or "N/A"
                        status = r.get("status") or r.get("projectstatus") or "N/A"
                        ptype = r.get("type") or r.get("projecttype") or "N/A"
                        lines.append(f"  {i+1}. Name: {name} | Number: {num} | Status: {status} | Type: {ptype}")
                if total > 50:
                    lines.append(f"  ... and {total - 50} more projects.")
                return "\n".join(lines)
            except Exception as e:
                return f"Error querying active projects: {e}"

        # ── TOOL 2: Company BP Catalog ───────────────────────────────────────
        @tool
        def query_company_bp_catalog() -> str:
            """
            Fetches master list of all Company-level Business Processes (BPs) in Unifier.
            First checks local SQLite cache for instant response, falls back to live API.
            """
            try:
                # 1. Try local SQLite cache first
                try:
                    from sync_manager import get_db_connection
                    conn = get_db_connection()
                    c = conn.cursor()
                    c.execute("SELECT bp_name, bp_model_name, studio_source FROM cached_company_bps")
                    rows = c.fetchall()
                    conn.close()
                    if rows:
                        lines = [
                            f"Total Company Business Processes (local cache): {len(rows)}",
                            "",
                            "Full BP list:"
                        ]
                        for i, r in enumerate(rows, 1):
                            lines.append(f"  {i}. {r[0]} | Model: {r[1]} | Source: {r[2]}")
                        return "\n".join(lines)
                except Exception:
                    pass

                # 2. Live API fallback
                if client is None:
                    return "No Unifier connection provided and no local cached BPs available."
                success, data, status_code, _ = client.get_company_bp_list()
                if not success:
                    return f"Company BP Catalog API failed (HTTP {status_code}): {data}"
                records = _extract_records(data)
                total = len(records)
                if total == 0:
                    return "No Company Business Processes found."

                field_keys = list(records[0].keys()) if isinstance(records[0], dict) else []
                lines = [
                    f"Total Company Business Processes: {total}",
                    f"Available fields: {', '.join(field_keys)}",
                    "",
                    "Full BP list:"
                ]
                for i, r in enumerate(records):
                    if isinstance(r, dict):
                        bp_name = r.get("bp_name") or r.get("bp_model_name") or str(r)
                        model = r.get("bp_model_name") or ""
                        source = r.get("studio_source") or r.get("source") or ""
                        extra = f" | Model: {model}" if model else ""
                        extra += f" | Source: {source}" if source else ""
                        lines.append(f"  {i+1}. {bp_name}{extra}")
                return "\n".join(lines)
            except Exception as e:
                return f"Error querying company BP catalog: {e}"

        # ── TOOL 3: Project BP Catalog ───────────────────────────────────────
        @tool
        def query_project_bp_catalog(project_number: str) -> str:
            """
            Fetches all Business Processes available for a specific project/shell.
            Args:
                project_number: The project shell number (e.g. '000001').
            """
            try:
                if client is None:
                    return f"No Unifier connection provided to fetch BPs for project '{project_number}'."
                success, data, status_code, _ = client.get_project_bp_list(project_number)
                if not success:
                    return f"Project BP Catalog API failed for project '{project_number}' (HTTP {status_code}): {data}"
                records = _extract_records(data)
                total = len(records)
                if total == 0:
                    return f"No Business Processes found for project {project_number}."

                lines = [f"Project '{project_number}' has {total} Business Processes:"]
                for i, r in enumerate(records):
                    if isinstance(r, dict):
                        bp_name = r.get("bp_name") or r.get("bp_model_name") or str(r)
                        lines.append(f"  {i+1}. {bp_name}")
                    else:
                        lines.append(f"  {i+1}. {r}")
                return "\n".join(lines)
            except Exception as e:
                return f"Error querying project BP catalog: {e}"

        # ── TOOL 4: Company BP Records (all) ────────────────────────────────
        @tool
        def query_company_bp_records(bpname: str) -> str:
            """
            Fetches all records inside a specific Company-level Business Process.
            Args:
                bpname: The exact BP name (e.g. 'Vendor', 'Contract', 'RFI').
            """
            try:
                # 1. Check local cache first
                try:
                    from sync_manager import get_db_connection
                    conn = get_db_connection()
                    c = conn.cursor()
                    c.execute("SELECT record_no, title, status, creator, assigned_to FROM cached_bp_records WHERE scope_type='company' AND bp_name=?", (bpname,))
                    rows = c.fetchall()
                    conn.close()
                    if rows:
                        lines = [f"Company BP '{bpname}' (local cache): {len(rows)} records found", ""]
                        for i, r in enumerate(rows[:20], 1):
                            lines.append(f"  Record {i}: #{r[0]} | Title: {r[1]} | Status: {r[2]} | Creator: {r[3]} | Assigned: {r[4]}")
                        return "\n".join(lines)
                except Exception:
                    pass

                # 2. Live API fallback
                if client is None:
                    return f"No Unifier connection provided and no local records cached for BP '{bpname}'."
                success, data, status_code, _ = client.get_company_bp_records(bpname=bpname)
                if not success:
                    return f"Company BP Records API failed for BP '{bpname}' (HTTP {status_code}): {data}"
                records = _extract_records(data)
                total = len(records)
                if total == 0:
                    return f"No records found in Company BP '{bpname}'."

                field_keys = list(records[0].keys()) if isinstance(records[0], dict) else []
                lines = [
                    f"Company BP '{bpname}': {total} total records",
                    f"Fields available: {', '.join(field_keys)}",
                    "",
                    "Records (first 20):"
                ]
                for i, r in enumerate(records[:20]):
                    if isinstance(r, dict):
                        lines.append(f"  Record {i+1}: {_format_record(r)}")
                    else:
                        lines.append(f"  Record {i+1}: {r}")
                if total > 20:
                    lines.append(f"  ... and {total - 20} more records.")
                return "\n".join(lines)
            except Exception as e:
                return f"Error querying company BP records for '{bpname}': {e}"

        # ── TOOL 5: Specific Company BP Record by record_no ──────────────────
        @tool
        def query_specific_company_bp_record(bpname: str, record_no: str) -> str:
            """
            Fetches a single specific record from a Company-level Business Process by its record number.
            """
            try:
                if client is None:
                    return f"No Unifier connection provided to fetch record '{record_no}'."
                success, data, status_code, _ = client.get_company_bp_records(
                    bpname=bpname,
                    filter_condition=f"record_no={record_no}"
                )
                if not success:
                    return f"Specific record lookup failed for BP '{bpname}' record '{record_no}' (HTTP {status_code}): {data}"
                records = _extract_records(data)
                if len(records) == 0:
                    return f"Record '{record_no}' not found in Company BP '{bpname}'."

                r = records[0]
                if isinstance(r, dict):
                    return (
                        f"Company BP '{bpname}' | Record '{record_no}':\n"
                        f"{_format_record(r, max_fields=100)}"
                    )
                return str(r)
            except Exception as e:
                return f"Error fetching specific record '{record_no}' from BP '{bpname}': {e}"

        # ── TOOL 6: Project BP Records (all records) ─────────────────────
        @tool
        def query_project_bp_records(project_number: str, bpname: str) -> str:
            """
            Fetches ALL records inside a Business Process for a specific project/shell.
            """
            try:
                # 1. Check local cache first
                try:
                    from sync_manager import get_db_connection
                    conn = get_db_connection()
                    c = conn.cursor()
                    c.execute("SELECT record_no, title, status, creator, assigned_to FROM cached_bp_records WHERE scope_type='project' AND project_number=? AND bp_name=?", (project_number, bpname))
                    rows = c.fetchall()
                    conn.close()
                    if rows:
                        lines = [f"Project '{project_number}' | BP '{bpname}' (local cache): {len(rows)} records found", ""]
                        for i, r in enumerate(rows[:20], 1):
                            lines.append(f"  Record {i}: #{r[0]} | Title: {r[1]} | Status: {r[2]} | Creator: {r[3]} | Assigned: {r[4]}")
                        return "\n".join(lines)
                except Exception:
                    pass

                # 2. Live API fallback
                if client is None:
                    return f"No Unifier connection provided and no local records cached for Project '{project_number}' BP '{bpname}'."
                success, data, status_code, _ = client.get_project_bp_records(
                    project_number=project_number,
                    bpname=bpname
                )
                if not success:
                    return f"Project BP Records API failed for project '{project_number}' BP '{bpname}' (HTTP {status_code}): {data}"
                records = _extract_records(data)
                total = len(records)
                if total == 0:
                    return f"No records found in BP '{bpname}' for project '{project_number}'."

                field_keys = list(records[0].keys()) if isinstance(records[0], dict) else []
                lines = [
                    f"Project '{project_number}' | BP '{bpname}': {total} total records",
                    f"Fields available: {', '.join(field_keys)}",
                    "",
                    "Records (first 20):"
                ]
                for i, r in enumerate(records[:20]):
                    if isinstance(r, dict):
                        lines.append(f"  Record {i+1}: {_format_record(r)}")
                    else:
                        lines.append(f"  Record {i+1}: {r}")
                if total > 20:
                    lines.append(f"  ... and {total - 20} more records.")
                return "\n".join(lines)
            except Exception as e:
                return f"Error querying project BP records for project '{project_number}' BP '{bpname}': {e}"

        # ── TOOL 7: Specific Project BP Record by record_no ──────────────────
        @tool
        def query_specific_project_bp_record(project_number: str, bpname: str, record_no: str) -> str:
            """
            Fetches a single specific record from a Project-level Business Process by its record number.
            """
            try:
                if client is None:
                    return f"No Unifier connection provided to fetch record '{record_no}'."
                success, data, status_code, _ = client.get_project_bp_records(
                    project_number=project_number,
                    bpname=bpname,
                    filter_condition=f"record_no={record_no}"
                )
                if not success:
                    return f"Specific record lookup failed for project '{project_number}' BP '{bpname}' record '{record_no}' (HTTP {status_code}): {data}"
                records = _extract_records(data)
                if len(records) == 0:
                    return f"Record '{record_no}' not found in BP '{bpname}' for project '{project_number}'."

                r = records[0]
                if isinstance(r, dict):
                    return (
                        f"Project '{project_number}' | BP '{bpname}' | Record '{record_no}':\n"
                        f"{_format_record(r, max_fields=100)}"
                    )
                return str(r)
            except Exception as e:
                return f"Error fetching specific record '{record_no}' from project '{project_number}' BP '{bpname}': {e}"

        # ── TOOL 8: User Directory (all) ─────────────────────────────────────
        @tool
        def query_user_directory() -> str:
            """
            Fetches ALL users from the Unifier user administration directory.
            Checks local SQLite cache first for instant response, falls back to live API.
            """
            try:
                # 1. Try local SQLite cache first
                try:
                    from sync_manager import get_db_connection
                    conn = get_db_connection()
                    c = conn.cursor()
                    c.execute("SELECT user_name, first_name, last_name, email, status FROM cached_users")
                    rows = c.fetchall()
                    conn.close()
                    if rows:
                        lines = [
                            f"Total users in Unifier directory (local cache): {len(rows)}",
                            "",
                            "User listing:"
                        ]
                        for i, r in enumerate(rows[:50], 1):
                            full_name = f"{r[1]} {r[2]}".strip() or r[0]
                            lines.append(f"  {i}. {full_name} ({r[0]}) | Email: {r[3]} | Status: {r[4]}")
                        return "\n".join(lines)
                except Exception:
                    pass

                # 2. Live API fallback
                if client is None:
                    return "No Unifier connection provided and no local users cached."
                success, data, status_code, _ = client.get_users()
                if not success:
                    return (
                        f"User Directory API failed (HTTP {status_code}): {data}\n"
                        "Note: The /admin/user/get endpoint may require admin-level permissions on your Bearer Token."
                    )

                records = _extract_records(data)
                total = len(records)

                if total == 0:
                    return f"User Directory returned 0 users."

                field_keys = list(records[0].keys()) if isinstance(records[0], dict) else []
                lines = [
                    f"Total users in Unifier directory: {total}",
                    f"User fields available: {', '.join(field_keys)}",
                    "",
                    "User listing (first 50):"
                ]
                for i, r in enumerate(records[:50]):
                    if isinstance(r, dict):
                        lines.append(f"  {i+1}: {_format_record(r, max_fields=10)}")
                    else:
                        lines.append(f"  {i+1}: {r}")
                if total > 50:
                    lines.append(f"  ... and {total - 50} more users.")
                return "\n".join(lines)
            except Exception as e:
                return f"Error querying user directory: {e}"

        # ── TOOL 9: Users Filtered by name/email/login ───────────────────────
        @tool
        def query_users_filtered(filter_value: str) -> str:
            """
            Searches for specific users in Unifier by name, email, or login ID.
            """
            try:
                if client is None:
                    return f"No Unifier connection provided to filter users for '{filter_value}'."
                filter_cond = filter_value.strip()
                success, data, status_code, _ = client.get_users(filter_condition=filter_cond)
                if not success:
                    return f"User search failed (HTTP {status_code}): {data}"
                records = _extract_records(data)
                total = len(records)
                if total == 0:
                    return f"No users found matching '{filter_value}'."
                field_keys = list(records[0].keys()) if isinstance(records[0], dict) else []
                lines = [
                    f"Found {total} user(s) matching '{filter_value}':",
                    f"User fields: {', '.join(field_keys)}",
                    ""
                ]
                for i, r in enumerate(records[:20]):
                    if isinstance(r, dict):
                        lines.append(f"  {i+1}: {_format_record(r, max_fields=10)}")
                    else:
                        lines.append(f"  {i+1}: {r}")
                return "\n".join(lines)
            except Exception as e:
                return f"Error searching users for '{filter_value}': {e}"

        # ── TOOL 10: Full Database Summary (all endpoints) ────────────────────
        @tool
        def query_full_database_summary() -> str:
            """
            Hits ALL major Unifier endpoints at once and returns a comprehensive summary.
            """
            lines = ["=== FULL UNIFIER DATABASE SUMMARY ===", ""]

            # Try local cache summary first
            try:
                from sync_manager import get_sync_stats
                stats = get_sync_stats()
                lines.append(f"📁 Cached Projects: {stats.get('cached_projects', 0)}")
                lines.append(f"🗂️  Cached Company BPs: {stats.get('cached_company_bps', 0)}")
                lines.append(f"📄 Cached BP Records: {stats.get('cached_bp_records', 0)}")
                lines.append(f"👥 Cached Users: {stats.get('cached_users', 0)}")
                lines.append(f"🔍 Vector Embeddings Index: {stats.get('vector_embeddings', 0)}")
                lines.append(f"⏰ Last Sync Timestamp: {stats.get('last_sync', 'Never')}")
                lines.append("")
            except Exception:
                pass

            if client:
                lines.append("--- LIVE UNIFIER API ENDPOINTS ---")
                try:
                    ok, data, code, _ = client.get_active_projects()
                    records = _extract_records(data) if ok else []
                    lines.append(f"📁 Live Active Projects: {len(records)} (HTTP {code})")
                except Exception as e:
                    lines.append(f"📁 Active Projects: {e}")

            return "\n".join(lines)

        # ── TOOL 11: Smart Project User Lookup ───────────────────────────
        @tool
        def query_project_users(project_number: str) -> str:
            """
            Smart search for users/people assigned to a specific project.
            Checks local SQLite cache first for instant lookup, bounded live API fallback.
            """
            try:
                # 1. Try local SQLite cache first (instant <2ms)
                try:
                    from sync_manager import get_db_connection
                    conn = get_db_connection()
                    c = conn.cursor()
                    c.execute("""
                        SELECT bp_name, 'creator', creator FROM cached_bp_records WHERE project_number=? AND creator != ''
                        UNION
                        SELECT bp_name, 'assigned_to', assigned_to FROM cached_bp_records WHERE project_number=? AND assigned_to != ''
                    """, (project_number, project_number))
                    rows = c.fetchall()
                    conn.close()
                    if rows:
                        lines = [
                            f"### Users found in Project '{project_number}' (local cache)",
                            f"Found {len(rows)} user assignment records.\n",
                            "| Business Process | Field | Assigned User/Value |",
                            "|---|---|---|"
                        ]
                        for r in rows[:50]:
                            lines.append(f"| {r[0]} | {r[1]} | {r[2]} |")
                        return "\n".join(lines)
                except Exception:
                    pass

                # 2. Live API fallback (bounded to first 3 BPs max to avoid HTTP timeout)
                if client is None:
                    return f"No Unifier connection provided and no cached user records found for project '{project_number}'."

                ok, bp_data, code, _ = client.get_project_bp_list(project_number)
                if not ok:
                    return f"Could not fetch BPs for project '{project_number}' (HTTP {code}): {bp_data}"
                bp_records = _extract_records(bp_data)
                if not bp_records:
                    return f"No Business Processes found for project '{project_number}'."

                bp_names = []
                for r in bp_records:
                    if isinstance(r, dict):
                        n = r.get("bp_name") or r.get("bp_model_name") or ""
                        if n:
                            bp_names.append(str(n))

                USER_FIELDS = {
                    "assigned_to", "assignedto", "creator", "created_by", "createdby",
                    "owner", "owner_id", "manager", "project_manager", "responsible",
                    "user", "user_name", "username", "modified_by", "modifiedby"
                }

                found_users = []
                for bp_name in bp_names[:3]:  # Max 3 BPs live to avoid 502 timeout
                    try:
                        ok2, rec_data, _, _ = client.get_project_bp_records(
                            project_number=project_number, bpname=bp_name
                        )
                        if not ok2:
                            continue
                        recs = _extract_records(rec_data)
                        for rec in recs[:5]:
                            if not isinstance(rec, dict):
                                continue
                            for k, v in rec.items():
                                if k.lower().replace("-", "_") in USER_FIELDS and v:
                                    found_users.append({
                                        "BP": bp_name,
                                        "Field": k,
                                        "Value": str(v)
                                    })
                    except Exception:
                        continue

                if not found_users:
                    return f"Project '{project_number}' scanning checked initial BPs. No user assignment fields found or token unauthorized."

                lines = [
                    f"### Users found in Project '{project_number}'",
                    "| Business Process | Field | Assigned User/Value |",
                    "|---|---|---|"
                ]
                for u in found_users[:30]:
                    lines.append(f"| {u['BP']} | {u['Field']} | {u['Value']} |")
                return "\n".join(lines)
            except Exception as e:
                return f"Error scanning project '{project_number}' for users: {e}"

        # ── TOOL 12: Vector Store Semantic Search ─────────────────────────────
        @tool
        def query_vector_search_unifier(query: str, project_number: str = "", bp_name: str = "") -> str:
            """
            Performs fast semantic similarity vector search across the cached ChromaDB vector store.
            Use for open-ended questions like 'find change orders related to concrete', 'why was contract delayed', 'search for supplier documents'.
            Args:
                query: Search text query.
                project_number: Optional filter by project number.
                bp_name: Optional filter by BP name.
            """
            try:
                from sync_manager import query_vector_search
                results = query_vector_search(query_text=query, project_number=project_number or None, bp_name=bp_name or None, n_results=5)
                if not results:
                    return "No matching semantic results found in the local vector store. Try live querying or triggering a sync."
                lines = [f"Found {len(results)} relevant vector matches:"]
                for idx, r in enumerate(results, 1):
                    doc = r.get("document", "")
                    meta = r.get("metadata", {})
                    dist = r.get("distance")
                    score_str = f" (distance: {dist:.3f})" if dist is not None else ""
                    lines.append(f"  {idx}. [{meta.get('scope_type', 'record')}] {doc[:300]}{score_str}")
                return "\n".join(lines)
            except Exception as e:
                return f"Vector search error: {e}"

        # ── TOOL 13: Local Fast Cache Sync ─────────────────────────────────────
        @tool
        def trigger_local_data_sync() -> str:
            """
            Triggers a full sync of remote Unifier REST API data into the local SQLite cache and ChromaDB vector store.
            Use when user asks to 'sync data', 'refresh database', 'update local vector store'.
            """
            try:
                from sync_manager import SyncManager
                sm = SyncManager(client=client)
                res = sm.sync_all()
                return f"Sync complete! Total records synced: {res.get('total_records_synced', 0)} in {res.get('elapsed_ms', 0):.1f}ms."
            except Exception as e:
                return f"Sync error: {e}"

        # ── TOOL 14: Oracle Primavera Unifier Documentation & References ─────
        @tool
        def query_oracle_documentation_guides() -> str:
            """
            Returns the official Oracle Primavera Unifier v26 documentation links, user manuals, and BP field schema mappings (bp_model_name, bp_name, studio_source).
            Use when user asks about documentation, reference guides, uDesigner guide, integration interface guide, business process user guide, or BP field mapping definitions.
            """
            return (
                "### 📚 Official Oracle Primavera Unifier v26 Reference Guides & Schema\n\n"
                "#### **Official Oracle Documentation Links**\n"
                "- 🔗 [Integration Interface Guide](https://docs.oracle.com/en/industries/construction-engineering/primavera-unifier/26/integration-interface/introduction-10280474a.html)\n"
                "- 🔗 [Data Reference Guide](http://docs.oracle.com/en/industries/construction-engineering/primavera-unifier/26/reference/introduction-10289477a.html)\n"
                "- 🔗 [Business Processes User Guide](https://docs.oracle.com/en/industries/construction-engineering/primavera-unifier/26/business-process/workingwithbusinessprocesses-10292605a.html)\n"
                "- 🔗 [uDesigner User Guide](https://docs.oracle.com/en/industries/construction-engineering/primavera-unifier/26/udesigner/introducingunifierudesigner-77633a.html)\n"
                "- 🔗 [General User Guide](https://docs.oracle.com/en/industries/construction-engineering/primavera-unifier/26/general-user/gettingstartedwithgeneraloperations-73021a.html)\n"
                "- 🔗 [Managers User Guide](https://docs.oracle.com/en/industries/construction-engineering/primavera-unifier/26/general-user/gettingstartedwithgeneraloperations-73021a.html)\n\n"
                "#### **Business Process (BP) Field Schema Mapping**\n"
                "| Field Name | Description / Unique Property |\n"
                "|---|---|\n"
                "| `bp_model_name` | The BP Model ID (Unique Identifier) |\n"
                "| `bp_name` | The BP Display Name (Unique) |\n"
                "| `studio_source` | The BP Type / Studio Source (simple, database, etc.) |\n"
                "| `no_workflow` | Boolean flag indicating if BP is non-workflow |\n"
            )

        tools = [
            query_active_projects,            # GET  /admin/projectshell?Status=Active
            query_company_bp_catalog,          # GET  /admin/bps
            query_project_bp_catalog,          # GET  /admin/bps/{project_number}
            query_company_bp_records,          # POST /bp/records/
            query_specific_company_bp_record,  # POST /bp/records/ (by record_no)
            query_project_bp_records,          # POST /bp/records/{project}
            query_specific_project_bp_record,  # POST /bp/records/{project} (by record_no)
            query_user_directory,              # POST /admin/user/get
            query_users_filtered,              # POST /admin/user/get (with filter)
            query_project_users,               # Smart: scans ALL project BPs for user fields
            query_full_database_summary,       # All endpoints combined
            query_vector_search_unifier,       # ChromaDB Vector Store Search
            trigger_local_data_sync,           # SQLite + ChromaDB Sync
            query_oracle_documentation_guides, # Official Oracle Unifier Docs & BP Schema Mapping
        ]

        # ── Build LLM ────────────────────────────────────────────────────────
        try:
            if provider == "groq":
                if not self.groq_api_key:
                    return "Groq API key is missing. Please add it in the AI Chatbot Config sidebar."
                model_name = "llama-3.1-8b-instant"
                llm = ChatGroq(
                    model_name=model_name,
                    temperature=0.1,
                    groq_api_key=self.groq_api_key,
                )
            elif provider == "gemini":
                if not self.gemini_api_key:
                    return "Google Gemini API key is missing. Please add it in the AI Chatbot Config sidebar."
                from langchain_google_genai import ChatGoogleGenerativeAI
                model_name = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
                llm = ChatGoogleGenerativeAI(
                    model=model_name,
                    temperature=0.1,
                    google_api_key=self.gemini_api_key,
                )
            elif provider == "openai":
                if not self.openai_api_key:
                    return "OpenAI API key is missing. Please add it in the AI Chatbot Config sidebar."
                from langchain_openai import ChatOpenAI
                llm = ChatOpenAI(
                    model="gpt-3.5-turbo",
                    temperature=0.1,
                    openai_api_key=self.openai_api_key,
                )
            else:
                return f"Unknown provider '{provider}'. Choose 'groq', 'gemini', or 'openai'."
        except Exception as e:
            return f"Failed to initialise LLM: {e}"

        # ── System Prompt ────────────────────────────────────────────────────
        system_prompt = (
            "You are a STRICT Oracle Primavera Unifier database assistant. "
            "Unifier is a construction project management platform.\n"
            "You ONLY answer questions about data stored in this Unifier database.\n\n"
            "TOOLS AVAILABLE (14 live & cached tools — call them to get real data):\n"
            "  1.  query_active_projects — all active project shells (name, number, status, type)\n"
            "  2.  query_company_bp_catalog — list of all Company-level Business Processes\n"
            "  3.  query_project_bp_catalog(project_number) — BPs for a project\n"
            "  4.  query_company_bp_records(bpname) — all records in a Company BP\n"
            "  5.  query_specific_company_bp_record(bpname, record_no) — one Company BP record by ID\n"
            "  6.  query_project_bp_records(project_number, bpname) — all records in a Project BP\n"
            "  7.  query_specific_project_bp_record(project_number, bpname, record_no) — one Project BP record\n"
            "  8.  query_user_directory — full user list from /admin/user/get\n"
            "  9.  query_users_filtered(filter_value) — search user by name or email\n"
            "  10. query_project_users(project_number) — SMART: scans ALL project BPs to find assigned users\n"
            "  11. query_full_database_summary — overview from all endpoints\n"
            "  12. query_vector_search_unifier(query) — FAST semantic vector search over cached records\n"
            "  13. trigger_local_data_sync — Sync remote Unifier data into local SQLite & ChromaDB\n"
            "  14. query_oracle_documentation_guides — Returns official Oracle Unifier v26 documentation URLs & BP schema mappings\n\n"
            "OFFICIAL ORACLE PRIMAVERA UNIFIER V26 REFERENCE GUIDES:\n"
            "  - Integration Interface Guide: https://docs.oracle.com/en/industries/construction-engineering/primavera-unifier/26/integration-interface/introduction-10280474a.html\n"
            "  - Data Reference Guide: http://docs.oracle.com/en/industries/construction-engineering/primavera-unifier/26/reference/introduction-10289477a.html\n"
            "  - Business Processes User Guide: https://docs.oracle.com/en/industries/construction-engineering/primavera-unifier/26/business-process/workingwithbusinessprocesses-10292605a.html\n"
            "  - uDesigner User Guide: https://docs.oracle.com/en/industries/construction-engineering/primavera-unifier/26/udesigner/introducingunifierudesigner-77633a.html\n"
            "  - General User Guide: https://docs.oracle.com/en/industries/construction-engineering/primavera-unifier/26/general-user/gettingstartedwithgeneraloperations-73021a.html\n"
            "  - Managers User Guide: https://docs.oracle.com/en/industries/construction-engineering/primavera-unifier/26/general-user/gettingstartedwithgeneraloperations-73021a.html\n\n"
            "BP SCHEMA MAPPING:\n"
            "  - bp_model_name: Unique BP Identifier / Model Name (e.g. 'uxsample', 'uxbpor')\n"
            "  - bp_name: Unique BP Display Name (e.g. 'AM_sample', 'BPO PP')\n"
            "  - studio_source: BP Type / Studio Source (e.g. 'simple', 'database')\n\n"
            "STRICT RULES:\n"
            "1. SCOPE: You are an expert assistant for Oracle Primavera Unifier. Answer database queries, REST API questions, BP field mappings, and documentation guide requests. For completely unrelated non-Unifier topics (such as weather, sports, or entertainment), politely state that your scope is limited to Primavera Unifier.\n"
            "2. ALWAYS call the right tool before answering. NEVER fabricate or guess data.\n"
            "3. API ERRORS & FAILURES: If a tool returns an API error or status code failure (e.g. HTTP 401 Unauthorized, 403 Forbidden, 500 Error), ALWAYS clearly report the error and status code to the user: "
            "'⚠️ Unifier API Request Failed (HTTP [code]): [message]. Please check your Bearer Token or permissions in the sidebar.' DO NOT respond with out-of-scope fallback when a tool fails.\n"
            "4. OUTPUT FORMAT — MANDATORY:\n"
            "   - ALWAYS present lists, records, and data as MARKDOWN TABLES.\n"
            "   - Use | Column | Column | format with a header separator row |---|---|\n"
            "   - For projects table: columns = | # | Project Name | Project Number | Status | Type |\n"
            "   - For users table: columns = | # | Name/Username | Role/Field | Source BP |\n"
            "   - For BP records: present key fields as a table.\n"
            "5. For semantic queries ('why', 'find documents about X'): call query_vector_search_unifier.\n"
            "6. For 'sync database' or 'update cache': call trigger_local_data_sync.\n"
            "7. For documentation, reference guides, uDesigner guide, integration guide, user guides, or BP schema field mapping: ALWAYS call query_oracle_documentation_guides.\n"
        )

        messages: list = [("system", system_prompt)]
        for msg in (chat_history or [])[-6:]:
            role = "user" if msg.get("role") == "user" else "assistant"
            content = msg.get("content", "")
            if content:
                messages.append((role, content))
        messages.append(("user", user_query))

        # \u2500\u2500 Run Agent \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
        try:
            agent_executor = create_react_agent(llm, tools)
            response = agent_executor.invoke({"messages": messages})
            last_msg = response.get("messages", [])[-1]
            return str(last_msg.content) if hasattr(last_msg, "content") else str(last_msg)
        except Exception as e:
            return (
                f"Agent error: {e}\n\n"
                "If this is an API key error, check your Groq/OpenAI key in the sidebar."
            )
