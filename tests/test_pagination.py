"""Tests for pagination / 'show more' follow-through (fixes the YES/YES/NO loop)."""
import json
import pytest

import sync_manager
import agent_memory
import agent_tools
import retrieval
from agent_memory import ConversationMemory


@pytest.fixture()
def seeded(tmp_path, monkeypatch):
    monkeypatch.setattr(sync_manager, "DB_CACHE_PATH", str(tmp_path / "cache.db"))
    # Pagination logic is tested against the seeded SQLite fixture; force that path
    # even if POSTGRES_DSN is set in the environment.
    monkeypatch.setattr(retrieval, "_use_pg", lambda: False)
    sync_manager.init_cache_db()
    monkeypatch.setattr(agent_memory, "DB_PATH", str(tmp_path / "chats.db"))
    agent_memory.ensure_schema()
    conn = sync_manager.get_db_connection()
    for i in range(45):  # 45 company Vendor records
        conn.execute(
            "INSERT INTO cached_bp_records (id, scope_type, project_number, bp_name, record_no, title, status, creator, assigned_to, raw_json, last_synced_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (f"c{i}", "company", "", "Vendor", f"V-{i:03d}", f"Vendor {i}", "Active", "a", "b", json.dumps({}), "now"),
        )
    conn.commit()
    conn.close()


def _show_more(mem):
    token = agent_tools.set_request_context(client=None, memory=mem)
    try:
        return agent_tools.show_more_records.invoke({})
    finally:
        agent_tools.reset_request_context(token)


def test_show_more_pages_and_advances(seeded):
    mem = ConversationMemory(conversation_id="c")
    mem.set_list_state(scope="company", bpname="Vendor", project_number="", shown=20, total=45)

    out = _show_more(mem)
    assert "records 21-40 of 45" in out
    assert mem.list_state["shown"] == 40           # advanced
    assert "V-020" in out and "V-039" in out       # the second page

    out2 = _show_more(mem)
    assert "records 41-45 of 45" in out2
    assert mem.list_state["shown"] == 45
    assert "End of records" in out2

    out3 = _show_more(mem)
    assert "That's all 45" in out3                  # nothing left


def test_show_more_without_active_list(seeded):
    mem = ConversationMemory(conversation_id="c2")
    out = _show_more(mem)
    assert "no active list" in out.lower()


def test_show_more_falls_back_to_active_bp(seeded):
    # No prior listing, but the conversation is "about" Vendor → 'show' should list it.
    mem = ConversationMemory(conversation_id="c6")
    mem.active_bp_name = "Vendor"
    out = _show_more(mem)
    assert "records 1-20 of 45" in out
    assert mem.list_state["shown"] == 20


class _Msg:
    def __init__(self, tc):
        self.tool_calls = tc


def test_stale_list_state_cleared_on_bp_change(seeded):
    # An open list for one BP must not survive a pivot to a different BP (the Budget-R bug).
    mem = ConversationMemory(conversation_id="c7")
    mem.set_list_state(scope="project", bpname="Budget-R", project_number="001", shown=20, total=30)
    mem.update_from_tool_calls([_Msg([{"name": "count_matching_records",
                                       "args": {"bp_name": "Change Order", "project_number": "001"}}])])
    assert not mem.list_state          # stale Budget-R list dropped
    assert mem.active_bp_name == "Change Order"


def test_open_offer_surfaces_in_context_block(seeded):
    mem = ConversationMemory(conversation_id="c3")
    mem.set_list_state(scope="company", bpname="Vendor", project_number="", shown=20, total=45)
    block = mem.context_block()
    assert "show more" in block.lower()
    assert "shown 20 of 45" in block


def test_offer_closed_when_all_shown(seeded):
    mem = ConversationMemory(conversation_id="c4")
    mem.set_list_state(scope="company", bpname="Vendor", project_number="", shown=45, total=45)
    assert mem.has_open_list() is False


def test_list_state_persists(seeded):
    mem = ConversationMemory(conversation_id="c5")
    mem.set_list_state(scope="project", bpname="Contract", project_number="001", shown=20, total=60)
    mem.save()
    reloaded = ConversationMemory.load("c5")
    assert reloaded.list_state["bpname"] == "Contract"
    assert reloaded.list_state["shown"] == 20
    assert reloaded.has_open_list() is True
