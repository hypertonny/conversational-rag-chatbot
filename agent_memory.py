"""
agent_memory.py — Structured conversation memory for the Unifier chatbot.

The frontend replays a raw transcript, but that forces the model to re-parse
entities like a project number out of prior prose on every turn. Instead we keep
a small set of resolved slots per conversation (active project / BP / record) and
inject them into the system prompt, so a follow-up like "tell me the BP record"
resolves against the project the user already established.

Slots are filled deterministically from the tool-call arguments the agent actually
used, not from the printed answer — that reflects what was truly queried. State is
persisted in the same SQLite DB as chat history (data/chats.db).
"""
import os
import re
import json
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

DB_PATH = os.path.join("data", "chats.db")

# Per-conversation lock so concurrent "show more" + new listing can't interleave list_state.
_MEM_LOCK = threading.Lock()

# Tool-argument aliases -> canonical slot.
_PROJECT_ARGS = ("project_number",)
_BP_ARGS = ("bpname", "bp_name")
_RECORD_ARGS = ("record_no",)

# resolve_project prints this on an exact hit — capture the canonical number from the
# RESULT (not just args), so "0000567, what's its name?" then "how many POs in this?"
# reuses the project even though resolve_project's arg is `query`, not `project_number`.
# Accepts single/double quotes and varied phrasing to survive prompt rewording.
_RESOLVED_RES = [
    re.compile(r"project_number '([^']+)': ([^(]+?)\s*\(Status"),
    re.compile(r'project_number "([^"]+)": ([^(]+?)\s*\(Status'),
    re.compile(r"project_number\s*[‘’'\"`]?([A-Za-z0-9][A-Za-z0-9\-_]*)\s*[’'\"`]?\s*:\s*([^(]+?)\s*\(Status", re.IGNORECASE),
    re.compile(r"Exact match\s*[—–-]\s*project_number\s*[‘’'\"`]?([A-Za-z0-9][A-Za-z0-9\-_]*)\s*[’'\"`]?\s*:\s*([^(]+?)\s*\(Status", re.IGNORECASE),
]
# A bare query arg that looks like a project number (e.g. resolve_project(query='0000567')).
_QUERY_PROJECT_LIKE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-_]{0,63}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.row_factory = sqlite3.Row
    return conn


