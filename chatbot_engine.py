"""
chatbot_engine.py — Agentic RAG Engine for Primavera Unifier Portal
7 comprehensive tools covering ALL Unifier endpoints:
  1. query_active_projects         — all project shells (full detail)
  2. query_company_bp_catalog      — all Company BPs
  3. query_project_bp_catalog      — BPs for a specific project
  4. query_company_bp_records      — records inside a Company BP
  5. query_project_bp_records      — records inside a Project BP (was missing!)
  6. query_user_directory          — full user list with ALL fields + raw debug
  7. query_full_database_summary   — hits every endpoint and returns combined overview
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

        # ── TOOL 4: Company BP Records ───────────────────────────────────────
        @tool
        def query_company_bp_records(bpname: str) -> str:
            """
            Fetches all records inside a specific Company-level Business Process by name.
            Returns count and full detail of all records including all fields.
            Use when user asks about records in a company BP like 'Vendor', 'Contract', 'Invoice'.
            Args:
                bpname: The exact BP name (e.g. 'Vendor', 'Contract', 'RFI').
            """
            try:
                success, data, status_code, _ = client.get_company_bp_records(bpname)
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

        # ── TOOL 5: Project BP Records ───────────────────────────────────────
        @tool
        def query_project_bp_records(project_number: str, bpname: str) -> str:
            """
            Fetches all records inside a specific Business Process for a specific project.
            Returns count and full detail of every record including all fields.
            Use when user asks about records in a BP within a specific project.
            Args:
                project_number: The project number (e.g. '000001').
                bpname: The BP name (e.g. 'Contract', 'RFI', 'Submittal').
            """
            try:
                success, data, status_code, _ = client.get_project_bp_records(project_number, bpname)
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

        # ── TOOL 6: User Directory ───────────────────────────────────────────
        @tool
        def query_user_directory() -> str:
            """
            Fetches ALL users from the Unifier user administration directory.
            Returns total count and every user with ALL fields: user_name, first_name, last_name, email, status, roles, etc.
            Also returns raw API response preview if users list is empty, for debugging.
            Use when user asks about users, people, admins, assigned users, user count, or user list.
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

        # ── TOOL 7: Full Database Summary ─────────────────────────────────────
        @tool
        def query_full_database_summary() -> str:
            """
            Hits ALL Unifier endpoints at once and returns a comprehensive summary:
            active projects, company BPs, and user directory combined.
            Use when user asks for a general overview, 'all data', 'everything', or 'what information do you have'.
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
            query_active_projects,
            query_company_bp_catalog,
            query_project_bp_catalog,
            query_company_bp_records,
            query_project_bp_records,
            query_user_directory,
            query_full_database_summary,
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
            "You are a knowledgeable AI assistant for Oracle Primavera Unifier.\n"
            "You have 7 tools that query the live Unifier database in real-time:\n"
            "  1. query_active_projects — all project shells with full field details\n"
            "  2. query_company_bp_catalog — all Company-level Business Processes\n"
            "  3. query_project_bp_catalog(project_number) — BPs for a specific project\n"
            "  4. query_company_bp_records(bpname) — all records inside a Company BP\n"
            "  5. query_project_bp_records(project_number, bpname) — records inside a Project BP\n"
            "  6. query_user_directory — complete user list with all field details\n"
            "  7. query_full_database_summary — overview from ALL endpoints at once\n\n"
            "RULES:\n"
            "1. Always greet the user warmly for casual messages.\n"
            "2. For ANY data question, ALWAYS call the appropriate tool(s) first. NEVER guess.\n"
            "3. Report results clearly — include counts, field names, and specific values.\n"
            "4. If a tool returns raw field names, report them so the user knows what is available.\n"
            "5. If asked about users in a project, call query_user_directory to get all users. "
            "Then explain that project-specific user assignments may be inside BP records.\n"
            "6. Never fabricate field values, record counts, or project names.\n"
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
