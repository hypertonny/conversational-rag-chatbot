"""Tests for BP scope-awareness and project-number resolution (the image bugs)."""
import json
import pytest

import sync_manager
import retrieval
import agent_tools


@pytest.fixture()
def seeded(tmp_path, monkeypatch):
    monkeypatch.setattr(sync_manager, "DB_CACHE_PATH", str(tmp_path / "cache.db"))
    sync_manager.init_cache_db()
    conn = sync_manager.get_db_connection()
    # Company BP catalog: Vendor is company-level
    conn.execute("INSERT INTO cached_company_bps (bp_name, bp_model_name, studio_source, raw_json, last_synced_at) "
                 "VALUES (?,?,?,?,?)", ("Vendor", "uxueven", "database", "{}", "now"))
    # Distinct projects that are NOT zero-pad equivalent
    for num, name in [("001", "Test Project 1"), ("0001", "Nik_test"), ("000001", "OracleNewR")]:
        conn.execute("INSERT INTO cached_projects (project_number, project_name, status, project_type, raw_json, last_synced_at) "
                     "VALUES (?,?,?,?,?,?)", (num, name, "Active", "Standard", "{}", "now"))
    # Company Vendor records
    for i in range(3):
        conn.execute("INSERT INTO cached_bp_records (id, scope_type, project_number, bp_name, record_no, title, status, creator, assigned_to, raw_json, last_synced_at) "
                     "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     (f"c{i}", "company", "", "Vendor", f"V-{i}", f"Vendor {i}", "Active", "a", "b", json.dumps({}), "now"))
    conn.commit()
    conn.close()


def test_is_company_bp(seeded):
    assert retrieval.is_company_bp("Vendor") is True
    assert retrieval.is_company_bp("vendor") is True      # case-insensitive
    assert retrieval.is_company_bp("Contract") is False


def test_find_projects_exact_not_padded(seeded):
    res = retrieval.find_projects("001")
    assert res["exact"] is not None
    assert res["exact"]["project_number"] == "001"       # exact, not '0001'
    # The distinct near-variants surface as candidates but never as the exact match
    nums = {c["project_number"] for c in res["candidates"]}
    assert "001" in nums


def test_find_projects_no_match(seeded):
    res = retrieval.find_projects("zzz-nope")
    assert res["exact"] is None
    assert res["candidates"] == []


class FakeClient:
    def __init__(self, project_bps):
        self._pbps = project_bps

    def get_project_bp_list(self, project_number):
        return True, {"data": [{"bp_name": n} for n in self._pbps]}, 200, 1.0

    def get_company_bp_records(self, bpname, **kw):
        return True, {"data": [{"record_no": "V-1", "title": "Vendor 1", "status": "Active"}]}, 200, 1.0

    def get_project_bp_records(self, project_number, bpname, **kw):
        return True, {"data": []}, 200, 1.0


def _call_project_records(client, project_number, bpname):
    token = agent_tools.set_request_context(client=client, memory=None)
    try:
        return agent_tools.query_project_bp_records.invoke(
            {"project_number": project_number, "bpname": bpname}
        )
    finally:
        agent_tools.reset_request_context(token)


def test_company_bp_not_falsely_attributed_to_project(seeded):
    # Vendor is NOT in this project's catalog -> must be reported as company-level, not project-specific
    client = FakeClient(project_bps=["Contract", "RFI"])
    out = _call_project_records(client, "001", "Vendor")
    assert "company-level" in out.lower()
    assert "Company BP 'Vendor'" in out


def test_genuine_project_bp_uses_project_scope(seeded):
    # Vendor IS in this project's catalog -> project path is used (no company note)
    client = FakeClient(project_bps=["Vendor", "Contract"])
    out = _call_project_records(client, "001", "Vendor")
    assert "company-level" not in out.lower()
    assert "project '001'" in out.lower()
