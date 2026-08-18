"""
sync_manager.py — Local Relational Cache & Vector Store Sync Manager for Primavera Unifier

Provides dual-storage architecture:
  1. SQLite Relational Cache (unifier_cache.db): Fast structured query & aggregation engine (<5ms).
  2. ChromaDB Vector Store (chroma_db/): Semantic embedding search with RBAC-ready metadata tags.
"""
import os
import json
import time
import sqlite3
import logging

from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple, Union

logger = logging.getLogger("SyncManager")

os.makedirs("data", exist_ok=True)
DB_CACHE_PATH = os.path.join("data", "unifier_cache.db")
CHROMA_DIR = "chroma_db"

def get_db_connection():
    conn = sqlite3.connect(DB_CACHE_PATH, timeout=10.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.row_factory = sqlite3.Row
    return conn

def init_cache_db():
    conn = get_db_connection()
    c = conn.cursor()
    
    # Active Projects Shells
    c.execute('''
        CREATE TABLE IF NOT EXISTS cached_projects (
            project_number TEXT PRIMARY KEY,
            project_name TEXT,
            status TEXT,
            project_type TEXT,
            raw_json TEXT,
            last_synced_at TEXT
        )
    ''')
    
    # Company Business Processes Catalog
    c.execute('''
        CREATE TABLE IF NOT EXISTS cached_company_bps (
            bp_name TEXT PRIMARY KEY,
            bp_model_name TEXT,
            studio_source TEXT,
            raw_json TEXT,
            last_synced_at TEXT
        )
    ''')

    # Project Business Processes Catalog
    c.execute('''
        CREATE TABLE IF NOT EXISTS cached_project_bps (
            id TEXT PRIMARY KEY,
            project_number TEXT,
            bp_name TEXT,
            bp_model_name TEXT,
            studio_source TEXT,
            raw_json TEXT,
            last_synced_at TEXT
        )
    ''')

    # BP Records (Company & Project level)
    c.execute('''
        CREATE TABLE IF NOT EXISTS cached_bp_records (
            id TEXT PRIMARY KEY,
            scope_type TEXT,
            project_number TEXT,
            bp_name TEXT,
            record_no TEXT,
            title TEXT,
            status TEXT,
            creator TEXT,
            assigned_to TEXT,
            raw_json TEXT,
            last_synced_at TEXT
        )
    ''')

    # Users Directory
    c.execute('''
        CREATE TABLE IF NOT EXISTS cached_users (
            user_name TEXT PRIMARY KEY,
            first_name TEXT,
            last_name TEXT,
            email TEXT,
            status TEXT,
            raw_json TEXT,
            last_synced_at TEXT
        )
    ''')

    # Sync History Log
    c.execute('''
        CREATE TABLE IF NOT EXISTS sync_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sync_type TEXT,
            status TEXT,
            records_count INTEGER,
            message TEXT,
            duration_ms REAL,
            created_at TEXT
        )
    ''')

    conn.commit()
    conn.close()
    logger.info("Initialized local SQLite cache schema at unifier_cache.db")

init_cache_db()

# --- CHROMADB VECTOR STORE SETUP ---
_vector_collection = None

def get_vector_collection():
    global _vector_collection
    if _vector_collection is None:
        try:
            import chromadb
            client = chromadb.PersistentClient(path=CHROMA_DIR)
            _vector_collection = client.get_or_create_collection(
                name="unifier_knowledge_base",
                metadata={"hnsw:space": "cosine"}
            )
            logger.info("Initialized ChromaDB vector collection 'unifier_knowledge_base'")
        except Exception as e:
            logger.warning(f"Could not initialize ChromaDB vector collection: {e}")
            _vector_collection = None
    return _vector_collection


def _extract_records(data: Any) -> list:
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


def _format_record_text(r: dict) -> str:
    parts = []
    for k, v in r.items():
        if isinstance(v, (str, int, float, bool)) and v:
            parts.append(f"{k}: {v}")
    return " | ".join(parts)


class SyncManager:
    """
    Manages background and on-demand synchronization between remote Primavera Unifier REST APIs
    and local SQLite + ChromaDB dual storage.
    """

    def __init__(self, client=None):
        self.client = client

    def sync_projects(self) -> Tuple[bool, int, str]:
        if not self.client:
            return False, 0, "No UnifierClient provided."

        start_t = time.time()
        ok, data, code, _ = self.client.get_active_projects()
        if not ok:
            return False, 0, f"API error (HTTP {code}): {data}"

        records = _extract_records(data)
        now = datetime.utcnow().isoformat()
        conn = get_db_connection()
        c = conn.cursor()

        count = 0
        vector_collection = get_vector_collection()
        doc_ids, doc_texts, doc_metas = [], [], []

        for r in records:
            if not isinstance(r, dict):
                continue
            num = str(r.get("projectnumber") or r.get("project_number") or r.get("id") or "").strip()
            name = str(r.get("projectname") or r.get("name") or "Unnamed Project")
            status = str(r.get("status") or r.get("projectstatus") or "Active")
            ptype = str(r.get("type") or r.get("projecttype") or "Standard")

            if not num:
                continue

            c.execute('''
                INSERT INTO cached_projects (project_number, project_name, status, project_type, raw_json, last_synced_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_number) DO UPDATE SET
                    project_name=excluded.project_name,
                    status=excluded.status,
                    project_type=excluded.project_type,
                    raw_json=excluded.raw_json,
                    last_synced_at=excluded.last_synced_at
            ''', (num, name, status, ptype, json.dumps(r), now))
            count += 1

            # Prepare vector document
            doc_id = f"project_{num}"
            text = f"Project #{num}: {name} | Status: {status} | Type: {ptype} | Detail: {_format_record_text(r)}"
            meta = {
                "project_number": num,
                "project_name": name,
                "status": status,
                "scope_type": "project_shell"
            }
            doc_ids.append(doc_id)
            doc_texts.append(text)
            doc_metas.append(meta)

        conn.commit()
        conn.close()

        if vector_collection and doc_ids:
            try:
                vector_collection.upsert(ids=doc_ids, documents=doc_texts, metadatas=doc_metas)
            except Exception as e:
                logger.warning(f"Vector upsert failed for projects: {e}")

        elapsed_ms = (time.time() - start_t) * 1000
        return True, count, f"Synced {count} active projects in {elapsed_ms:.1f}ms"

    def sync_company_bps(self) -> Tuple[bool, int, str]:
        if not self.client:
            return False, 0, "No UnifierClient provided."

        start_t = time.time()
        ok, data, code, _ = self.client.get_company_bp_list()
        if not ok:
            return False, 0, f"API error (HTTP {code}): {data}"

        records = _extract_records(data)
        now = datetime.utcnow().isoformat()
        conn = get_db_connection()
        c = conn.cursor()

        count = 0
        for r in records:
            if not isinstance(r, dict):
                continue
            bp_name = str(r.get("bp_name") or r.get("bp_model_name") or "").strip()
            model_name = str(r.get("bp_model_name") or "")
            source = str(r.get("studio_source") or r.get("source") or "")

            if not bp_name:
                continue

            c.execute('''
                INSERT INTO cached_company_bps (bp_name, bp_model_name, studio_source, raw_json, last_synced_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(bp_name) DO UPDATE SET
                    bp_model_name=excluded.bp_model_name,
                    studio_source=excluded.studio_source,
                    raw_json=excluded.raw_json,
                    last_synced_at=excluded.last_synced_at
            ''', (bp_name, model_name, source, json.dumps(r), now))
            count += 1

        conn.commit()
        conn.close()
        elapsed_ms = (time.time() - start_t) * 1000
        return True, count, f"Synced {count} company BPs in {elapsed_ms:.1f}ms"

    def sync_company_bp_records(self, bpname: str) -> Tuple[bool, int, str]:
        if not self.client:
            return False, 0, "No UnifierClient provided."

        start_t = time.time()
        ok, data, code, _ = self.client.get_company_bp_records(bpname=bpname)
        if not ok:
            return False, 0, f"API error (HTTP {code}): {data}"

        records = _extract_records(data)
        now = datetime.utcnow().isoformat()
        conn = get_db_connection()
        c = conn.cursor()

        count = 0
        vector_collection = get_vector_collection()
        doc_ids, doc_texts, doc_metas = [], [], []

        for r in records:
            if not isinstance(r, dict):
                continue
            rec_no = str(r.get("record_no") or r.get("id") or r.get("record_id") or f"rec_{count}").strip()
            title = str(r.get("title") or r.get("record_title") or r.get("name") or "")
            status = str(r.get("status") or "")
            creator = str(r.get("creator") or r.get("created_by") or "")
            assigned = str(r.get("assigned_to") or r.get("assignedto") or r.get("owner") or "")

            rec_id = f"company_{bpname}_{rec_no}"

            c.execute('''
                INSERT INTO cached_bp_records (id, scope_type, project_number, bp_name, record_no, title, status, creator, assigned_to, raw_json, last_synced_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title,
                    status=excluded.status,
                    creator=excluded.creator,
                    assigned_to=excluded.assigned_to,
                    raw_json=excluded.raw_json,
                    last_synced_at=excluded.last_synced_at
            ''', (rec_id, "company", "", bpname, rec_no, title, status, creator, assigned, json.dumps(r), now))
            count += 1

            # Prepare vector document with RBAC metadata
            text = f"Company BP '{bpname}' Record #{rec_no}: {title} | Status: {status} | Creator: {creator} | Assigned: {assigned} | Detail: {_format_record_text(r)}"
            meta = {
                "scope_type": "company",
                "bp_name": bpname,
                "record_no": rec_no,
                "project_number": "",
                "creator": creator,
                "assigned_to": assigned
            }
            doc_ids.append(rec_id)
            doc_texts.append(text)
            doc_metas.append(meta)

        conn.commit()
        conn.close()

        if vector_collection and doc_ids:
            try:
                vector_collection.upsert(ids=doc_ids, documents=doc_texts, metadatas=doc_metas)
            except Exception as e:
                logger.warning(f"Vector upsert failed for company BP {bpname}: {e}")

        elapsed_ms = (time.time() - start_t) * 1000
        return True, count, f"Synced {count} records for Company BP '{bpname}' in {elapsed_ms:.1f}ms"

    def sync_project_bp_records(self, project_number: str, bpname: str) -> Tuple[bool, int, str]:
        if not self.client:
            return False, 0, "No UnifierClient provided."

        start_t = time.time()
        ok, data, code, _ = self.client.get_project_bp_records(project_number=project_number, bpname=bpname)
        if not ok:
            return False, 0, f"API error (HTTP {code}): {data}"

        records = _extract_records(data)
        now = datetime.utcnow().isoformat()
        conn = get_db_connection()
        c = conn.cursor()

        count = 0
        vector_collection = get_vector_collection()
        doc_ids, doc_texts, doc_metas = [], [], []

        for r in records:
            if not isinstance(r, dict):
                continue
            rec_no = str(r.get("record_no") or r.get("id") or r.get("record_id") or f"rec_{count}").strip()
            title = str(r.get("title") or r.get("record_title") or r.get("name") or "")
            status = str(r.get("status") or "")
            creator = str(r.get("creator") or r.get("created_by") or "")
            assigned = str(r.get("assigned_to") or r.get("assignedto") or r.get("owner") or "")

            rec_id = f"project_{project_number}_{bpname}_{rec_no}"

            c.execute('''
                INSERT INTO cached_bp_records (id, scope_type, project_number, bp_name, record_no, title, status, creator, assigned_to, raw_json, last_synced_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title,
                    status=excluded.status,
                    creator=excluded.creator,
                    assigned_to=excluded.assigned_to,
                    raw_json=excluded.raw_json,
                    last_synced_at=excluded.last_synced_at
            ''', (rec_id, "project", project_number, bpname, rec_no, title, status, creator, assigned, json.dumps(r), now))
            count += 1

            # Prepare vector document with RBAC metadata
            text = f"Project '{project_number}' BP '{bpname}' Record #{rec_no}: {title} | Status: {status} | Creator: {creator} | Assigned: {assigned} | Detail: {_format_record_text(r)}"
            meta = {
                "scope_type": "project",
                "project_number": project_number,
                "bp_name": bpname,
                "record_no": rec_no,
                "creator": creator,
                "assigned_to": assigned
            }
            doc_ids.append(rec_id)
            doc_texts.append(text)
            doc_metas.append(meta)

        conn.commit()
        conn.close()

        if vector_collection and doc_ids:
            try:
                vector_collection.upsert(ids=doc_ids, documents=doc_texts, metadatas=doc_metas)
            except Exception as e:
                logger.warning(f"Vector upsert failed for project {project_number} BP {bpname}: {e}")

        elapsed_ms = (time.time() - start_t) * 1000
        return True, count, f"Synced {count} records for Project '{project_number}' BP '{bpname}' in {elapsed_ms:.1f}ms"

    def sync_users(self) -> Tuple[bool, int, str]:
        if not self.client:
            return False, 0, "No UnifierClient provided."

        start_t = time.time()
        ok, data, code, _ = self.client.get_users()
        if not ok:
            return False, 0, f"API error (HTTP {code}): {data}"

        records = _extract_records(data)
        now = datetime.utcnow().isoformat()
        conn = get_db_connection()
        c = conn.cursor()

        count = 0
        for r in records:
            if not isinstance(r, dict):
                continue
            uname = str(r.get("user_name") or r.get("username") or r.get("email") or r.get("id") or "").strip()
            fname = str(r.get("first_name") or "")
            lname = str(r.get("last_name") or "")
            email = str(r.get("email") or "")
            status = str(r.get("status") or "Active")

            if not uname:
                continue

            c.execute('''
                INSERT INTO cached_users (user_name, first_name, last_name, email, status, raw_json, last_synced_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_name) DO UPDATE SET
                    first_name=excluded.first_name,
                    last_name=excluded.last_name,
                    email=excluded.email,
                    status=excluded.status,
                    raw_json=excluded.raw_json,
                    last_synced_at=excluded.last_synced_at
            ''', (uname, fname, lname, email, status, json.dumps(r), now))
            count += 1

        conn.commit()
        conn.close()
        elapsed_ms = (time.time() - start_t) * 1000
        return True, count, f"Synced {count} users in {elapsed_ms:.1f}ms"

    def sync_all(self) -> Dict[str, Any]:
        """
        Executes a complete sync across all Unifier endpoints into SQLite + ChromaDB.
        """
        start_t = time.time()
        summary = {}

        # 1. Projects
        p_ok, p_cnt, p_msg = self.sync_projects()
        summary["projects"] = {"success": p_ok, "count": p_cnt, "message": p_msg}

        # 2. Company BPs
        cbp_ok, cbp_cnt, cbp_msg = self.sync_company_bps()
        summary["company_bps"] = {"success": cbp_ok, "count": cbp_cnt, "message": cbp_msg}

        # 3. Users
        u_ok, u_cnt, u_msg = self.sync_users()
        summary["users"] = {"success": u_ok, "count": u_cnt, "message": u_msg}

        total_records = p_cnt + cbp_cnt + u_cnt
        elapsed_ms = (time.time() - start_t) * 1000

        conn = get_db_connection()
        c = conn.cursor()
        c.execute('''
            INSERT INTO sync_logs (sync_type, status, records_count, message, duration_ms, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', ("full_sync", "completed", total_records, json.dumps(summary), elapsed_ms, datetime.utcnow().isoformat()))
        conn.commit()
        conn.close()

        return {
            "success": True,
            "total_records_synced": total_records,
            "elapsed_ms": elapsed_ms,
            "summary": summary
        }


# --- LOCAL QUERY HELPER FUNCTIONS FOR FAST CHATBOT RETRIEVAL ---

def query_cached_projects() -> List[Dict[str, Any]]:
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT project_number, project_name, status, project_type, raw_json FROM cached_projects ORDER BY project_number ASC')
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def query_cached_users(filter_val: str = "") -> List[Dict[str, Any]]:
    conn = get_db_connection()
    c = conn.cursor()
    if filter_val:
        v = f"%{filter_val.strip()}%"
        c.execute('SELECT user_name, first_name, last_name, email, status, raw_json FROM cached_users WHERE user_name LIKE ? OR first_name LIKE ? OR last_name LIKE ? OR email LIKE ?', (v, v, v, v))
    else:
        c.execute('SELECT user_name, first_name, last_name, email, status, raw_json FROM cached_users')
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def query_cached_bp_records(project_number: str = "", bpname: str = "", record_no: str = "") -> List[Dict[str, Any]]:
    conn = get_db_connection()
    c = conn.cursor()
    query = 'SELECT * FROM cached_bp_records WHERE 1=1'
    params = []

    if project_number:
        query += ' AND project_number = ?'
        params.append(project_number)
    if bpname:
        query += ' AND bp_name = ?'
        params.append(bpname)
    if record_no:
        query += ' AND record_no = ?'
        params.append(record_no)

    c.execute(query, params)
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def query_vector_search(query_text: str, project_number: Optional[str] = None, bp_name: Optional[str] = None, n_results: int = 5) -> List[Dict[str, Any]]:
    col = get_vector_collection()
    if not col:
        return []

    try:
        where_meta = {}
        if project_number:
            where_meta["project_number"] = project_number
        if bp_name:
            where_meta["bp_name"] = bp_name

        kwargs = {"query_texts": [query_text], "n_results": n_results}
        if where_meta:
            kwargs["where"] = where_meta

        res = col.query(**kwargs)
        results = []
        if res and "documents" in res and res["documents"]:
            docs = res["documents"][0]
            metas = res.get("metadatas", [[]])[0]
            distances = res.get("distances", [[]])[0] if "distances" in res else []
            for i, doc in enumerate(docs):
                results.append({
                    "document": doc,
                    "metadata": metas[i] if i < len(metas) else {},
                    "distance": distances[i] if i < len(distances) else None
                })
        return results
    except Exception as e:
        logger.warning(f"Vector search exception: {e}")
        return []

def get_sync_stats() -> Dict[str, Any]:
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM cached_projects')
    p_cnt = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM cached_company_bps')
    cbp_cnt = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM cached_bp_records')
    rec_cnt = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM cached_users')
    u_cnt = c.fetchone()[0]
    c.execute('SELECT id, sync_type, status, records_count, duration_ms, created_at FROM sync_logs ORDER BY id DESC LIMIT 1')
    last_log = c.fetchone()
    conn.close()

    col = get_vector_collection()
    vec_cnt = col.count() if col else 0

    return {
        "cached_projects": p_cnt,
        "cached_company_bps": cbp_cnt,
        "cached_bp_records": rec_cnt,
        "cached_users": u_cnt,
        "vector_embeddings": vec_cnt,
        "last_sync": dict(last_log) if last_log else None
    }
