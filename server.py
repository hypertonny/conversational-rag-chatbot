import os
import json
from typing import Dict, Any, Optional, List
from fastapi import FastAPI, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from unifier_client import UnifierClient
from chatbot_engine import ChatbotEngine

app = FastAPI(
    title="Oracle Primavera Unifier REST API Portal & AI Chatbot",
    description="High-performance custom web dashboard backend for Primavera Unifier REST v1 APIs and Conversational RAG AI.",
    version="2.0.0"
)

# Enable CORS for local testing & Dokploy domain integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global Cached Chatbot Engine instance
chatbot_engine_cache: Dict[str, ChatbotEngine] = {}

def get_engine(openai_key: Optional[str] = None, groq_key: Optional[str] = None) -> ChatbotEngine:
    cache_key = f"{openai_key or ''}:{groq_key or ''}"
    if cache_key not in chatbot_engine_cache:
        chatbot_engine_cache[cache_key] = ChatbotEngine(
            openai_api_key=openai_key if openai_key else None,
            groq_api_key=groq_key if groq_key else None
        )
    return chatbot_engine_cache[cache_key]


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

@app.post("/api/chat")
def chat(req: ChatReq):
    try:
        engine = get_engine(openai_key=req.openai_api_key or None, groq_key=req.groq_api_key or None)

        client = None
        if req.bearer_token and req.bearer_token.strip():
            client = UnifierClient(bearer_token=req.bearer_token.strip(), base_url=req.base_url or None)

        answer = engine.get_chat_response(
            user_query=req.prompt,
            chat_history=req.chat_history or [],
            provider=req.provider or "groq",
            client=client
        )
        return {"answer": answer}
    except Exception as e:
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
