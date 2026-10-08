"""
test_grounding.py — Phase 4 strict DB-grounding: the answer guard + currency safety.

The guard tests are pure (no DB/LLM). The pgstore currency test is skipped unless
POSTGRES_DSN is configured, so the default SQLite test run stays self-contained.
"""
import os
import pytest

from chatbot_engine import verify_grounding, _answer_facts, _nums


# ───────────────────────── grounding guard (pure) ─────────────────────────
def test_grounded_count_passes():
    corpus = "Exact count of matching records: 381 (project_number=001)."
    assert verify_grounding("There are 381 records in project 001.", corpus) == []


def test_fabricated_count_flagged():
    corpus = "Exact count of matching records: 381 (project_number=001)."
    bad = verify_grounding("There are 35 records.", corpus)
    assert "35" in bad


def test_amount_formatting_matches_by_value():
    # 49,334.00 in the answer must match 49334.0 in the tool output.
    corpus = "| Euro (EUR) | 6 | 49334.0 |"
    assert verify_grounding("EUR total is 49,334.00 across 6 rows.", corpus) == []


def test_bad_record_id_flagged():
    corpus = "Row: CON-00003.002 approved."
    bad = verify_grounding("See INV-99999 and CON-00003.002.", corpus)
    assert "INV-99999" in bad
    assert "CON-00003.002" not in bad


def test_single_digits_ignored():
    # Bare single digits are list indices / small counts, not data to verify.
    corpus = "no numbers of interest here"
    assert verify_grounding("Top 3 statuses; see item 2.", corpus) == []


def test_code_and_italic_spans_ignored():
    corpus = "count: 10"
    # Filter literals in backticks / italic source-notes must not trip the guard.
    assert verify_grounding("Applied `project_number=777`. _Source: BP 999._ Count: 10.", corpus) == []


def test_answer_facts_strips_ids_before_numbers():
    nums, ids = _answer_facts("INV-00002 has amount 1000.00")
    assert "INV-00002" in ids
    assert 1000.0 in nums
    assert 2.0 not in nums  # the '00002' inside the id must not become a number


def test_nums_parses_commas_and_decimals():
    got = _nums("1,234.50 and 381 and 0.9615")
    assert 1234.5 in got and 381.0 in got and 0.96 in got


# ───────────────────── currency safety (needs Postgres) ─────────────────────
_PG = bool(os.getenv("POSTGRES_DSN", "").strip())


@pytest.mark.skipif(not _PG, reason="POSTGRES_DSN not configured")
def test_currency_aggregation_never_combines():
    import pgstore
    rows = pgstore.aggregate_amounts(project_number="001", bp_name="Change Order")
    # One row per currency, each with its own exact subtotal — never a merged total.
    currencies = [r["currency"] for r in rows]
    assert len(currencies) == len(set(currencies))          # distinct currencies
    assert all("total" in r and "record_count" in r for r in rows)
    # Per-currency counts must sum to the exact overall count (consistency).
    total_rows = sum(r["record_count"] for r in rows)
    assert total_rows == pgstore.count_records(project_number="001", bp_name="Change Order")
