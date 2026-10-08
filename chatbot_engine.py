"""
chatbot_engine.py — Orchestrator for the Primavera Unifier Agentic RAG chatbot.

Thin coordinator: it compiles the LangGraph ReAct agent ONCE per (api key, model)
and reuses it across requests. The per-request Unifier client and conversation
memory are passed to the tools through a ContextVar (see agent_tools), and the
resolved conversation slots are injected into the system prompt each turn.

Tool definitions live in agent_tools.py, the prompt in agent_prompts.py, and
structured/semantic retrieval in retrieval.py.
"""
import os
import re
import logging
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("ChatbotEngine")

RECURSION_LIMIT = 25          # hard cap on ReAct steps to prevent runaway loops
MAX_HISTORY_TURNS = 6         # verbatim recent turns fed to the agent

# ── Database-grounding guard ──────────────────────────────────────────────
# Every number / record-id in the answer must be traceable to a tool result (or
# the resolved-context block) THIS turn. Currency-aware: amounts carry their
# currency label so "1000 JPY" never verifies against "$1000". Single-digit
# monetary amounts (e.g. "$1", "€8") are still checked when they carry a
# currency marker; bare single digits (list indices, "3 statuses") are ignored.
_CODE_SPAN_RE = re.compile(r"`[^`]*`|```.*?```|_[^_\n]+_", re.DOTALL)
_ID_RE = re.compile(r"\b[A-Za-z]{2,}-\d[\w.\-]*")
_NUM_RE = re.compile(r"-?\d[\d,]*\.?\d*")
_CUR_RE = re.compile(r"(USD|EUR|JPY|GBP|AED|SAR|\$|€|¥|£)", re.IGNORECASE)


def _amounts_with_currency(text: str) -> set:
    """Set of (rounded_value, currency_key) for every number in text.

    currency_key is the normalized currency token found within 12 chars
    before/after the number, or '' when none is present."""
    out = set()
    if not text:
        return out
    for m in _NUM_RE.finditer(text):
        raw = m.group(0)
        s = raw.replace(",", "")
        if s in (".", "-", ""):
            continue
        try:
            val = round(float(s), 2)
        except ValueError:
            continue
        window = text[max(0, m.start() - 12):m.end() + 12]
        cm = _CUR_RE.search(window)
        cur = cm.group(1).upper() if cm else ""
        # Normalize symbols to codes for comparison.
        cur = {"$": "USD", "€": "EUR", "¥": "JPY", "£": "GBP"}.get(cur, cur)
        out.add((val, cur))
    return out


def _nums(text: str) -> set:
    return {v for v, _ in _amounts_with_currency(text or "")}


def _has_currency_marker(answer: str, start: int, end: int) -> bool:
    window = answer[max(0, start - 12):end + 12]
    return bool(_CUR_RE.search(window))


def _answer_facts(answer: str):
    """Return (data_numbers, record_ids) worth verifying (backward-compatible floats).

    Single-digit numbers are kept ONLY when they carry a currency marker
    (e.g. "$1"); bare digits like "3 statuses" are ignored."""
    stripped = _CODE_SPAN_RE.sub(" ", answer or "")
    ids = {m.upper() for m in _ID_RE.findall(stripped)}
    # Drop record-ids before pulling numbers so 'INV-00002' doesn't yield a bogus 2.
    no_ids = _ID_RE.sub(" ", stripped)
    data_nums = set()
    for m in _NUM_RE.finditer(no_ids):
        raw = m.group(0)
        s = raw.replace(",", "").rstrip(".")   # trailing sentence-period isn't a decimal point
        if not s or s in ("-", "."):
            continue
        has_dec = bool(re.search(r"\.\d", s))
        intpart = s.lstrip("-").split(".")[0]
        if len(intpart) < 2 and not has_dec:
            if not _has_currency_marker(no_ids, m.start(), m.end()):
                continue
        try:
            data_nums.add(round(float(s), 2))
        except ValueError:
            pass
    return data_nums, ids


def _answer_amounts(answer: str) -> set:
    """Currency-qualified amounts in an answer: set of (value, currency)."""
    stripped = _CODE_SPAN_RE.sub(" ", answer or "")
    no_ids = _ID_RE.sub(" ", stripped)
    out = set()
    for m in _NUM_RE.finditer(no_ids):
        raw = m.group(0)
        s = raw.replace(",", "").rstrip(".")
        if not s or s in ("-", "."):
            continue
        has_dec = bool(re.search(r"\.\d", s))
        intpart = s.lstrip("-").split(".")[0]
        if len(intpart) < 2 and not has_dec:
            if not _has_currency_marker(no_ids, m.start(), m.end()):
                continue
        try:
            val = round(float(s), 2)
        except ValueError:
            continue
        window = no_ids[max(0, m.start() - 12):m.end() + 12]
        cm = _CUR_RE.search(window)
        cur = cm.group(1).upper() if cm else ""
        cur = {"$": "USD", "€": "EUR", "¥": "JPY", "£": "GBP"}.get(cur, cur)
        out.add((val, cur))
    return out


