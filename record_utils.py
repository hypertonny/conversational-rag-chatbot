"""
record_utils.py — Shared helpers for parsing and formatting Unifier records.

Single source of truth for record extraction/formatting, previously duplicated
across chatbot_engine.py and sync_manager.py.
"""
from typing import Any, List


def extract_records(data: Any) -> List[Any]:
    """Safely extract a list of records from a Unifier API response.

    Unifier wraps record lists under a variety of keys depending on the endpoint,
    so probe the common ones before falling back to treating the payload itself
    as a single record.
    """
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


def format_record(r: dict, max_fields: int = 40) -> str:
    """Format a single record dict into a readable pipe-separated string.

    Bounded by ``max_fields`` so a wide record doesn't blow up the LLM context.
    """
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


def normalize_user(r: dict) -> dict:
    """Map Unifier's `uuu_user_*` user fields to a stable, friendly shape.

    The /admin/user/get API returns keys like uuu_user_name, uuu_user_firstname,
    uuu_user_lastname, uuu_user_email, uuu_user_loginname, uuu_user_status ('1'=active),
    ue_usr_EmpIDTB50, uuu_user_title, uuu_user_company. Older/other shapes may use plain
    names — probe both so the tools never render blank rows.
    """
    def pick(*keys):
        for k in keys:
            v = r.get(k)
            if v not in (None, ""):
                return str(v)
        return ""

    first = pick("uuu_user_firstname", "first_name", "firstName")
    last = pick("uuu_user_lastname", "last_name", "lastName")
    name = pick("uuu_user_name", "name") or f"{first} {last}".strip()
    login = pick("uuu_user_loginname", "user_name", "username", "login") or name
    status_raw = pick("uuu_user_status", "status")
    status = {"1": "Active", "0": "Inactive", "": ""}.get(status_raw, status_raw) or "Active"
    return {
        "login": login,
        "name": name or login,
        "first_name": first,
        "last_name": last,
        "email": pick("uuu_user_email", "email"),
        "status": status,
        "emp_id": pick("ue_usr_EmpIDTB50", "employee_id", "emp_id"),
        "title": pick("uuu_user_title", "title"),
        "company": pick("uuu_user_company", "company"),
        "phone": pick("uuu_user_workphone", "uuu_user_mobilephone", "phone"),
    }


def format_record_text(r: dict) -> str:
    """Flatten a record's scalar fields into embedding-friendly text.

    Used when building ChromaDB vector documents — only truthy scalar values are
    included so the embedding stays focused on meaningful content.
    """
    parts = []
    for k, v in r.items():
        if isinstance(v, (str, int, float, bool)) and v:
            parts.append(f"{k}: {v}")
    return " | ".join(parts)
