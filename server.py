import os
import json
import time
import logging
import sqlite3
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from fastapi import FastAPI, HTTPException, Response, status, BackgroundTasks
from dotenv import load_dotenv

load_dotenv()


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()

def _run_background_sync(token: str, url: str):
    try:
        from sync_manager import SyncManager
        client = UnifierClient(bearer_token=token, base_url=url)
        sm = SyncManager(client=client)
        logger.info("Starting background synchronization...")
        stats = sm.sync_all()
        logger.info(f"Background sync complete: {stats}")
    except Exception as e:
        logger.error(f"Background sync error: {e}")

# Configure server logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("FastAPI_Server")
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from unifier_client import UnifierClient
from sync_manager import query_cached_projects, query_cached_users, query_cached_bp_records, start_background_scheduler
from chatbot_engine import ChatbotEngine
from agent_memory import ConversationMemory


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Auto-populate the local cache + vector store from Unifier on boot and start the
    recurring sync scheduler, so the chatbot has real data immediately (the cache doesn't
    reliably survive a redeploy). Replaces the deprecated @app.on_event('startup')."""
    token = os.getenv("UNIFIER_BEARER_TOKEN", "")
    if token:
        url = os.getenv("UNIFIER_BASE_URL", UnifierClient.DEFAULT_BASE_URL)
        start_background_scheduler(token, url)
    else:
        logger.info("UNIFIER_BEARER_TOKEN not set — skipping startup sync/scheduler.")
    yield


app = FastAPI(
    title="Oracle Primavera Unifier REST API Portal & AI Chatbot",
    description="High-performance custom web dashboard backend for Primavera Unifier REST v1 APIs and Conversational RAG AI.",
    version="2.0.0",
    lifespan=lifespan,
)

# --- DATABASE SETUP ---
os.makedirs("data", exist_ok=True)
DB_PATH = os.path.join("data", "chats.db")

def get_chat_db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn

def init_db():
    conn = get_chat_db_connection()
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            title TEXT,
            updated_at TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            conversation_id TEXT,
            role TEXT,
            content TEXT,
            created_at TEXT,
            FOREIGN KEY (conversation_id) REFERENCES conversations (id) ON DELETE CASCADE
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# Enable CORS for local testing & Dokploy domain integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_no_cache_headers(request, call_next):
    response = await call_next(request)
    # Ensure browsers and proxies never cache HTML, JS, or CSS
    if request.url.path == "/" or request.url.path.endswith(".html") or request.url.path.startswith("/static"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0, private"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

def get_engine(gemini_key: Optional[str] = None) -> ChatbotEngine:
    key = (gemini_key or "").strip() or os.getenv("GEMINI_API_KEY", "")
    return ChatbotEngine(gemini_api_key=key or None)


def _unifier_client(bearer_token: Optional[str] = None, base_url: Optional[str] = None) -> UnifierClient:
    """Build a UnifierClient, falling back to server .env creds when the request omits them.
    Keeps secrets server-side: the frontend sends empty values and the server supplies the
    token/URL from the environment, so credentials never travel to or display on the client."""
    token = (bearer_token or "").strip() or os.getenv("UNIFIER_BEARER_TOKEN", "")
    url = (base_url or "").strip() or os.getenv("UNIFIER_BASE_URL", UnifierClient.DEFAULT_BASE_URL)
    return UnifierClient(bearer_token=token, base_url=url or None)




# --- PYDANTIC REQUEST MODELS ---

class TestConnectionReq(BaseModel):
    bearer_token: str
    base_url: Optional[str] = None

class CompanyBPCatalogReq(BaseModel):
    bearer_token: str
    base_url: Optional[str] = None

class ProjectBPCatalogReq(BaseModel):
    bearer_token: str
    base_url: Optional[str] = None
    project_number: str

class CompanyBPRecordsReq(BaseModel):
    bearer_token: str
    base_url: Optional[str] = None
    bpname: str
    filter_condition: Optional[str] = ""
    lineitem: Optional[str] = "no"
    lineitem_file: Optional[str] = "no"
    general_comments: Optional[str] = "no"
    attach_all_publications: Optional[str] = "no"

class ProjectBPRecordsReq(BaseModel):
    bearer_token: str
    base_url: Optional[str] = None
    project_number: str
    bpname: str
    filter_condition: Optional[str] = ""
    lineitem: Optional[str] = "no"
    lineitem_file: Optional[str] = "no"
    general_comments: Optional[str] = "no"
    attach_all_publications: Optional[str] = "no"

class FileDownloadReq(BaseModel):
    bearer_token: str
    base_url: Optional[str] = None
    payload: Dict[str, Any]

class UserAdminReq(BaseModel):
    bearer_token: str
    base_url: Optional[str] = None
    filter_condition: Optional[str] = ""

class CustomRequestReq(BaseModel):
    bearer_token: str
    base_url: Optional[str] = None
    method: str
    endpoint: str
    json_body: Optional[Dict[str, Any]] = None
    custom_headers: Optional[Dict[str, str]] = None

class ChatReq(BaseModel):
    bearer_token: Optional[str] = ""
    base_url: Optional[str] = ""
    gemini_api_key: Optional[str] = ""
    provider: Optional[str] = "gemini"
    prompt: str
    chat_history: Optional[List[Dict[str, str]]] = []
    conversation_id: Optional[str] = None


# --- API ROUTES ---

@app.get("/api/health")
def health_check():
    return {"status": "ok", "app": "Primavera Unifier Custom Web Portal", "version": "2.2.0-gemini"}

@app.post("/api/test-connection")
def test_connection(req: TestConnectionReq):
    client = _unifier_client(req.bearer_token, req.base_url)
    success, msg, code = client.test_connection()
    # Note: The chatbot now uses a live Agentic flow (LangGraph tools).
    # Data is fetched on-demand per prompt — no pre-population needed.
    return {"success": success, "message": msg, "status_code": code}

@app.post("/api/active-projects")
def get_active_projects(req: TestConnectionReq):
    client = _unifier_client(req.bearer_token, req.base_url)
    success, data, status_code, elapsed_ms = client.get_active_projects()
    if not success:
        cached = query_cached_projects()
        if cached:
            return {"success": True, "data": cached, "status_code": 200, "elapsed_ms": 1.0, "is_cached": True}
    return {"success": success, "data": data, "status_code": status_code, "elapsed_ms": elapsed_ms}

@app.post("/api/company-bp-catalog")
def get_company_bp_catalog(req: CompanyBPCatalogReq):
    client = _unifier_client(req.bearer_token, req.base_url)
    success, data, status_code, elapsed_ms = client.get_company_bp_list()
    return {"success": success, "data": data, "status_code": status_code, "elapsed_ms": elapsed_ms}

@app.post("/api/project-bp-catalog")
def get_project_bp_catalog(req: ProjectBPCatalogReq):
    client = _unifier_client(req.bearer_token, req.base_url)
    success, data, status_code, elapsed_ms = client.get_project_bp_list(req.project_number)
    return {"success": success, "data": data, "status_code": status_code, "elapsed_ms": elapsed_ms}

@app.post("/api/company-bp-records")
def get_company_bp_records(req: CompanyBPRecordsReq):
    client = _unifier_client(req.bearer_token, req.base_url)
    success, data, status_code, elapsed_ms = client.get_company_bp_records(
        bpname=req.bpname,
        filter_condition=req.filter_condition or "",
        lineitem=req.lineitem or "no",
        lineitem_file=req.lineitem_file or "no",
        general_comments=req.general_comments or "no",
        attach_all_publications=req.attach_all_publications or "no"
    )
    if not success:
        cached = query_cached_bp_records(bpname=req.bpname)
        if cached:
            return {"success": True, "data": cached, "status_code": 200, "elapsed_ms": 1.0, "is_cached": True}
    return {"success": success, "data": data, "status_code": status_code, "elapsed_ms": elapsed_ms}

@app.post("/api/project-bp-records")
def get_project_bp_records(req: ProjectBPRecordsReq):
    client = _unifier_client(req.bearer_token, req.base_url)
    success, data, status_code, elapsed_ms = client.get_project_bp_records(
        project_number=req.project_number,
        bpname=req.bpname,
        filter_condition=req.filter_condition or "",
        lineitem=req.lineitem or "no",
        lineitem_file=req.lineitem_file or "no",
        general_comments=req.general_comments or "no",
        attach_all_publications=req.attach_all_publications or "no"
    )
    if not success:
        cached = query_cached_bp_records(project_number=req.project_number, bpname=req.bpname)
        if cached:
            return {"success": True, "data": cached, "status_code": 200, "elapsed_ms": 1.0, "is_cached": True}
    return {"success": success, "data": data, "status_code": status_code, "elapsed_ms": elapsed_ms}

@app.post("/api/download-file")
def download_bp_file(req: FileDownloadReq):
    from fastapi.responses import StreamingResponse
    import re
    client = _unifier_client(req.bearer_token, req.base_url)
    success, content_or_err, status_code, elapsed_ms, resp_headers = client.download_bp_file(req.payload)
    if success and isinstance(content_or_err, bytes):
        # Cap in-memory download size to avoid OOM on large attachments (50 MB).
        MAX_BYTES = 50 * 1024 * 1024
        if len(content_or_err) > MAX_BYTES:
            return {"success": False, "data": f"Attachment is {len(content_or_err)} bytes, over the 50 MB download cap. Refine the record/file and retry.", "status_code": 413, "elapsed_ms": elapsed_ms}
        raw_name = str(req.payload.get("file_name", "unifier_attachment.bin"))
        safe_name = re.sub(r'[^A-Za-z0-9._-]', '_', raw_name)[:120] or "unifier_attachment.bin"
        headers = {"Content-Disposition": f'attachment; filename="{safe_name}"'}
        return StreamingResponse(iter([content_or_err]), media_type="application/octet-stream", headers=headers)
    else:
        return {"success": False, "data": content_or_err, "status_code": status_code, "elapsed_ms": elapsed_ms}

@app.post("/api/users")
def get_users(req: UserAdminReq):
    client = _unifier_client(req.bearer_token, req.base_url)
    success, data, status_code, elapsed_ms = client.get_users(filter_condition=req.filter_condition or "")
    if not success:
        cached = query_cached_users(filter_val=req.filter_condition or "")
        if cached:
            return {"success": True, "data": cached, "status_code": 200, "elapsed_ms": 1.0, "is_cached": True}
    return {"success": success, "data": data, "status_code": status_code, "elapsed_ms": elapsed_ms}

@app.post("/api/custom-request")
def custom_request(req: CustomRequestReq):
    client = _unifier_client(req.bearer_token, req.base_url)
    success, data, status_code, elapsed_ms, resp_headers = client.custom_request(
        method=req.method,
        endpoint_or_full_url=req.endpoint,
        json_data=req.json_body,
        custom_headers=req.custom_headers
    )
    return {
        "success": success,
        "data": data,
        "status_code": status_code,
        "elapsed_ms": elapsed_ms,
        "headers": resp_headers
    }

class SyncReq(BaseModel):
    bearer_token: Optional[str] = ""
    base_url: Optional[str] = ""

@app.post("/api/sync")
def trigger_sync(req: SyncReq, background_tasks: BackgroundTasks):
    token = req.bearer_token or os.getenv("UNIFIER_BEARER_TOKEN", "")
    url = req.base_url or os.getenv("UNIFIER_BASE_URL", UnifierClient.DEFAULT_BASE_URL)
    if not token:
        raise HTTPException(status_code=400, detail="Bearer token is required to trigger sync.")
    
    background_tasks.add_task(_run_background_sync, token, url)
    return {"success": True, "message": "Synchronization started in background."}

@app.get("/api/sync-stats")
def get_sync_stats_endpoint():
    from sync_manager import get_sync_stats
    return {"success": True, "stats": get_sync_stats()}

@app.get("/api/db-graph")
def db_graph(project_number: str = ""):
    """Hierarchy of what exists under the company and a single project, built from the
    local cache (read-only). Powers the database-graph canvas page.

    Model: Company -> Project (shell) -> Business Process -> Record -> Fields / Line items.
    """
    from sync_manager import get_db_connection, get_sync_stats
    conn = get_db_connection()
    try:
        # Default to the project with the most cached records if none supplied.
        if not project_number:
            row = conn.execute(
                "SELECT project_number FROM cached_bp_records WHERE scope_type='project' "
                "AND project_number!='' GROUP BY project_number ORDER BY COUNT(*) DESC LIMIT 1"
            ).fetchone()
            project_number = row["project_number"] if row else ""

        stats = get_sync_stats()

        company_bps = [dict(r) for r in conn.execute(
            "SELECT cb.bp_name, COALESCE(rc.c, 0) AS records FROM cached_company_bps cb "
            "LEFT JOIN (SELECT bp_name, COUNT(*) c FROM cached_bp_records WHERE scope_type='company' GROUP BY bp_name) rc "
            "ON rc.bp_name = cb.bp_name ORDER BY records DESC, cb.bp_name"
        ).fetchall()]

        proj_row = conn.execute(
            "SELECT project_number, project_name, status, project_type FROM cached_projects WHERE project_number=?",
            (project_number,)
        ).fetchone()
        project = dict(proj_row) if proj_row else {"project_number": project_number, "project_name": "(unknown)", "status": "", "project_type": ""}

        project_bps = [dict(r) for r in conn.execute(
            "SELECT bp_name, COUNT(*) AS records FROM cached_bp_records WHERE project_number=? "
            "GROUP BY bp_name ORDER BY records DESC", (project_number,)
        ).fetchall()]

        # Per-BP status breakdown + a sample record's field list (columns) and line-item info.
        for bp in project_bps:
            statuses = conn.execute(
                "SELECT status, COUNT(*) c FROM cached_bp_records WHERE project_number=? AND bp_name=? GROUP BY status ORDER BY c DESC",
                (project_number, bp["bp_name"])
            ).fetchall()
            bp["statuses"] = {(s["status"] or "(blank)"): s["c"] for s in statuses}
            sample = conn.execute(
                "SELECT raw_json FROM cached_bp_records WHERE project_number=? AND bp_name=? LIMIT 1",
                (project_number, bp["bp_name"])
            ).fetchone()
            fields, line_item_fields = [], []
            try:
                d = json.loads(sample["raw_json"]) if sample else {}
                fields = [k for k in d.keys() if k != "_bp_lineitems"]
                li = d.get("_bp_lineitems")
                if isinstance(li, list) and li and isinstance(li[0], dict):
                    line_item_fields = list(li[0].keys())
            except Exception:
                pass
            bp["field_count"] = len(fields)
            bp["fields"] = fields[:60]
            bp["line_item_fields"] = line_item_fields[:40]
            bp["has_line_items"] = bool(line_item_fields)

        status_totals = {(r["status"] or "(blank)"): r["c"] for r in conn.execute(
            "SELECT status, COUNT(*) c FROM cached_bp_records WHERE project_number=? GROUP BY status ORDER BY c DESC",
            (project_number,)
        ).fetchall()}

        projects_with_data = [dict(r) for r in conn.execute(
            "SELECT r.project_number, COALESCE(p.project_name,'') project_name, COUNT(*) records "
            "FROM cached_bp_records r LEFT JOIN cached_projects p ON p.project_number=r.project_number "
            "WHERE r.scope_type='project' AND r.project_number!='' GROUP BY r.project_number "
            "ORDER BY records DESC LIMIT 40"
        ).fetchall()]

        return {
            "success": True,
            "company": {
                "name": "Oracle Primavera Unifier (Company)",
                "projects_total": stats.get("cached_projects", 0),
                "company_bp_count": stats.get("cached_company_bps", 0),
                "users": stats.get("cached_users", 0),
                "vector_embeddings": stats.get("vector_embeddings", 0),
            },
            "company_bps": company_bps,
            "project": project,
            "project_bp_count": len(project_bps),
            "project_record_total": sum(b["records"] for b in project_bps),
            "project_bps": project_bps,
            "status_totals": status_totals,
            "projects_with_data": projects_with_data,
        }
    finally:
        conn.close()

@app.get("/api/db-graph/records")
def db_graph_records(project_number: str = "", bp_name: str = "", scope: str = "project", limit: int = 300):
    """List records under a BP (for lazy tree expansion)."""
    from sync_manager import get_db_connection
    conn = get_db_connection()
    try:
        if scope == "company":
            rows = conn.execute(
                "SELECT record_no, title, status FROM cached_bp_records WHERE scope_type='company' AND bp_name=? "
                "ORDER BY record_no LIMIT ?", (bp_name, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT record_no, title, status FROM cached_bp_records WHERE project_number=? AND bp_name=? "
                "ORDER BY record_no LIMIT ?", (project_number, bp_name, limit)
            ).fetchall()
        return {"success": True, "records": [dict(r) for r in rows]}
    finally:
        conn.close()

@app.get("/api/db-graph/record")
def db_graph_record(record_no: str, bp_name: str, project_number: str = "", scope: str = "project"):
    """Full field values + line items for one record (the leaf data in the tree)."""
    from sync_manager import get_db_connection
    conn = get_db_connection()
    try:
        if scope == "company":
            row = conn.execute(
                "SELECT raw_json FROM cached_bp_records WHERE scope_type='company' AND bp_name=? AND record_no=? LIMIT 1",
                (bp_name, record_no)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT raw_json FROM cached_bp_records WHERE project_number=? AND bp_name=? AND record_no=? LIMIT 1",
                (project_number, bp_name, record_no)
            ).fetchone()
        fields, line_items, li_cols = [], [], []
        if row:
            try:
                d = json.loads(row["raw_json"])
            except Exception:
                d = {}
            for k, v in d.items():
                if k == "_bp_lineitems" or isinstance(v, (dict, list)):
                    continue
                sv = str(v)
                if sv not in ("", "None"):
                    fields.append({"k": k, "v": sv[:160]})
            li = d.get("_bp_lineitems")
            if isinstance(li, list):
                for it in li[:50]:
                    if isinstance(it, dict):
                        line_items.append({k: str(v)[:80] for k, v in it.items() if not isinstance(v, (dict, list))})
                if line_items:
                    li_cols = list(line_items[0].keys())
        return {"success": True, "fields": fields, "line_items": line_items, "line_item_fields": li_cols}
    finally:
        conn.close()

@app.get("/api/project/{project_number}/export")
def export_project_full(project_number: str):
    """Generate a comprehensive JSON export of a project shell with all its metadata,
    all business processes, records, custom fields, and line items."""
    from sync_manager import get_db_connection
    from collections import defaultdict
    conn = get_db_connection()
    try:
        p_row = conn.execute("SELECT * FROM cached_projects WHERE project_number = ?", (project_number,)).fetchone()
        if not p_row:
            raise HTTPException(status_code=404, detail=f"Project '{project_number}' not found in database.")
        p = dict(p_row)
        try:
            p['raw_json'] = json.loads(p.get('raw_json') or '{}')
        except Exception:
            pass

        rows = conn.execute(
            "SELECT * FROM cached_bp_records WHERE project_number = ? ORDER BY bp_name, record_no",
            (project_number,)
        ).fetchall()

        bp_groups = defaultdict(list)
        creators = set()
        assignees = set()
        vendors = set()
        status_counts = defaultdict(int)

        for r in rows:
            item = dict(r)
            status_counts[item['status'] or 'Unspecified'] += 1
            if item['creator']: creators.add(item['creator'])
            if item['assigned_to']: assignees.add(item['assigned_to'])

            raw = {}
            try:
                raw = json.loads(item.get('raw_json') or '{}')
            except Exception:
                pass

            for vk in ('ue_gen_VenNameTB50', 'ue_ven_CompShortNameTB60', 'vendor_name'):
                if raw.get(vk):
                    vendors.add(str(raw[vk]))

            line_items = raw.pop('_bp_lineitems', [])
            fields = {k: v for k, v in raw.items()}

            rec_obj = {
                'record_no': item['record_no'],
                'title': item['title'],
                'status': item['status'],
                'creator': item['creator'],
                'assigned_to': item['assigned_to'],
                'last_synced_at': item['last_synced_at'],
                'fields': fields,
                'line_items_count': len(line_items) if isinstance(line_items, list) else 0,
                'line_items': line_items if isinstance(line_items, list) else []
            }
            bp_groups[item['bp_name']].append(rec_obj)

        bp_list = []
        for bp_name, recs in sorted(bp_groups.items(), key=lambda x: len(x[1]), reverse=True):
            bp_statuses = defaultdict(int)
            for rc in recs:
                bp_statuses[rc['status'] or 'Unspecified'] += 1
            bp_list.append({
                'business_process': bp_name,
                'total_records': len(recs),
                'status_summary': dict(bp_statuses),
                'has_line_items': any(r['line_items_count'] > 0 for r in recs),
                'records': recs
            })

        return {
            'export_metadata': {
                'format_version': '1.0',
                'project_number': project_number,
                'project_name': p.get('project_name', ''),
                'scope': 'Comprehensive Project Context & Database Dump',
                'generated_at': _utcnow()
            },
            'project_details': {
                'project_number': p['project_number'],
                'project_name': p['project_name'],
                'status': p['status'],
                'project_type': p['project_type'],
                'raw_metadata': p.get('raw_json', {}),
                'last_synced_at': p['last_synced_at']
            },
            'summary_metrics': {
                'total_records': len(rows),
                'total_business_processes': len(bp_list),
                'status_breakdown': dict(status_counts),
                'associated_vendors': sorted(list(vendors)),
                'creators': sorted(list(creators)),
                'assignees': sorted(list(assignees))
            },
            'business_processes': bp_list
        }
    finally:
        conn.close()

@app.get("/api/conversations")
def list_conversations(limit: int = 100, offset: int = 0):
    conn = get_chat_db_connection()
    c = conn.cursor()
    c.execute('SELECT id, title, updated_at FROM conversations ORDER BY updated_at DESC LIMIT ? OFFSET ?',
              (max(1, min(limit, 200)), max(0, offset)))
    rows = c.fetchall()
    conn.close()
    return [{"id": r[0], "title": r[1], "updated_at": r[2]} for r in rows]

@app.get("/api/conversations/{conv_id}")
def get_conversation(conv_id: str):
    conn = get_chat_db_connection()
    c = conn.cursor()
    c.execute('SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY created_at ASC', (conv_id,))
    rows = c.fetchall()
    conn.close()
    return [{"role": r[0], "content": r[1]} for r in rows]

@app.delete("/api/conversations/{conv_id}")
def delete_conversation(conv_id: str):
    conn = get_chat_db_connection()
    try:
        c = conn.cursor()
        # Foreign keys ON: deleting the conversation cascades to messages.
        # Keep explicit message delete as a safety net for DBs created before FK enforcement.
        c.execute('DELETE FROM messages WHERE conversation_id = ?', (conv_id,))
        c.execute('DELETE FROM conversations WHERE id = ?', (conv_id,))
        try:
            c.execute('DELETE FROM conversation_context WHERE conversation_id = ?', (conv_id,))
        except Exception:
            pass
        # Cleanup any orphan messages left by pre-FK deletes.
        try:
            c.execute('DELETE FROM messages WHERE conversation_id NOT IN (SELECT id FROM conversations)')
        except Exception:
            pass
        conn.commit()
    finally:
        conn.close()
    return {"success": True}

@app.post("/api/chat")
def chat(req: ChatReq):
    logger.info(f"Received chat request (provider: {req.provider}). Prompt length: {len(req.prompt)}")
    start_t = time.time()
    conn = None
    try:
        # All credentials fall back to .env so the UI fields are optional.
        token = (req.bearer_token or "").strip() or os.getenv("UNIFIER_BEARER_TOKEN", "")
        base_url = (req.base_url or "").strip() or os.getenv("UNIFIER_BASE_URL", UnifierClient.DEFAULT_BASE_URL)
        gemini_key = (req.gemini_api_key or "").strip() or os.getenv("GEMINI_API_KEY", "")
        provider = (req.provider or "").strip() or os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")

        engine = get_engine(gemini_key=gemini_key or None)

        client = None
        if token:
            client = UnifierClient(bearer_token=token, base_url=base_url or None)

        # Database logic for conversation
        conv_id = req.conversation_id
        conn = get_chat_db_connection()
        c = conn.cursor()

        if not conv_id:
            conv_id = str(uuid.uuid4())
            title = req.prompt[:30] + "..." if len(req.prompt) > 30 else req.prompt
            c.execute('INSERT INTO conversations (id, title, updated_at) VALUES (?, ?, ?)', (conv_id, title, _utcnow()))
        else:
            c.execute('UPDATE conversations SET updated_at = ? WHERE id = ?', (_utcnow(), conv_id))

        # Save user message
        c.execute('INSERT INTO messages (id, conversation_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)',
                  (str(uuid.uuid4()), conv_id, "user", req.prompt, _utcnow()))
        conn.commit()

        # Load structured conversation memory so follow-ups reuse resolved entities.
        memory = ConversationMemory.load(conv_id)

        answer = engine.get_chat_response(
            user_query=req.prompt,
            chat_history=req.chat_history or [],
            provider=provider,
            client=client,
            conversation_id=conv_id,
            memory=memory,
        )

        # Save assistant message
        c.execute('INSERT INTO messages (id, conversation_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)',
                  (str(uuid.uuid4()), conv_id, "assistant", answer, _utcnow()))
        conn.commit()

        elapsed = time.time() - start_t
        logger.info(f"Chat request successfully completed in {elapsed:.2f}s")
        return {"answer": answer, "conversation_id": conv_id}
    except Exception as e:
        elapsed = time.time() - start_t
        logger.error(f"Chat request failed after {elapsed:.2f}s with error: {e}")
        # Return valid JSON (the SPA reads data.answer), but flag it as an error rather
        # than disguising a failure as a normal answer.
        return {
            "answer": "⚠️ The assistant hit a server error while handling your request. Please try again.",
            "error": True,
            "detail": str(e),
            "conversation_id": req.conversation_id,
        }
    finally:
        if conn is not None:
            conn.close()

# Environment Config Defaults for Frontend
@app.get("/api/config")
def get_config():
    # SECURITY: never return the actual secret values to the browser. Only report
    # whether each credential is already loaded from the server environment, so the UI
    # can show "Loaded from environment" instead of pre-filling (and exposing) the secret.
    return {
        "bearer_token_set": bool(os.getenv("UNIFIER_BEARER_TOKEN", "").strip()),
        "gemini_key_set": bool(os.getenv("GEMINI_API_KEY", "").strip()),
        "default_base_url": os.getenv("UNIFIER_BASE_URL", UnifierClient.DEFAULT_BASE_URL),
        "default_gemini_model": os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite"),
        "default_llm_provider": os.getenv("LLM_PROVIDER", "gemini").lower()
    }


# --- MOUNT STATIC FILES FOR SPA FRONTEND ---
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/db-graph")
def db_graph_page():
    path = "static/db-graph.html"
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        ts = int(time.time())
        content = content.replace("/static/db-graph.js", f"/static/db-graph.js?v={ts}")
        return HTMLResponse(content=content, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
    return FileResponse(path)


@app.get("/")
def read_root():
    index_path = "static/index.html"
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            content = f.read()
        ts = int(time.time())
        content = content.replace('/static/style.css', f'/static/style.css?v={ts}')
        content = content.replace('/static/app.js', f'/static/app.js?v={ts}')
        return HTMLResponse(
            content=content,
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0, private",
                "Pragma": "no-cache",
                "Expires": "0"
            }
        )
    return FileResponse(index_path)