def verify_grounding(answer: str, corpus: str):
    """Return the list of numbers/record-ids in `answer` not found in `corpus`
    (the concatenated tool outputs + resolved-context block for this turn).
    Amounts must match BOTH numeric value and currency label."""
    corpus = corpus or ""
    corpus_amounts = _amounts_with_currency(corpus)
    corpus_vals = {v for v, _ in corpus_amounts}
    corpus_low = corpus.lower()
    data_amounts = _answer_amounts(answer)
    _, ids = _answer_facts(answer)
    bad = []
    for val, cur in data_amounts:
        if cur:
            # Currency-qualified amount: require same value WITH same currency nearby.
            if (val, cur) not in corpus_amounts:
                bad.append(_fmt_num(val) + f" ({cur})" if cur else _fmt_num(val))
        else:
            # Bare number: require the value anywhere in the corpus.
            if not any(abs(val - cn) < 0.01 for cn in corpus_vals):
                bad.append(_fmt_num(val))
    for i in ids:
        if i.lower() not in corpus_low:
            bad.append(i)
    return bad


def _fmt_num(n: float) -> str:
    return str(int(n)) if float(n).is_integer() else str(n)


# Cache of compiled agents keyed by (api_key, model_name) so we don't rebuild the
# 20 tools + graph on every request.
_AGENT_CACHE: Dict[tuple, Any] = {}


def _resolve_model_name(provider: str) -> str:
    env_model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")
    if provider and provider.startswith("gemini-"):
        return provider
    return env_model


def _get_compiled_agent(api_key: str, model_name: str):
    """Build (or fetch from cache) the compiled ReAct agent for this key+model.

    The cache key is a SHA-256 hash of the API key so raw secrets are never
    retained as dict keys / in tracebacks."""
    import hashlib
    key_hash = hashlib.sha256((api_key or "").encode("utf-8")).hexdigest()
    cache_key = (key_hash, model_name)
    if cache_key in _AGENT_CACHE:
        return _AGENT_CACHE[cache_key]

    from langchain_google_genai import ChatGoogleGenerativeAI
    from langgraph.prebuilt import create_react_agent
    from agent_tools import build_tools

    llm = ChatGoogleGenerativeAI(model=model_name, temperature=0.1, google_api_key=api_key)
    agent = create_react_agent(llm, build_tools())
    _AGENT_CACHE[cache_key] = agent
    logger.info(f"Compiled ReAct agent (model={model_name}); cached for reuse.")
    return agent
