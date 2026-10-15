"""
test_suggestions.py — Unit tests for the "Suggestions" / "Did you mean?" feature.
"""
import pytest
import retrieval
import agent_tools


def test_suggest_matches_empty_query():
    res = retrieval.suggest_matches("")
    assert res == {"projects": [], "records": [], "business_processes": []}


def test_suggest_similar_entities_empty():
    ans = agent_tools.suggest_similar_entities.invoke({"query": ""})
    assert "Please provide a query" in ans


def test_suggest_matches_structure():
    res = retrieval.suggest_matches("Datamato")
    assert "projects" in res
    assert "records" in res
    assert "business_processes" in res


def test_suggest_similar_entities_tool():
    ans = agent_tools.suggest_similar_entities.invoke({"query": "chng order"})
    assert "Matching" in ans or "Business Process" in ans
