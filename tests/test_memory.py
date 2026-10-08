"""Tests for structured conversation memory (agent_memory.py)."""
import json
import pytest

import agent_memory
import sync_manager
from agent_memory import ConversationMemory


class FakeMsg:
    """Stand-in for a LangChain AIMessage carrying tool calls."""
    def __init__(self, tool_calls):
        self.tool_calls = tool_calls


@pytest.fixture()
def temp_dbs(tmp_path, monkeypatch):
    # Memory persistence DB
    mem_db = str(tmp_path / "chats_test.db")
    monkeypatch.setattr(agent_memory, "DB_PATH", mem_db)
    agent_memory.ensure_schema()
    # Cache DB (for project-name lookup)
    cache_db = str(tmp_path / "cache_test.db")
    monkeypatch.setattr(sync_manager, "DB_CACHE_PATH", cache_db)
    sync_manager.init_cache_db()
    conn = sync_manager.get_db_connection()
    conn.execute(
        "INSERT INTO cached_projects (project_number, project_name, status, project_type, raw_json, last_synced_at) "
        "VALUES (?,?,?,?,?,?)",
        ("001", "Datamato", "Active", "Standard", json.dumps({}), "now"),
    )
    conn.commit()
    conn.close()
    return mem_db


def test_slot_extraction_from_tool_calls(temp_dbs):
    mem = ConversationMemory(conversation_id="conv-1")
    messages = [FakeMsg([{"name": "query_project_bp_records",
                          "args": {"project_number": "001", "bpname": "Contract"}}])]
    mem.update_from_tool_calls(messages)
    assert mem.active_project_number == "001"
    assert mem.active_project_name == "Datamato"   # resolved from cache
    assert mem.active_bp_name == "Contract"


def test_persistence_round_trip(temp_dbs):
    mem = ConversationMemory(conversation_id="conv-2")
    mem.update_from_tool_calls([FakeMsg([{"name": "query_specific_project_bp_record",
                                          "args": {"project_number": "001", "bpname": "Contract", "record_no": "C-7"}}])])
    mem.save()

    reloaded = ConversationMemory.load("conv-2")
    assert reloaded.active_project_number == "001"
    assert reloaded.active_bp_name == "Contract"
    assert reloaded.last_record_no == "C-7"


def test_context_block_contains_active_entities(temp_dbs):
    mem = ConversationMemory(conversation_id="conv-3", active_project_number="001",
                             active_project_name="Datamato", active_bp_name="Contract")
    block = mem.context_block()
    assert "CURRENT CONTEXT" in block
    assert "001" in block and "Datamato" in block and "Contract" in block


def test_empty_context_block_is_blank(temp_dbs):
    assert ConversationMemory(conversation_id="conv-4").context_block() == ""


def test_later_tool_call_overrides_project(temp_dbs):
    mem = ConversationMemory(conversation_id="conv-5")
    mem.update_from_tool_calls([
        FakeMsg([{"name": "query_project_bp_catalog", "args": {"project_number": "001"}}]),
        FakeMsg([{"name": "query_project_bp_records", "args": {"project_number": "002", "bpname": "Vendor"}}]),
    ])
    assert mem.active_project_number == "002"