class ChatbotEngine:
    def __init__(self, gemini_api_key: Optional[str] = None):
        self.gemini_api_key = gemini_api_key or os.getenv("GEMINI_API_KEY", "")

    def is_ready(self) -> bool:
        return bool(self.gemini_api_key or os.getenv("GEMINI_API_KEY", ""))

    def get_chat_response(
        self,
        user_query: str,
        chat_history: Optional[List[Dict[str, str]]] = None,
        provider: str = "gemini",
        client: Any = None,
        conversation_id: Optional[str] = None,
        memory: Any = None,
    ) -> str:
        chat_history = chat_history or []

        if not self.is_ready():
            return ("Chatbot is not ready. Please provide a Google Gemini API Key "
                    "in the AI Chatbot Config section of the sidebar.")
        if client is None:
            return ("No Unifier connection established. Please enter your Bearer Token "
                    "and click Test API Connection first, then ask your question again.")

        # Load conversation memory if the caller didn't hand one in.
        from agent_memory import ConversationMemory
        if memory is None:
            memory = ConversationMemory.load(conversation_id)

        try:
            agent = _get_compiled_agent(self.gemini_api_key, _resolve_model_name(provider))
        except Exception as e:
            return f"Failed to initialise LLM/agent: {e}"

        return self._run(agent, user_query, chat_history, client, memory)

    def _run(self, agent: Any, user_query: str, chat_history: List[Dict[str, str]], client: Any, memory: Any) -> str:
        from agent_prompts import build_system_prompt
        from agent_tools import set_request_context, reset_request_context

        system_prompt = build_system_prompt(memory.context_block())

        messages: list = [("system", system_prompt)]
        history = list(chat_history)
        # The frontend appends the current user turn before sending — drop the dupe.
        if history and history[-1].get("role") == "user" and history[-1].get("content") == user_query:
            history = history[:-1]
        for msg in history[-MAX_HISTORY_TURNS:]:
            role = "user" if msg.get("role") == "user" else "assistant"
            content = msg.get("content", "")
            if content:
                messages.append((role, content))
        messages.append(("user", user_query))

        token = set_request_context(client=client, memory=memory)
        try:
            response = agent.invoke({"messages": messages}, config={"recursion_limit": RECURSION_LIMIT})
            result_messages = response.get("messages", [])

            # Persist resolved entities from the tool calls the agent actually made.
            try:
                memory.update_from_tool_calls(result_messages)
                memory.update_history_summary(chat_history, keep_recent=MAX_HISTORY_TURNS)
                memory.save()
            except Exception as mem_err:
                logger.warning(f"Memory update failed: {mem_err}")

            answer, raw_tool_fallback = self._extract_answer(result_messages)

            # If the model returned absolutely nothing but DID run a tool, force a conversational summary
            if not answer and raw_tool_fallback:
                logger.warning("Agent returned empty answer after tool call. Forcing conversational summary.")
                correction = (
                    "You ran a tool but returned no response. "
                    "Please provide a conversational answer to the user based ONLY on the tool results you just received. "
                    "Do NOT dump raw tool output. Follow all formatting and grounding rules."
                )
                retry = list(messages) + result_messages + [("user", correction)]
                response2 = agent.invoke({"messages": retry}, config={"recursion_limit": RECURSION_LIMIT})
                rm2 = response2.get("messages", [])
                answer, _ = self._extract_answer(rm2)
                if not answer:
                    answer = f"I found this information, but encountered an error formatting it:\n\n{raw_tool_fallback}"

            if not answer:
                return "The assistant didn't return a response. Please try rephrasing your question."

            answer = self._enforce_grounding(agent, messages, result_messages, system_prompt, answer)
            return answer
        except Exception as e:
            err = str(e)
            if "429" in err or "RESOURCE_EXHAUSTED" in err:
                return ("⚠️ **Google Gemini Rate Limit Reached (429 Resource Exhausted)**\n\n"
                        "Your Gemini API Key has temporarily exceeded its quota. Please wait a few seconds "
                        "and try again, or check limits at [Google AI Studio](https://aistudio.google.com/).")
            logger.error(f"Agent error: {err}")
            return (f"Agent error: {err}\n\nIf this is an API key error, check your Gemini API key "
                    "in the AI Chatbot Config sidebar.")
        finally:
            reset_request_context(token)

    @staticmethod
    def _tool_corpus(result_messages: list, system_prompt: str) -> str:
        """All grounded text available this turn: tool outputs + the resolved-context
        block in the system prompt (which carries the active project number/name)."""
        parts = [system_prompt or ""]
        for msg in result_messages:
            if type(msg).__name__ == "ToolMessage" and getattr(msg, "content", None):
                parts.append(str(msg.content))
        return "\n".join(parts)

    def _enforce_grounding(self, agent: Any, messages: list, result_messages: list,
                           system_prompt: str, answer: str) -> str:
        """Backstop for the G-rules: if the answer states a number/record-id that isn't
        traceable to this turn's tool outputs, re-ground once; if it still can't be
        verified, flag the specific values rather than letting a fabricated figure stand."""
        try:
            corpus = self._tool_corpus(result_messages, system_prompt)
            bad = verify_grounding(answer, corpus)
            if not bad:
                return answer
            logger.warning(f"Grounding guard: unverifiable values {bad} — re-grounding.")

            correction = (
                "GROUNDING CHECK FAILED. Your previous draft stated these values that are NOT present "
                f"in any tool result this turn: {', '.join(bad)}. Rewrite the answer using ONLY values "
                "returned by the tools. Call a tool to obtain any figure you need; for anything the "
                "database does not provide, say 'That information is not in the database.' Do not compute, "
                "round, or invent numbers."
            )
            retry = list(messages) + result_messages + [("assistant", answer), ("user", correction)]
            response2 = agent.invoke({"messages": retry}, config={"recursion_limit": RECURSION_LIMIT})
            rm2 = response2.get("messages", [])
            answer2, _ = self._extract_answer(rm2)
            corpus2 = corpus + "\n" + self._tool_corpus(rm2, "")
            bad2 = verify_grounding(answer2, corpus2)
            if not bad2:
                return answer2 or answer
            # Still unverifiable → surface honestly instead of asserting a wrong figure.
            logger.warning(f"Grounding guard: still unverifiable after retry: {bad2}")
            caveat = ("\n\n> ⚠️ **Grounding note:** I could not verify these value(s) against the database "
                      f"this turn: {', '.join(bad2)}. Please re-ask or request a data sync so I can confirm them.")
            return (answer2 or answer) + caveat
        except Exception as e:
            logger.warning(f"Grounding guard error (returning original answer): {e}")
            return answer

    @staticmethod
    def _extract_answer(result_messages: list) -> tuple[str, str]:
        """Returns (actual_answer, raw_tool_fallback)."""
        last_msg = result_messages[-1] if result_messages else None
        content = str(last_msg.content) if last_msg is not None and getattr(last_msg, "content", None) else ""
        raw_tool = ""
        if not content:
            # Find the last tool message if any
            for msg in reversed(result_messages):
                if type(msg).__name__ == "ToolMessage" and getattr(msg, "content", None):
                    raw_tool = str(msg.content)
                    break
        return content, raw_tool
