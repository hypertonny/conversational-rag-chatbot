"""
qa_prompt_test.py — Prompt/behaviour test harness for the Unifier chatbot.

Acts like a QA tester: computes ground truth from the Postgres store, fires a
battery of natural user questions at the LIVE /api/chat endpoint (real agent +
Gemini + Postgres), and grades each answer. Multi-turn cases reuse a
conversation_id so memory/context is exercised.

Run:  POSTGRES_DSN=... python qa_prompt_test.py [http://localhost:8501]
"""
import os
import re
import sys
import json
import time
import uuid
import requests

import pgstore

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8501"
CHAT = BASE.rstrip("/") + "/api/chat"


def ask(prompt, conversation_id=None, history=None):
    body = {"prompt": prompt, "conversation_id": conversation_id, "chat_history": history or []}
    t0 = time.time()
    try:
        r = requests.post(CHAT, json=body, timeout=120)
        ans = r.json().get("answer", "") if r.ok else f"HTTP {r.status_code}: {r.text[:200]}"
    except Exception as e:
        ans = f"REQUEST ERROR: {e}"
    return ans, round(time.time() - t0, 1)


def has(ans, *subs):
    a = ans.lower()
    return all(s.lower() in a for s in subs)


def has_num(ans, n):
    return bool(re.search(rf"(?<!\d){n}(?!\d)", ans.replace(",", "")))


# ── Ground truth from the store ──
GT = {
    "rec_001": pgstore.count_records(project_number="001"),
    "co_001": pgstore.count_records(project_number="001", bp_name="change order"),
    "po_001": pgstore.count_records(project_number="001", bp_name="purchase order"),
    "rec_0000567": pgstore.count_records(project_number="0000567"),
    "status_001": pgstore.group_records("status", project_number="001"),
    "cur_co_001": pgstore.aggregate_amounts(project_number="001", bp_name="change order"),
    "vendor_company": pgstore.is_company_bp("Vendor"),
    "resolve_001": pgstore.find_projects("001").get("exact"),
}
print("GROUND TRUTH:", json.dumps({k: v for k, v in GT.items() if k not in ("status_001", "cur_co_001")}, default=str))
print("  status_001:", GT["status_001"][:4])
print("  cur_co_001:", GT["cur_co_001"])
print("=" * 100)

results = []  # (id, category, question, answer, latency, verdict, note)


def record(cid, cat, q, ans, lat, ok, note=""):
    results.append((cid, cat, q, ans, lat, "PASS" if ok else "FAIL", note))
    print(f"[{ 'PASS' if ok else 'FAIL' }] {cid} ({lat}s) {q}\n   -> {ans[:220].replace(chr(10),' ')}\n")


# ── Single-turn battery (natural QA-tester questions) ──
co = GT["co_001"]; po = GT["po_001"]; rec = GT["rec_001"]

a, l = ask("How many records are there in project 001?")
record("Q1", "count", "records in 001", a, l, has_num(a, rec), f"expect {rec}")

a, l = ask("How many change orders are in project 001?")
record("Q2", "count+filter", "change orders in 001", a, l, has_num(a, co), f"expect {co}")

a, l = ask("Break down the records in project 001 by status.")
top = GT["status_001"][0]
record("Q3", "group-by", "001 by status", a, l, has_num(a, top["record_count"]) and has(a, top["value"]), f"top {top}")

a, l = ask("What is the total value of change orders in project 001?")
eur = next((r for r in GT["cur_co_001"] if "EUR" in r["currency"]), None)
usd = next((r for r in GT["cur_co_001"] if "USD" in r["currency"]), None)
ok_cur = (not eur or has_num(a, int(eur["total"]))) and (not usd or has_num(a, int(usd["total"])))
record("Q4", "currency-safe", "total CO value 001", a, l, ok_cur, f"EUR/USD separate {GT['cur_co_001']}")

a, l = ask("What is project 001?")
nm = (GT["resolve_001"] or {}).get("project_name", "")
record("Q5", "resolve", "what is project 001", a, l, has(a, nm), f"expect {nm}")

a, l = ask("Is Vendor a company-level business process or project-level?")
record("Q6", "scope", "Vendor company-level?", a, l, has(a, "company"), "Vendor is company-level")

a, l = ask("How many change orders are in project 0000567?")
ok7 = ("sync" in a.lower() or "not" in a.lower() or "no record" in a.lower()) and not re.search(r"\b0 change orders\b", a.lower())
record("Q7", "incomplete-store", "change orders in 0000567", a, l, ok7, "should flag not-ingested, not flat 0")

a, l = ask("What's the weather in London today?")
record("Q8", "out-of-scope", "weather", a, l, has(a, "unifier"), "scope note, no fabrication")

a, l = ask("hi")
record("Q9", "greeting", "hi", a, l, not has_num(a, rec) and len(a) < 1200, "greeting, no tool dump")

a, l = ask("How many flux-capacitor records are in project 001?")
ok10 = ("0" in a or "no " in a.lower() or "not" in a.lower())
record("Q10", "grounding", "nonexistent BP", a, l, ok10, "must not fabricate")

a, l = ask("Give me the dollar budget exposure and cost forecast for project 001.")
record("Q11", "missing-field", "budget/forecast 001", a, l, has(a, "not") or "database" in a.lower(), "say not in DB; no invented $")

# ── Multi-turn (context reuse) ──
c1 = f"qa-{uuid.uuid4().hex[:8]}"
a, l = ask("What is project 001?", conversation_id=c1)
record("Q12a", "multiturn", "establish 001", a, l, has(a, nm), "sets context")
a, l = ask("How many change orders does it have?", conversation_id=c1)
record("Q12b", "multiturn", "'it' -> 001 change orders", a, l, has_num(a, co), f"reuse 001, expect {co}")

c2 = f"qa-{uuid.uuid4().hex[:8]}"
a, l = ask("0000567 what is the project name for this project number?", conversation_id=c2)
record("Q13a", "multiturn", "establish 0000567", a, l, has(a, "building construction"), "sets context")
a, l = ask("How many purchase orders are there in this?", conversation_id=c2)
ok13 = ("0000567" in a or "building construction" in a.lower()) and "what is the project number" not in a.lower()
record("Q13b", "multiturn", "'this' -> reuse 0000567 (screenshot bug)", a, l, ok13, "must NOT re-ask for project number")

# ── Summary ──
print("=" * 100)
p = sum(1 for r in results if r[5] == "PASS")
print(f"SUMMARY: {p}/{len(results)} passed")
with open("qa_results.json", "w", encoding="utf-8") as f:
    json.dump([{"id": r[0], "category": r[1], "question": r[2], "answer": r[3],
                "latency_s": r[4], "verdict": r[5], "note": r[6]} for r in results], f, indent=2)
print("Wrote qa_results.json")
