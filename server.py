import os
import json
import time
import logging
import sqlite3
import uuid
from datetime import datetime
from typing import Dict, Any, Optional, List
from fastapi import FastAPI, HTTPException, Response, status, BackgroundTasks

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
from fastapi.responses import FileResponse
from pydantic import BaseModel

from unifier_client import UnifierClient
from sync_manager import query_cached_projects, query_cached_users, query_cached_bp_records
from chatbot_engine import ChatbotEngine

app = FastAPI(
    title="Oracle Primavera Unifier REST API Portal & AI Chatbot",
    description="High-performance custom web dashboard backend for Primavera Unifier REST v1 APIs and Conversational RAG AI.",
    version="2.0.0"
)

# --- DATABASE SETUP ---
def get_chat_db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
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

def get_engine(openai_key: Optional[str] = None, groq_key: Optional[str] = None) -> ChatbotEngine:
    return ChatbotEngine(
        openai_api_key=openai_key if openai_key else None,
        groq_api_key=groq_key if groq_key else None
    )


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
    openai_api_key: Optional[str] = ""
    groq_api_key: Optional[str] = ""
    provider: Optional[str] = "groq"
    prompt: str
    chat_history: Optional[List[Dict[str, str]]] = []
    conversation_id: Optional[str] = None


# --- API ROUTES ---

@app.get("/api/health")
def health_check():
    return {"status": "ok", "app": "Primavera Unifier Custom Web Portal", "version": "2.0.0"}

@app.post("/api/test-connection")
def test_connection(req: TestConnectionReq):
    client = UnifierClient(bearer_token=req.bearer_token, base_url=req.base_url)
    success, msg, code = client.test_connection()
    # Note: The chatbot now uses a live Agentic flow (LangGraph tools).
    # Data is fetched on-demand per prompt — no pre-population needed.
    return {"success": success, "message": msg, "status_code": code}

@app.post("/api/active-projects")
def get_active_projects(req: TestConnectionReq):
    cached = query_cached_projects()
    if cached:
        return {"success": True, "data": cached, "status_code": 200, "elapsed_ms": 1.0}
    client = UnifierClient(bearer_token=req.bearer_token, base_url=req.base_url)
    success, data, status_code, elapsed_ms = client.get_active_projects()
    return {"success": success, "data": data, "status_code": status_code, "elapsed_ms": elapsed_ms}

@app.post("/api/company-bp-catalog")
def get_company_bp_catalog(req: CompanyBPCatalogReq):
    client = UnifierClient(bearer_token=req.bearer_token, base_url=req.base_url)
    success, data, status_code, elapsed_ms = client.get_company_bp_list()
    return {"success": success, "data": data, "status_code": status_code, "elapsed_ms": elapsed_ms}

@app.post("/api/project-bp-catalog")
def get_project_bp_catalog(req: ProjectBPCatalogReq):
    client = UnifierClient(bearer_token=req.bearer_token, base_url=req.base_url)
    success, data, status_code, elapsed_ms = client.get_project_bp_list(req.project_number)
    return {"success": success, "data": data, "status_code": status_code, "elapsed_ms": elapsed_ms}

@app.post("/api/company-bp-records")
def get_company_bp_records(req: CompanyBPRecordsReq):
    cached = query_cached_bp_records(bpname=req.bpname)
    if cached:
        return {"success": True, "data": cached, "status_code": 200, "elapsed_ms": 1.0}
    client = UnifierClient(bearer_token=req.bearer_token, base_url=req.base_url)
    success, data, status_code, elapsed_ms = client.get_company_bp_records(
        bpname=req.bpname,
        filter_condition=req.filter_condition or "",
        lineitem=req.lineitem or "no",
        lineitem_file=req.lineitem_file or "no",
        general_comments=req.general_comments or "no",
        attach_all_publications=req.attach_all_publications or "no"
    )
    return {"success": success, "data": data, "status_code": status_code, "elapsed_ms": elapsed_ms}

@app.post("/api/project-bp-records")
def get_project_bp_records(req: ProjectBPRecordsReq):
    cached = query_cached_bp_records(project_number=req.project_number, bpname=req.bpname)
    if cached:
        return {"success": True, "data": cached, "status_code": 200, "elapsed_ms": 1.0}
    client = UnifierClient(bearer_token=req.bearer_token, base_url=req.base_url)
    success, data, status_code, elapsed_ms = client.get_project_bp_records(
        project_number=req.project_number,
        bpname=req.bpname,
        filter_condition=req.filter_condition or "",
        lineitem=req.lineitem or "no",
        lineitem_file=req.lineitem_file or "no",
        general_comments=req.general_comments or "no",
        attach_all_publications=req.attach_all_publications or "no"
    )
    return {"success": success, "data": data, "status_code": status_code, "elapsed_ms": elapsed_ms}

