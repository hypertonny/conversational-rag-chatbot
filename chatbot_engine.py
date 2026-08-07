"""
chatbot_engine.py — Agentic RAG Engine for Primavera Unifier Portal
Fixed bugs:
  1. Docstring was placed AFTER the early return, making it dead code.
  2. get_engine() in test_connection ingested into keyless engine; chat used keyed engine - different cache objects.
  3. names list could contain None values causing join() to crash.
  4. Missing try/except around LangGraph agent, returning raw exceptions to frontend.
  5. ingest_json_data no longer needed in agent flow - removed dead code.
"""
import os
from typing import List, Dict, Any, Optional

from langchain_groq import ChatGroq


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

        @tool
        def query_active_projects() -> str:
            """Fetches ALL active projects from Primavera Unifier. Use this when user asks about projects, project count, or list of projects."""
            try:
                success, data, _, _ = client.get_active_projects()
                if not success:
                    return f"API call failed: {data}"
                records = data.get("data", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
                total = len(records)
                samples = []
                for r in records[:20]:
                    if isinstance(r, dict):
                        name = r.get("projectname") or r.get("name") or ""
                        num = r.get("projectnumber") or r.get("project_number") or ""
                        entry = f"{name} (#{num})" if (name and num) else (name or num or str(r))
                        samples.append(entry)
                return (
                    f"Total active projects in the Unifier database: {total}.\n"
                    f"Sample projects: {', '.join(samples) if samples else 'none available'}."
                )
            except Exception as e:
                return f"Error querying active projects: {e}"

        @tool
        def query_company_bp_catalog() -> str:
            """Fetches the master list of all Company-level Business Processes (BPs) in Unifier. Use when user asks about company BPs or available business processes."""
            try:
                success, data, _, _ = client.get_company_bp_list()
                if not success:
                    return f"API call failed: {data}"
                records = data.get("data", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
                names = [str(r.get("bp_name") or r.get("bp_model_name") or "") for r in records if isinstance(r, dict)]
                names = [n for n in names if n]
                return (
                    f"Total Company Business Processes: {len(records)}.\n"
                    f"BP Names: {', '.join(names[:60]) if names else 'none available'}."
                )
            except Exception as e:
                return f"Error querying company BP catalog: {e}"

        @tool
        def query_project_bp_catalog(project_number: str) -> str:
            """Fetches the Business Processes for a specific project. Use when user asks about BPs for a specific project number. Args: project_number (str): e.g. '000001'"""
            try:
                success, data, _, _ = client.get_project_bp_list(project_number)
                if not success:
                    return f"API call failed for project {project_number}: {data}"
                records = data.get("data", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
                names = [str(r.get("bp_name") or r.get("bp_model_name") or "") for r in records if isinstance(r, dict)]
                names = [n for n in names if n]
                return (
                    f"Project {project_number} has {len(records)} Business Processes.\n"
                    f"BP Names: {', '.join(names[:60]) if names else 'none available'}."
                )
            except Exception as e:
                return f"Error querying project BP catalog: {e}"

        @tool
        def query_company_bp_records(bpname: str) -> str:
            """Fetches records inside a specific Company BP. Use when user asks about records in a BP like 'Vendor' or 'Contract'. Args: bpname (str): BP name e.g. 'Vendor'"""
            try:
                success, data, _, _ = client.get_company_bp_records(bpname)
                if not success:
                    return f"API call failed for BP '{bpname}': {data}"
                records = data.get("data", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
                return (
                    f"Company BP '{bpname}' contains {len(records)} records.\n"
                    f"Sample records: {str(records[:5]) if records else 'no records found'}."
                )
            except Exception as e:
                return f"Error querying company BP records for '{bpname}': {e}"

        @tool
        def query_user_directory() -> str:
            """Fetches the Unifier user administration directory. Use when user asks about users, admins, or user list."""
            try:
                success, data, _, _ = client.get_users()
                if not success:
                    return f"API call failed: {data}"
                records = data.get("data", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
                samples = []
                for r in records[:10]:
                    if isinstance(r, dict):
                        name = r.get("user_name") or r.get("first_name") or r.get("email") or ""
                        if name:
                            samples.append(name)
                return (
                    f"Total users in Unifier directory: {len(records)}.\n"
                    f"Sample users: {', '.join(samples) if samples else 'none available'}."
                )
            except Exception as e:
                return f"Error querying user directory: {e}"

        tools = [
            query_active_projects,
            query_company_bp_catalog,
            query_project_bp_catalog,
            query_company_bp_records,
            query_user_directory,
        ]

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

        system_prompt = (
            "You are a helpful AI assistant for Oracle Primavera Unifier.\n"
            "You have access to tools that query the live Unifier database in real-time.\n\n"
            "RULES:\n"
            "1. For casual greetings (hi, hello, how are you), respond warmly and ask how you can help.\n"
            "2. For ANY data question (projects, BPs, users, counts, records), ALWAYS call the appropriate "
            "tool first to fetch live data. Never guess or fabricate data.\n"
            "3. Summarise the tool results clearly and concisely for the user.\n"
            "4. If a tool fails, explain what went wrong and suggest the user check their connection.\n"
        )

        messages: list = [("system", system_prompt)]
        for msg in (chat_history or [])[-6:]:
            role = "user" if msg.get("role") == "user" else "assistant"
            content = msg.get("content", "")
            if content:
                messages.append((role, content))
        messages.append(("user", user_query))

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
