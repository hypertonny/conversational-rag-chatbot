# 📋 Project Checklist — Oracle Primavera Unifier RAG Portal

> Living document. We update it as we go so progress stays consistent and traceable.
> **Last updated:** 2026-10-12

---

## 🤝 Working Agreement (rules for this phase of work)
1. **Builds:** Full `docker compose build` is slow — **HOLD** full rebuilds until the build is optimized to a better/faster version. For now, iterate with **`docker cp`** (quick: copy changed files into the running container + restart).
2. **Current focus:** **Phase 5** (eval + observability). Create/update docs as we proceed, in a structured manner.
3. **Ingestion / data source:** **RESOLVED (2026-10-12).** During **testing** → **live cache-on-read**: query hits the live Unifier API, caches the result into Postgres (so repeats are instant + the store fills progressively), and answers exactly from it. **Production (future, needs its own go)** → one full data dump into Postgres, then gradual incremental sync as Unifier updates. The old "full bulk ingest now" is NOT happening.
4. **Deploy:** **Last.** Nothing goes to the live client site (`client.apps.bnhverse.com`) until everything else is done and approved.

## 🔑 Status Legend
✅ Done & verified  |  🔄 In progress  |  ⏳ Pending  |  ⏸️ Held (by decision)  |  💬 Needs discussion

---

## ✅ Completed & Verified
| # | Item | Notes |
|---|------|-------|
| C1 | **P1 — Postgres+pgvector store** | schema, DAL, backfill. 42,748 projects, 1,904 records. count(001)=381 |
| C2 | **P2 — Embeddings + CDC** | `pg_ingest.py`, 1,904 chunks (all-MiniLM 384d), HNSW+tsv, content_hash CDC |
| C3 | **P3 — Retrieval wiring** | `retrieval.py` backend-switch (PG ↔ SQLite fallback) |
| C4 | **P4 — Strict grounding + citations** | G1–G6, F1–F4 hybrid format, currency-safe, grounding guard |
| C5 | **Responsive UI (RWD)** | tablet/phone breakpoints, chat history redesign |
| C6 | **Docker image optimization** | multi-stage, CPU torch, baked model → 541 MB |
| C7 | **Credential hiding** | `/api/config` booleans only; "Loaded from env" + override UI |
| C8 | **Case-insensitive `record_no`** | `rep-00030` now matches `REP-00030` (DB graph vs chat parity) |
| C9 | **Empty-answer → conversational fallback** | no more raw tool-output dumps |
| C10 | **DB Graph opens in same tab** | removed `target="_blank"` |
| C11 | **All code committed + pushed** | commit `69d6951` on `origin/main` |
| C12 | **Live cache-on-read (testing mode)** | `LIVE_FIRST=true` (default). Structured tools pull the project's live records → cache into PG → answer exactly. TTL (10 min) avoids re-crawl. Verified: cold project 002 (wiped) → live-crawled 61 BPs → 85 records repopulated → exact "85"; warm repeat 2.5s; empty shell (003) → genuine 0. 40 tests pass. |
| C13 | **Case-insensitive project resolution + record-vs-project routing** | `find_projects` now matches `prj202`=`PRJ202` (case-insensitive exact, still NOT zero-pad). Prompt M13: a `LETTERS-DIGITS` token (BUDG-00001) is a RECORD → search records, never resolve_project. Verified: "prj202" resolves; "is BUDG-00001 approved in prj202" → "Approved"; typo "bugd-00001" → searched as record, honest not-found. |
| C14 | **"Suggestions" / Did-You-Mean (`pg_trgm`)** | PostgreSQL trigram similarity matching across projects, records, and BPs. Added GIN trigram indexes in `_SCHEMA`. Implemented `suggest_matches` in DAL, new `/api/suggest` API endpoint, `suggest_similar_entities` agent tool, automatic did-you-mean fallbacks in `resolve_project` and record lookups, and Prompt Rule M14. 45/45 tests passing. Deployed via `docker cp`. |
| C15 | **Model updated to `gemini-3.5-flash-lite`** | Upgraded default model configuration across `.env`, `docker-compose.yml`, `server.py`, `chatbot_engine.py`, and frontend UI (`index.html`/`app.js`). Recreated container and verified via `/api/config`. |
| C16 | **Clean JSON block content normalization** | Fixed raw python list-of-dicts `[{'type':'text', 'text':'...', 'extras':...}]` leaking to frontend by adding `_normalize_content` in `chatbot_engine.py`. Extracts clean markdown text across both legacy string and new block format responses. 45/45 tests pass. Deployed via `docker cp`. |
| C17 | **Foreign key fix for custom/restored conversation IDs** | In `server.py`, added upsert check for `conversations` before inserting user/assistant messages, preventing SQLite `FOREIGN KEY constraint failed` errors when client sends custom conversation IDs. Deployed via `docker cp`. |
| C18 | **Dynamic table spacing & responsive wrapper** | Replaced rigid `display: block` on table with real `display: table` and dynamic column auto-distribution. Wrapped all markdown tables in `.chat-table-wrapper` with horizontal touch scroll so wide tables never overflow or break. Eliminated the dead white void on the right of 2- and 3-column tables. Verified in browser and mobile view. Committed and pushed. |