@app.post("/api/download-file")
def download_bp_file(req: FileDownloadReq):
    client = UnifierClient(bearer_token=req.bearer_token, base_url=req.base_url)
    success, content_or_err, status_code, elapsed_ms, resp_headers = client.download_bp_file(req.payload)
    if success and isinstance(content_or_err, bytes):
        file_name = req.payload.get("file_name", "unifier_attachment.bin")
        headers = {"Content-Disposition": f'attachment; filename="{file_name}"'}
        return Response(content=content_or_err, media_type="application/octet-stream", headers=headers)
    else:
        return {"success": False, "data": content_or_err, "status_code": status_code, "elapsed_ms": elapsed_ms}

@app.post("/api/users")
def get_users(req: UserAdminReq):
    cached = query_cached_users(filter_val=req.filter_condition or "")
    if cached:
        return {"success": True, "data": cached, "status_code": 200, "elapsed_ms": 1.0}
    client = UnifierClient(bearer_token=req.bearer_token, base_url=req.base_url)
    success, data, status_code, elapsed_ms = client.get_users(filter_condition=req.filter_condition or "")
    return {"success": success, "data": data, "status_code": status_code, "elapsed_ms": elapsed_ms}

@app.post("/api/custom-request")
def custom_request(req: CustomRequestReq):
    client = UnifierClient(bearer_token=req.bearer_token, base_url=req.base_url)
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

@app.get("/api/conversations")
def list_conversations():
    conn = get_chat_db_connection()
    c = conn.cursor()
    c.execute('SELECT id, title, updated_at FROM conversations ORDER BY updated_at DESC')
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
    c = conn.cursor()
    c.execute('DELETE FROM messages WHERE conversation_id = ?', (conv_id,))
    c.execute('DELETE FROM conversations WHERE id = ?', (conv_id,))
    conn.commit()
    conn.close()
    return {"success": True}

@app.post("/api/chat")
def chat(req: ChatReq):
    logger.info(f"Received chat request (provider: {req.provider}). Prompt length: {len(req.prompt)}")
    start_t = time.time()
    try:
        engine = get_engine(openai_key=req.openai_api_key or None, groq_key=req.groq_api_key or None)

        client = None
        if req.bearer_token and req.bearer_token.strip():
            client = UnifierClient(bearer_token=req.bearer_token.strip(), base_url=req.base_url or None)

        # Database logic for conversation
        conv_id = req.conversation_id
        conn = get_chat_db_connection()
        c = conn.cursor()

        if not conv_id:
            conv_id = str(uuid.uuid4())
            title = req.prompt[:30] + "..." if len(req.prompt) > 30 else req.prompt
            now = datetime.utcnow().isoformat()
            c.execute('INSERT INTO conversations (id, title, updated_at) VALUES (?, ?, ?)', (conv_id, title, now))
        else:
            now = datetime.utcnow().isoformat()
            c.execute('UPDATE conversations SET updated_at = ? WHERE id = ?', (now, conv_id))

        # Save user message
        c.execute('INSERT INTO messages (id, conversation_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)', 
                  (str(uuid.uuid4()), conv_id, "user", req.prompt, datetime.utcnow().isoformat()))
        conn.commit()

        answer = engine.get_chat_response(
            user_query=req.prompt,
            chat_history=req.chat_history or [],
            provider=req.provider or "groq",
            client=client
        )

        # Save assistant message
        c.execute('INSERT INTO messages (id, conversation_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)', 
                  (str(uuid.uuid4()), conv_id, "assistant", answer, datetime.utcnow().isoformat()))
        conn.commit()
        conn.close()

        elapsed = time.time() - start_t
        logger.info(f"Chat request successfully completed in {elapsed:.2f}s")
        return {"answer": answer, "conversation_id": conv_id}
    except Exception as e:
        elapsed = time.time() - start_t
        logger.error(f"Chat request failed after {elapsed:.2f}s with error: {e}")
        # Always return valid JSON — never let a 500 reach the frontend
        return {"answer": f"Server error: {str(e)}"}

# Environment Config Defaults for Frontend
@app.get("/api/config")
def get_config():
    return {
        "default_bearer_token": os.getenv("UNIFIER_BEARER_TOKEN", ""),
        "default_base_url": os.getenv("UNIFIER_BASE_URL", UnifierClient.DEFAULT_BASE_URL),
        "default_openai_key": os.getenv("OPENAI_API_KEY", ""),
        "default_groq_key": os.getenv("GROQ_API_KEY", ""),
        "default_llm_provider": os.getenv("LLM_PROVIDER", "groq").lower()
    }


# --- MOUNT STATIC FILES FOR SPA FRONTEND ---
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def read_root():
    return FileResponse("static/index.html")
