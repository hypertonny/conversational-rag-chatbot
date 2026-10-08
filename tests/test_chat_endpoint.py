"""Tests for the /api/chat endpoint correctness (server.chat):
- the SQLite connection is always closed (even on error)
- an engine failure returns valid JSON flagged as an error, not a 500
- the happy path persists messages and returns a conversation_id
"""
import pytest

import server
import agent_memory


class TrackedConn:
    """Wraps a real sqlite connection and records whether close() was called."""
    def __init__(self, real):
        self._real = real
        self.closed = False

    def cursor(self):
        return self._real.cursor()

    def execute(self, *a, **k):
        return self._real.execute(*a, **k)

    def commit(self):
        return self._real.commit()

    def close(self):
        self.closed = True
        return self._real.close()


@pytest.fixture()
def temp_env(tmp_path, monkeypatch):
    db = str(tmp_path / "chats.db")
    monkeypatch.setattr(server, "DB_PATH", db)
    monkeypatch.setattr(agent_memory, "DB_PATH", db)
    server.init_db()
    agent_memory.ensure_schema()

    created = {}

    real_connect = server.get_chat_db_connection

    def tracked_connect():
        conn = TrackedConn(real_connect())
        created["conn"] = conn
        return conn

    monkeypatch.setattr(server, "get_chat_db_connection", tracked_connect)
    return created


def _req(**kw):
    base = dict(bearer_token="x", base_url="", gemini_api_key="k", provider="gemini",
                prompt="hello", chat_history=[], conversation_id=None)
    base.update(kw)
    return server.ChatReq(**base)


def test_happy_path_returns_conversation_id(temp_env, monkeypatch):
    class FakeEngine:
        def get_chat_response(self, **kw):
            return "Here are your projects."
    monkeypatch.setattr(server, "get_engine", lambda gemini_key=None: FakeEngine())

    out = server.chat(_req())
    assert out["answer"] == "Here are your projects."
    assert out["conversation_id"]
    assert not out.get("error")
    assert temp_env["conn"].closed is True


def test_error_path_returns_json_and_closes_conn(temp_env, monkeypatch):
    class BoomEngine:
        def get_chat_response(self, **kw):
            raise RuntimeError("gemini exploded")
    monkeypatch.setattr(server, "get_engine", lambda gemini_key=None: BoomEngine())

    out = server.chat(_req(prompt="trigger error"))
    assert out["error"] is True
    assert "detail" in out
    assert isinstance(out["answer"], str)          # valid JSON answer, not a 500
    assert temp_env["conn"].closed is True          # connection not leaked on error
