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
    ):
        self.openai_api_key = openai_api_key or ""
        self.groq_api_key = groq_api_key or ""

    def is_ready(self) -> bool:
        return bool(self.openai_api_key or self.groq_api_key)

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
                "Chatbot is not ready. Please provide a Groq or OpenAI API Key "
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
            Returns total count, all project names, numbers, status, type, and every available field.
            Use when user asks about projects, project count, project list, or any project detail.
            """
            try:
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
            Fetches the complete master list of all Company-level Business Processes (BPs) in Unifier.
            Returns all BP names, model names, studio sources and all available fields.
            Use when user asks about company BPs, available business processes, or BP catalog.
            """
            try:
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
            Returns all BP names and fields for that project.
            Use when user asks about BPs for a specific project number.
            Args:
                project_number: The project shell number (e.g. '000001').
            """
            try:
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
            Endpoint: POST /bp/records/
            Returns full detail including all fields, line items, comments and attachments.
            Use when user asks about all records in a company BP like 'Vendor', 'Contract', 'Invoice'.
            NOTE: To look up ONE specific record by ID, use query_specific_company_bp_record instead.
            Args:
                bpname: The exact BP name (e.g. 'Vendor', 'Contract', 'RFI').
            """
            try:
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
            Endpoint: POST /bp/records/ with filter_condition="record_no=<record_no>"
            Use when user asks about a specific record like 'show me Vendor VEN-0000006' or 'find record RFI-0000001'.
            Returns ALL fields, line items, general comments, and file attachments for that record.
            Args:
                bpname: The BP name (e.g. 'Vendor').
                record_no: The record number (e.g. 'VEN-0000006').
            """
            try:
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
            Endpoint: POST /bp/records/{project_number}
            Returns full detail of every record including all fields, line items, comments, attachments.
            Use this to discover who is assigned to a project or what work is being done.
            NOTE: To look up ONE specific record by ID, use query_specific_project_bp_record instead.
            Args:
                project_number: The project number exactly as shown (e.g. '000001', '001', '0000567').
                bpname: The BP name (e.g. 'Contract', 'RFI', 'Submittal', 'Vendor').
            """
            try:
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
            Endpoint: POST /bp/records/{project_number} with filter_condition="record_no=<record_no>"
            Use when user asks about a specific record inside a project BP e.g. 'show me Contract CON-0001 in project 001'.
            Returns ALL fields, line items, comments, and attachment info for that record.
            Args:
                project_number: The project number (e.g. '001').
                bpname: The BP name (e.g. 'Contract').
                record_no: The record number (e.g. 'CON-0000001').
            """
            try:
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
            Endpoint: POST /admin/user/get
            Returns total count and every user with ALL fields: user_name, first_name, last_name, email, status, roles, etc.
            Also returns raw API response preview if users list is empty, for debugging.
            Use when user asks about users, people, admins, user count, or full user list.
            """
            try:
                success, data, status_code, _ = client.get_users()
                if not success:
                    return (
                        f"User Directory API failed (HTTP {status_code}): {data}\n"
                        "Note: The /admin/user/get endpoint may require admin-level permissions on your Bearer Token."
                    )

                records = _extract_records(data)
                total = len(records)

                if total == 0:
                    return (
                        f"User Directory returned 0 users.\n"
                        f"Raw API response (for debugging): {str(data)[:400]}\n\n"
                        "Possible reasons:\n"
                        "  1. The Bearer Token lacks admin/user-read permissions.\n"
                        "  2. The /admin/user/get endpoint requires a filterCondition payload.\n"
                        "  3. Users may be stored in a different endpoint on this Unifier instance."
                    )

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
            Searches for specific users in Unifier by name, email, or login ID using filterCondition.
            Endpoint: POST /admin/user/get with filterCondition payload.
            Use when user asks to find a specific person by name, email, or username.
            Args:
                filter_value: The name, email address, or login to search for (e.g. 'john', 'john@example.com').
            """
            try:
                filter_cond = filter_value.strip()
                success, data, status_code, _ = client.get_users(filter_condition=filter_cond)
                if not success:
                    return f"User search failed (HTTP {status_code}): {data}"
                records = _extract_records(data)
                total = len(records)
                if total == 0:
                    return (
                        f"No users found matching '{filter_value}'.\n"
                        f"Raw response: {str(data)[:200]}"
                    )
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
            Covers: active projects, company BP catalog, user directory.
            Use when user asks for a general overview, 'all data', 'everything', 'what can you tell me',
            or 'summarize the database'.
            """
            lines = ["=== FULL UNIFIER DATABASE SUMMARY ===", ""]

            # 1. Active Projects
            try:
                ok, data, code, _ = client.get_active_projects()
                records = _extract_records(data) if ok else []
                lines.append(f"📁 Active Projects: {len(records)} total (HTTP {code})")
                for r in records[:10]:
                    if isinstance(r, dict):
                        name = r.get("projectname") or r.get("name") or "N/A"
                        num = r.get("projectnumber") or r.get("project_number") or "N/A"
                        lines.append(f"   - {name} (#{num})")
                if len(records) > 10:
                    lines.append(f"   ... and {len(records) - 10} more projects")
                if not ok:
                    lines.append(f"   Error: {data}")
            except Exception as e:
                lines.append(f"📁 Active Projects: Error - {e}")

            lines.append("")

            # 2. Company BPs
            try:
                ok, data, code, _ = client.get_company_bp_list()
                records = _extract_records(data) if ok else []
                bp_names = [str(r.get("bp_name") or r.get("bp_model_name") or r) for r in records if isinstance(r, dict)]
                bp_names = [n for n in bp_names if n]
                lines.append(f"🗂️  Company Business Processes: {len(records)} total (HTTP {code})")
                lines.append(f"   Names: {', '.join(bp_names[:30]) if bp_names else 'none'}")
                if not ok:
                    lines.append(f"   Error: {data}")
            except Exception as e:
                lines.append(f"🗂️  Company BPs: Error - {e}")

            lines.append("")

            # 3. Users
            try:
                ok, data, code, _ = client.get_users()
                records = _extract_records(data) if ok else []
                lines.append(f"👥 Users: {len(records)} total (HTTP {code})")
                for r in records[:10]:
                    if isinstance(r, dict):
                        name = r.get("user_name") or r.get("first_name") or r.get("email") or str(r)
                        lines.append(f"   - {name}")
                if len(records) > 10:
                    lines.append(f"   ... and {len(records) - 10} more users")
                if len(records) == 0:
                    lines.append(f"   Raw response preview: {str(data)[:200]}")
                if not ok:
                    lines.append(f"   Error: {data}")
            except Exception as e:
                lines.append(f"👥 Users: Error - {e}")

            return "\n".join(lines)

        tools = [
            query_active_projects,           # GET  /admin/projectshell?Status=Active
            query_company_bp_catalog,         # GET  /admin/bps
            query_project_bp_catalog,         # GET  /admin/bps/{project_number}
            query_company_bp_records,         # POST /bp/records/              (all + optional filter)
            query_specific_company_bp_record, # POST /bp/records/              (filter by record_no)
            query_project_bp_records,         # POST /bp/records/{project}     (all + optional filter)
            query_specific_project_bp_record, # POST /bp/records/{project}     (filter by record_no)
            query_user_directory,             # POST /admin/user/get
            query_users_filtered,             # POST /admin/user/get           (with filterCondition)
            query_full_database_summary,      # All endpoints combined
        ]

        # ── Build LLM ────────────────────────────────────────────────────────
        try:
            if provider == "groq":
                if not self.groq_api_key:
                    return "Groq API key is missing. Please add it in the AI Chatbot Config sidebar."
                llm = ChatGroq(
                    model_name="llama-3.3-70b-versatile",
                    temperature=0.1,
                    groq_api_key=self.groq_api_key,
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
                return f"Unknown provider '{provider}'. Choose 'groq' or 'openai'."
        except Exception as e:
            return f"Failed to initialise LLM: {e}"

        # ── System Prompt ────────────────────────────────────────────────────
        system_prompt = (
            "You are a STRICT Oracle Primavera Unifier database assistant. "
            "Unifier is a construction project management platform.\n"
            "You ONLY answer questions about data stored in this organisation's Unifier database.\n\n"
            "TOOLS AVAILABLE (10 live tools — call them to get real data):\n"
            "  1. query_active_projects — all active project shells (name, number, status, type)\n"
            "  2. query_company_bp_catalog — list of all Company-level Business Processes\n"
            "  3. query_project_bp_catalog(project_number) — BPs available for a project\n"
            "  4. query_company_bp_records(bpname) — all records in a Company BP\n"
            "  5. query_specific_company_bp_record(bpname, record_no) — one specific Company BP record\n"
            "  6. query_project_bp_records(project_number, bpname) — all records in a Project BP\n"
            "  7. query_specific_project_bp_record(project_number, bpname, record_no) — one specific Project BP record\n"
            "  8. query_user_directory — full user list from /admin/user/get\n"
            "  9. query_users_filtered(filter_value) — search for a specific user by name or email\n"
            " 10. query_full_database_summary — comprehensive overview of all endpoints\n\n"
            "STRICT RULES:\n"
            "1. SCOPE: You ONLY answer questions about this Unifier database. "
            "If asked about anything outside Unifier (news, geography, politics, general knowledge, people outside the system), "
            "respond EXACTLY: 'I can only answer questions about your Primavera Unifier database. "
            "I cannot answer general knowledge questions.'\n"
            "2. ALWAYS call the right tool before answering. NEVER fabricate or guess data.\n"
            "3. For 'users in a project': first call query_project_bp_catalog to find BPs, "
            "then call query_project_bp_records for each BP to find user/assignee fields. "
            "Look for fields named 'assigned_to', 'creator', 'owner', 'user', 'manager', 'responsible'.\n"
            "4. For 'all data' or 'give me everything': call query_full_database_summary.\n"
            "5. For a specific record (record_no given): use query_specific_company_bp_record or query_specific_project_bp_record.\n"
            "6. Report field names and values clearly. If a tool returns an error, report it and suggest checking permissions.\n"
            "7. Temperature=0 mindset: report only what the tools return. Zero invention.\n"
        )

        messages: list = [("system", system_prompt)]
        for msg in (chat_history or [])[-6:]:
            role = "user" if msg.get("role") == "user" else "assistant"
            content = msg.get("content", "")
            if content:
                messages.append((role, content))
        messages.append(("user", user_query))

        # ── Run Agent ────────────────────────────────────────────────────────
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