---

## 🔄 In Progress
| # | Item | Status |
|---|------|--------|
| P5 | **Phase 5 — Eval & Observability** | 🔄 starting now |

### Phase 5 breakdown
- [ ] **5.1 Eval harness** — golden-set regression (001=381, change-orders=22, currency per-currency, "not in database" refusal, case-insensitive lookup, context reuse). Runnable + repeatable.
- [ ] **5.2 Observability** — per-stage latency logging (tool calls, LLM, grounding guard) + retrieval metrics.
- [ ] **5.3 Latency review** — investigate ~22–30s responses; propose/trial optimizations.
- [ ] **5.4 Docs** — document eval usage + metrics in a structured docs file.

---

## ⏳ / 💬 / ⏸️ Not Started
| # | Item | Status | Reason |
|---|------|--------|--------|
| N1 | **Docker build → persist via rebuild** | ⏸️ Held | Builds slow; use `docker cp` for now (Agreement #1) |
| N2 | **Production full dump + incremental sync** | ⏸️ Held | Future; needs its own go. Testing uses live cache-on-read (C12) |
| N3 | **Deploy to live client site** | ⏸️ Held | Last step, outward-facing (Agreement #4) |

---

## 🛠️ Quick-iterate (cp) procedure — our current build shortcut
```bash
# Copy changed files into the running container and restart (fast, no full build)
docker cp <file> unifier-dashboard:/app/<file>
docker compose restart unifier-dashboard
```
Reminder: these are ephemeral until a real `docker compose build`. Code is safe in git regardless.

---

## 📝 Update Log
- **2026-10-12** — Created checklist. Agreement set: hold full builds (use cp), do Phase 5 next, hold ingestion (discuss), deploy last. P1–P4 + UI/Docker/fixes confirmed done & committed (`69d6951`).
- **2026-10-12** — Ingestion decision RESOLVED: testing = **live cache-on-read** (`LIVE_FIRST=true`), production = full dump + incremental sync (future). Implemented `pg_sync.cache_scope` + `_ensure_live_scope` wired into all structured tools (count/group/list/aggregate/status-summary). Verified cold-read repopulation (002→85), warm TTL speed, empty-shell genuine 0. Deployed via `docker cp`. 40 tests pass.
- **2026-10-12** — Fixed 2 bugs from screenshots: (1) project resolution was case-sensitive (`prj202` ≠ `PRJ202`) → now case-insensitive exact in `find_projects`; (2) a record number (`BUDG-00001`) was misread as a project → prompt M13 routes `LETTERS-DIGITS` tokens to record search. Verified via chat. Deployed via `docker cp`. 40 tests pass.
- **2026-10-15** — Implemented **"Suggestions" / Did-You-Mean (`pg_trgm`)**: Added `pg_trgm` extension and GIN trigram indexes to `pgstore.py`. Implemented `suggest_matches` DAL for fuzzy typo matching across projects, records, and BPs. Added `/api/suggest` REST endpoint and `suggest_similar_entities` agent tool. Integrated automatic did-you-mean fallback in `resolve_project` and record lookups. Hardened grounding guard so user query tokens don't trigger false-positive caveats. 45/45 tests pass. Deployed via `docker cp`.
- **2026-10-16** — Model upgraded to **`gemini-3.5-flash-lite`** across `.env`, `docker-compose.yml`, backend engine, and frontend selectors. Verified live via `/api/config`.
- **2026-10-16** — Fixed raw content block leak: `_normalize_content` in `chatbot_engine.py` extracts pure markdown text from LangChain/Gemini 3.5 block structures (`[{'type':'text', 'text':...}]`), stripping raw dictionary strings and `extras` metadata. Fixed conversation table foreign key insert in `server.py`. Ran 10-turn multi-turn stress test covering records, typos, counts, currency totals, context switching, and company BPs with 100% pass rate. Deployed via `docker cp`. 45/45 tests pass.
