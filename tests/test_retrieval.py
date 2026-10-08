"""Tests for structured SQL retrieval over the local cache (retrieval.py)."""
import os
import json
import pytest

import sync_manager
import retrieval


@pytest.fixture()
def seeded_db(tmp_path, monkeypatch):
    """Point the cache DB at a temp file, create the schema, and seed BP records."""
    db_path = str(tmp_path / "unifier_cache_test.db")
    monkeypatch.setattr(sync_manager, "DB_CACHE_PATH", db_path)
    # These tests exercise the SQLite implementation + fixture; force that path even
    # when a POSTGRES_DSN is present in the ambient environment.
    monkeypatch.setattr(retrieval, "_use_pg", lambda: False)
    sync_manager.init_cache_db()

    rows = [
        # id, scope, project, bp, record_no, title, status, creator, assigned_to
        ("1", "project", "001", "Contract", "C-1", "Foundation", "Draft", "alice", "bob"),
        ("2", "project", "001", "Contract", "C-2", "Steel", "Approved", "alice", "carol"),
        ("3", "project", "001", "Contract", "C-3", "Concrete", "Draft", "dave", "bob"),
        ("4", "project", "002", "Vendor", "V-1", "AcmeCorp", "Active", "alice", "bob"),
        ("5", "company", "", "Vendor", "V-9", "GlobalSup", "Draft", "dave", "carol"),
    ]
    conn = sync_manager.get_db_connection()
    for r in rows:
        conn.execute(
            "INSERT INTO cached_bp_records (id, scope_type, project_number, bp_name, record_no, "
            "title, status, creator, assigned_to, raw_json, last_synced_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (*r, json.dumps({"title": r[5]}), "now"),
        )
    conn.commit()
    conn.close()
    return db_path


def test_count_all(seeded_db):
    assert retrieval.count_records() == 5


def test_count_filtered(seeded_db):
    assert retrieval.count_records(status="Draft") == 3
    assert retrieval.count_records(bp_name="Contract") == 3
    assert retrieval.count_records(bp_name="Contract", status="Draft") == 2
    assert retrieval.count_records(project_number="001") == 3


def test_count_keyword(seeded_db):
    # keyword matches title OR raw_json
    assert retrieval.count_records(keyword="Concrete") == 1


def test_group_records(seeded_db):
    rows = retrieval.group_records("status")
    counts = {r["value"]: r["record_count"] for r in rows}
    assert counts["Draft"] == 3
    assert counts["Approved"] == 1
    assert counts["Active"] == 1


def test_group_records_rejects_bad_column(seeded_db):
    with pytest.raises(ValueError):
        retrieval.group_records("raw_json")


def test_list_records_pagination(seeded_db):
    page1 = retrieval.list_records(limit=2, offset=0)
    assert page1["total"] == 5
    assert len(page1["rows"]) == 2
    page2 = retrieval.list_records(limit=2, offset=2)
    assert len(page2["rows"]) == 2
    # No overlap between pages
    ids1 = {r["record_no"] for r in page1["rows"]}
    ids2 = {r["record_no"] for r in page2["rows"]}
    assert ids1.isdisjoint(ids2)


def test_distinct_values(seeded_db):
    statuses = set(retrieval.distinct_values("status"))
    assert statuses == {"Draft", "Approved", "Active"}
    bps = set(retrieval.distinct_values("bp_name"))
    assert bps == {"Contract", "Vendor"}