def ensure_schema() -> None:
    conn = _connect()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS conversation_context (
                conversation_id TEXT PRIMARY KEY,
                active_project_number TEXT,
                active_project_name TEXT,
                active_bp_name TEXT,
                last_record_no TEXT,
                history_summary TEXT,
                list_state TEXT,
                updated_at TEXT
            )
            """
        )
        # Migration for DBs created before list_state existed.
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(conversation_context)").fetchall()]
        if "list_state" not in cols:
            conn.execute("ALTER TABLE conversation_context ADD COLUMN list_state TEXT")
        conn.commit()
    finally:
        conn.close()


ensure_schema()


def _lookup_project_name(project_number: str) -> str:
    """Best-effort project name; prefers the Postgres store, falls back to SQLite cache."""
    try:
        import pgstore
        if pgstore.is_configured():
            res = pgstore.find_projects(project_number)
            exact = res.get("exact")
            if exact and exact.get("project_name"):
                return exact["project_name"]
    except Exception:
        pass
    try:
        from sync_manager import get_db_connection
        conn = get_db_connection()
        try:
            row = conn.execute(
                "SELECT project_name FROM cached_projects WHERE project_number = ?",
                (project_number,),
            ).fetchone()
            return row["project_name"] if row and row["project_name"] else ""
        finally:
            conn.close()
    except Exception:
        return ""


class ConversationMemory:
    def __init__(
        self,
        conversation_id: Optional[str],
        active_project_number: str = "",
        active_project_name: str = "",
        active_bp_name: str = "",
        last_record_no: str = "",
        history_summary: str = "",
        list_state: Optional[Dict[str, Any]] = None,
    ):
        self.conversation_id = conversation_id
        self.active_project_number = active_project_number or ""
        self.active_project_name = active_project_name or ""
        self.active_bp_name = active_bp_name or ""
        self.last_record_no = last_record_no or ""
        self.history_summary = history_summary or ""
        # Pagination / pending-offer state for "show more" follow-ups.
        self.list_state: Dict[str, Any] = list_state or {}

    # ── Persistence ─────────────────────────────────────────────────────────
    @classmethod
    def load(cls, conversation_id: Optional[str]) -> "ConversationMemory":
        if not conversation_id:
            return cls(conversation_id=None)
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT * FROM conversation_context WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return cls(conversation_id=conversation_id)
        try:
            list_state = json.loads(row["list_state"]) if row["list_state"] else {}
        except (ValueError, TypeError):
            list_state = {}
        return cls(
            conversation_id=conversation_id,
            active_project_number=row["active_project_number"] or "",
            active_project_name=row["active_project_name"] or "",
            active_bp_name=row["active_bp_name"] or "",
            last_record_no=row["last_record_no"] or "",
            history_summary=row["history_summary"] or "",
            list_state=list_state,
        )

    def save(self) -> None:
        if not self.conversation_id:
            return
        conn = _connect()
        try:
            conn.execute(
                """
                INSERT INTO conversation_context
                    (conversation_id, active_project_number, active_project_name,
                     active_bp_name, last_record_no, history_summary, list_state, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(conversation_id) DO UPDATE SET
                    active_project_number=excluded.active_project_number,
                    active_project_name=excluded.active_project_name,
                    active_bp_name=excluded.active_bp_name,
                    last_record_no=excluded.last_record_no,
                    history_summary=excluded.history_summary,
                    list_state=excluded.list_state,
                    updated_at=excluded.updated_at
                """,
                (
                    self.conversation_id,
                    self.active_project_number,
                    self.active_project_name,
                    self.active_bp_name,
                    self.last_record_no,
                    self.history_summary,
                    json.dumps(self.list_state) if self.list_state else "",
                    _now(),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    # ── Updates ─────────────────────────────────────────────────────────────
    def update_from_tool_calls(self, messages: List[Any]) -> None:
        """Fill slots from the tool-call args the agent used this turn.

        Later calls win (the most recent project/BP the user steered toward), so we
        walk messages in order and overwrite as we go. resolve_project's `query`
        arg is also honored: a bare number the user typed fills the slot once the
        RESULT confirms the canonical exact match (never padded/reformatted).
        """
        with _MEM_LOCK:
            self._update_from_tool_calls_locked(messages)

    def _update_from_tool_calls_locked(self, messages: List[Any]) -> None:
        pending_query: str = ""
        for msg in messages or []:
            tool_calls = getattr(msg, "tool_calls", None) or []
            for call in tool_calls:
                name = (call.get("name", "") if isinstance(call, dict) else "") or ""
                args = call.get("args", {}) if isinstance(call, dict) else {}
                if not isinstance(args, dict):
                    continue
                for a in _PROJECT_ARGS:
                    val = str(args.get(a) or "").strip()
                    if val:
                        if val != self.active_project_number:
                            self.active_project_number = val
                            self.active_project_name = _lookup_project_name(val)
                # resolve_project(query='0000567') — remember the literal the user gave.
                if "resolve" in name and "query" in args:
                    q = str(args.get("query") or "").strip()
                    if q and _QUERY_PROJECT_LIKE.match(q) and len(q) <= 64:
                        pending_query = q
                for a in _BP_ARGS:
                    val = str(args.get(a) or "").strip()
                    if val:
                        self.active_bp_name = val
                for a in _RECORD_ARGS:
                    val = str(args.get(a) or "").strip()
                    if val:
                        self.last_record_no = val

            # Also capture the canonical project resolved in a resolve_project RESULT, so a
            # bare project number the user typed (resolved via `query`) still fills the slot.
            content = getattr(msg, "content", None)
            if content and type(msg).__name__ == "ToolMessage":
                text = str(content)
                matched = False
                for rx in _RESOLVED_RES:
                    m = rx.search(text)
                    if m:
                        num = m.group(1).strip()
                        if num:
                            self.active_project_number = num
                            self.active_project_name = (m.group(2) or "").strip() or _lookup_project_name(num)
                            matched = True
                            break
                # Fallback: pending bare-number query confirmed verbatim in the result.
                if not matched and pending_query and pending_query in text:
                    self.active_project_number = pending_query
                    if not self.active_project_name:
                        self.active_project_name = _lookup_project_name(pending_query)

        # Invalidate a stale pagination list: if the conversation has moved to a different
        # BP/project than the one the open list belongs to, drop it so a later "show more"
        # can't page an unrelated business process.
        s = self.list_state or {}
        if s.get("bpname"):
            sb, ab = s.get("bpname", "").lower(), (self.active_bp_name or "").lower()
            bp_mismatch = ab and sb not in ab and ab not in sb
            proj_mismatch = (self.active_project_number and s.get("project_number", "")
                             and s.get("project_number") != self.active_project_number)
            if bp_mismatch or proj_mismatch:
                self.list_state = {}

    def update_history_summary(self, chat_history: List[dict], keep_recent: int = 6) -> None:
        """Cheap heuristic rollup of older turns so long chats stay bounded without an
        extra LLM call — the resolved slots already carry the load-bearing state."""
        older = (chat_history or [])[:-keep_recent]
        user_topics = [
            (m.get("content") or "").strip().replace("\n", " ")[:80]
            for m in older
            if m.get("role") == "user" and (m.get("content") or "").strip()
        ]
        if user_topics:
            self.history_summary = "Earlier the user asked about: " + "; ".join(user_topics[-8:])

    # ── Pagination / pending-offer state ──────────────────────────────────────
    def set_list_state(self, scope: str, bpname: str, project_number: str, shown: int, total: int, exact: bool = True) -> None:
        """Record what list was just shown so a follow-up 'show more' can page it.
        exact=True means it came from a real listing of one BP (page by exact name);
        exact=False means it's a fuzzy/derived list (page by LIKE, matching count semantics)."""
        import uuid as _uuid
        with _MEM_LOCK:
            self.list_state = {
                "scope": scope,               # 'company' | 'project'
                "bpname": bpname or "",
                "project_number": project_number or "",
                "shown": int(shown),
                "total": int(total),
                "exact": bool(exact),
                "token": _uuid.uuid4().hex[:12],
                "sig": f"{scope}|{(bpname or '').lower()}|{project_number or ''}|{bool(exact)}",
            }

    def has_open_list(self) -> bool:
        s = self.list_state or {}
        return bool(s.get("bpname")) and int(s.get("shown", 0)) < int(s.get("total", 0))

    def advance_list(self, count: int) -> None:
        with _MEM_LOCK:
            if self.list_state:
                self.list_state["shown"] = int(self.list_state.get("shown", 0)) + int(count)

    def clear_list_state(self) -> None:
        with _MEM_LOCK:
            self.list_state = {}

    # ── Prompt injection ──────────────────────────────────────────────────────
    def context_block(self) -> str:
        """Compact context block injected into the system prompt, or '' if empty."""
        parts = []
        if self.active_project_number:
            name = f" ({self.active_project_name})" if self.active_project_name else ""
            parts.append(f"Active project: {self.active_project_number}{name}")
        if self.active_bp_name:
            parts.append(f"Active BP: {self.active_bp_name}")
        if self.last_record_no:
            parts.append(f"Last record: {self.last_record_no}")
        open_offer = ""
        if self.has_open_list():
            s = self.list_state
            scope_lbl = "company-wide" if s.get("scope") == "company" else f"project {s.get('project_number')}"
            open_offer = (f"An offer to show MORE records is open: '{s.get('bpname')}' ({scope_lbl}) — "
                          f"shown {s.get('shown')} of {s.get('total')}. If the user says yes/more/next/continue, "
                          f"call show_more_records (do NOT re-run the original query).")
        if not parts and not self.history_summary and not open_offer:
            return ""
        lines = [
            "# CURRENT CONTEXT (resolved earlier in THIS conversation — reuse it; do NOT re-ask)",
        ]
        if parts:
            lines.append(" | ".join(parts))
        if open_offer:
            lines.append(open_offer)
        if self.history_summary:
            lines.append(self.history_summary)
        if self.active_project_number:
            pn = self.active_project_number
            lines.append(
                f"MANDATORY CONTEXT REUSE: The active project is '{pn}'. When the user asks a project-scoped "
                f"question WITHOUT naming a project — e.g. 'how many purchase orders in this', 'what about here', "
                f"'show its change orders', 'and in this project?' — you MUST immediately call the tool with "
                f"project_number='{pn}'. NEVER reply 'which project?' / 'please provide the project number' when "
                f"an active project is shown here — that is a hard failure. Only ask if NO active project is listed."
            )
        else:
            lines.append(
                "If the user says 'the project', 'it', 'that BP', or 'the record' without naming one, "
                "use the values above. Only ask for clarification when the relevant value is absent."
            )
        return "\n".join(lines)
