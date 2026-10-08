"""End-to-end (LLM-free) test of the multi-turn memory scenario:

Turn 1: user establishes a project -> the agent's tool call resolves project 001.
Turn 2: a follow-up that names no project must still carry project 001 into the
        system prompt, so the agent reuses it instead of re-asking.
"""
import json
import pytest

import agent_memory
import sync_manager
from agent_memory import ConversationMemory
from agent_prompts import build_system_prompt


class FakeMsg:
    def __init__(self, tool_calls):
        self.tool_calls = tool_calls


@pytest.fixture()
def temp_dbs(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_memory, "DB_PATH", str(tmp_path / "chats.db"))
    agent_memory.ensure_schema()
    monkeypatch.setattr(sync_manager, "DB_CACHE_PATH", str(tmp_path / "cache.db"))
    sync_manager.init_cache_db()
    conn = sync_manager.get_db_connection()
    conn.execute(
        "INSERT INTO cached_projects (project_number, project_name, status, project_type, raw_json, last_synced_at) "
        "VALUES (?,?,?,?,?,?)",
        ("001", "Datamato", "Active", "Standard", json.dumps({}), "now"),
    )
    conn.commit()
    conn.close()


def test_project_resolved_turn1_is_reused_turn2(temp_dbs):
    conv_id = "conv-multiturn"

    # ---- Turn 1: "Tell me about project Datamato" ----
    mem = ConversationMemory.load(conv_id)
    turn1_messages = [
        FakeMsg([{"name": "query_active_projects", "args": {}}]),
        FakeMsg([{"name": "query_project_bp_catalog", "args": {"project_number": "001"}}]),
    ]
    mem.update_from_tool_calls(turn1_messages)
    mem.save()

    # ---- Turn 2: "tell me the BP record" (no project named) ----
    mem2 = ConversationMemory.load(conv_id)
    prompt = build_system_prompt(mem2.context_block())

    # The resolved project must be present in turn 2's system prompt.
    assert "Active project: 001 (Datamato)" in prompt
    assert "reuse" in prompt.lower()
    # And the agent is instructed to use it rather than re-ask.
    assert "do NOT re-ask" in prompt or "Only ask for clarification" in prompt


def test_prompt_without_memory_has_no_context_block(temp_dbs):
    prompt = build_system_prompt(ConversationMemory.load("fresh").context_block())
    # The injected block's header must be absent (the static body may still mention
    # "CURRENT CONTEXT" in its rules, so match the injected header line specifically).
    assert "# CURRENT CONTEXT (resolved earlier" not in prompt
