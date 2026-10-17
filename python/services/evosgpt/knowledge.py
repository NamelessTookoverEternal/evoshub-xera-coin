"""
EVOSGPT storage-side helpers: reusable knowledge, history recall, personal memory, usage metrics, retention.

Every function takes the Supabase client as `db` (core.py passes the Hub's shared client; no second
client is ever created here) and is written so a database failure degrades to "no result" rather than
breaking /chat. Three kinds of data are kept strictly apart:

  A. conversation history   evosgpt_memory       private, per user (and optional conversation_id)
  B. personal memory        evosgpt_long_memory  private, per user, sanitised deterministic facts
  C. shared knowledge       evosgpt_knowledge    NO user_id column, sanitised, only status='approved'
                                                 rows are ever served; AI-generated rows start 'pending'
"""
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from services.evosgpt import privacy

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------- tunables (env-overridable)
def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default

def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default

KNOWLEDGE_MIN_SIMILARITY = _env_float("EVOSGPT_KNOWLEDGE_MIN_SIMILARITY", 0.85)
KNOWLEDGE_MIN_CONFIDENCE = _env_float("EVOSGPT_KNOWLEDGE_MIN_CONFIDENCE", 0.7)
KNOWLEDGE_MAX_AGE_DAYS = _env_int("EVOSGPT_KNOWLEDGE_MAX_AGE_DAYS", 180)   # AI-generated entries go stale
KNOWLEDGE_SCAN_LIMIT = 300
RETENTION_DAYS = _env_int("EVOSGPT_RETENTION_DAYS", 365)                    # DB retention; 0 = keep forever
RETENTION_MAX_ROWS = _env_int("EVOSGPT_RETENTION_MAX_ROWS", 5000)           # per user
HISTORY_SCAN_LIMIT = 300
LONG_MEMORY_MAX_CHARS = 1200

def _now() -> datetime:
    return datetime.now(timezone.utc)

def _parse_ts(v) -> Optional[datetime]:
    if not v:
        return None
    try:
        s = str(v).replace("Z", "+00:00")
        d = datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None

# ---------------------------------------------------------------- text similarity

_STOP = set("""a an the is are was were be been am do does did of to in on at for with by from as and or but if then so
that this these those it its i me my mine you your we our us they them their he she him her what whats what's which who
whom how why when where can could would should will shall may might please tell about give show let lets just really
very some any more most much many""".split())

_NEG = {"not", "no", "never", "without", "dont", "don't", "cannot", "cant", "can't"}

def content_tokens(text: str) -> List[str]:
    toks = re.findall(r"[a-z0-9']+", (text or "").lower().replace("’", "'"))
    return [t for t in toks if t not in _STOP or t in _NEG]

def question_key(text: str) -> str:
    return " ".join(sorted(set(content_tokens(text))))

def similarity(a: str, b: str) -> float:
    A, B = set(content_tokens(a)), set(content_tokens(b))
    if not A or not B:
        return 0.0
    if {t for t in A if t.isdigit()} != {t for t in B if t.isdigit()}:    # "2 apples" != "3 apples"
        return 0.0
    if (A & _NEG) != (B & _NEG):                                           # "is X safe" != "is X not safe"
        return 0.0
    return len(A & B) / len(A | B)

# ---------------------------------------------------------------- what may be learned / reused

_PERSONAL_RX = re.compile(r"\b(i|i'm|im|i've|ive|i'll|my|mine|me|we|our|ours|us|myself)\b", re.I)
_VOLATILE_RX = re.compile(
    r"\b(today|tonight|tomorrow|yesterday|now|current(ly)?|latest|recent(ly)?|newest|price|prices|cost|rate|rates|"
    r"news|weather|score|scores|live|this (week|month|year)|right now|stock|exchange|who is the (president|ceo|prime)|"
    r"202\d|break(ing)?)\b", re.I)
_GENERATIVE_RX = re.compile(
    r"\b(write|essay|poem|story|song|script|letter|email|cv|resume|cover letter|code|program|debug|fix|build|create|generate|"
    r"design|draft|rewrite|rephrase|translate|brainstorm|roleplay|pretend|imagine|summari[sz]e|proofread|edit|improve|plan)\b", re.I)

def is_shareable_question(question: str) -> bool:
    """Only impersonal, timeless, factual-style questions can ever be reused across users."""
    q = (question or "").strip()
    n = len(content_tokens(q))
    if n < 1 or len(q.split()) < 3 or len(q.split()) > 40:
        return False
    if _PERSONAL_RX.search(q) or _VOLATILE_RX.search(q) or _GENERATIVE_RX.search(q):
        return False
    return True

# ---------------------------------------------------------------- C. shared knowledge

def _guard(fn, default=None):
    try:
        return fn()
    except Exception as e:                      # Supabase down / table missing => behave as "unknown"
        logger.warning("EVOSGPT knowledge store error: %s", e)
        return default

def find_knowledge(db, question: str) -> Optional[dict]:
    """Best APPROVED, fresh, confident match for the question, or None. A hit is not trusted blindly:
    similarity, confidence, freshness and shareability are all checked."""
    if not is_shareable_question(question):
        return None

    def _go():
        qkey = question_key(question)
        rows = (db.table("evosgpt_knowledge").select("*").eq("status", "approved")
                  .order("seen_count", desc=True).limit(KNOWLEDGE_SCAN_LIMIT).execute().data or [])
        best, best_score = None, 0.0
        for r in rows:
            if not _fresh(r):
                continue
            if float(r.get("confidence") or 0) < KNOWLEDGE_MIN_CONFIDENCE:
                continue
            score = 1.0 if r.get("question_key") == qkey else similarity(question, r.get("question", ""))
            if score > best_score:
                best, best_score = r, score
        if best and best_score >= KNOWLEDGE_MIN_SIMILARITY:
            return dict(best, match_score=round(best_score, 3))
        return None
    return _guard(_go)

def _fresh(row: dict) -> bool:
    exp = _parse_ts(row.get("expires_at"))
    if exp and exp < _now():
        return False
    if row.get("source") == "ai_generated":
        ref = _parse_ts(row.get("updated_at")) or _parse_ts(row.get("created_at"))
        if ref and KNOWLEDGE_MAX_AGE_DAYS and (_now() - ref) > timedelta(days=KNOWLEDGE_MAX_AGE_DAYS):
            return False
    return True

def bump_knowledge_use(db, row: dict) -> None:
    _guard(lambda: db.table("evosgpt_knowledge").update({"use_count": int(row.get("use_count") or 0) + 1})
           .eq("id", row["id"]).execute())

def learn_candidate(db, question: str, answer: str, *, confidence: float = 0.5) -> str:
    """Offer an OpenAI answer as a *pending* knowledge candidate. Returns a short outcome label.

    Nothing learned here is served until a human sets status='approved'. We refuse outright (store
    nothing) if either text contains anything the privacy filter would have redacted, so private
    message content can never reach the shared table, even redacted.
    """
    if not is_shareable_question(question):
        return "skipped_not_shareable"
    q = privacy.sanitize_for_shared(question, 400)
    a = privacy.sanitize_for_shared(answer, 2000)
    if not q or not a:
        return "skipped_private"
    if len(a) < 40 or "![" in a or "```" in a:
        return "skipped_unsuitable"

    def _go():
        qkey = question_key(q)
        existing = (db.table("evosgpt_knowledge").select("*").eq("question_key", qkey).limit(1).execute().data or [])
        now = _now().isoformat()
        if not existing:
            db.table("evosgpt_knowledge").insert({
                "question_key": qkey, "question": q, "answer": a, "source": "ai_generated", "status": "pending",
                "confidence": confidence, "seen_count": 1, "use_count": 0, "conflict_count": 0,
                "created_at": now, "updated_at": now,
            }).execute()
            return "created_pending"
        row = existing[0]
        patch = {"seen_count": int(row.get("seen_count") or 1) + 1}
        if row.get("status") == "approved":
            # Never overwrite reviewed content. A materially different new answer is a conflict signal;
            # enough conflicts on an AI-generated entry send it back to review.
            if similarity(a, row.get("answer", "")) < 0.3:
                patch["conflict_count"] = int(row.get("conflict_count") or 0) + 1
                if row.get("source") == "ai_generated" and patch["conflict_count"] >= 3:
                    patch["status"] = "pending"
            db.table("evosgpt_knowledge").update(patch).eq("id", row["id"]).execute()
            return "seen_approved"
        if row.get("status") == "pending":
            patch.update({"answer": a, "updated_at": now})
        db.table("evosgpt_knowledge").update(patch).eq("id", row["id"]).execute()
        return "seen_" + str(row.get("status"))
    return _guard(_go, "error")

# ---------------------------------------------------------------- A. conversation history recall

_RECALL_RX = re.compile(
    r"\b(what did we (?:discuss|talk about|say|decide|cover|do)|what were we (?:discussing|talking about|working on)|"
    r"remind me (?:what|about|of)|(?:what|which) (?:did|have) (?:i|we) (?:tell|told|say|said|ask|asked)|"
    r"(?:we|i) (?:discussed|talked about|spoke about|mentioned|chatted about)|"
    r"(?:last|previous|earlier) (?:time|chat|conversation|session)|our (?:last|previous|earlier) (?:chat|conversation))\b", re.I)
_CONTINUE_RX = re.compile(r"\b(continue|resume|carry on|pick up|go on with|keep working on)\b.*\b(we|our|that|the|my|earlier|before|last)\b", re.I)
_RECALL_VOCAB = set("""what did we discuss discussed talk talked about say said decide decided cover covered do remind me of
which have i tell told ask asked mentioned spoke chat chatted last previous earlier time conversation session our
yesterday today week month ago before were working on project continue resume carry pick up go keep""".split())

def history_intent(message: str) -> Optional[str]:
    """'recall' (answer from history), 'continue' (needs OpenAI WITH retrieved context) or None."""
    if _CONTINUE_RX.search(message or ""):
        return "continue"
    if _RECALL_RX.search(message or ""):
        return "recall"
    return None

def _time_window(message: str) -> Optional[Tuple[datetime, datetime]]:
    m = (message or "").lower()
    today = _now().replace(hour=0, minute=0, second=0, microsecond=0)
    if "yesterday" in m:
        return today - timedelta(days=1), today
    if "today" in m or "earlier today" in m:
        return today, today + timedelta(days=1)
    if "last week" in m or "this week" in m:
        return today - timedelta(days=7), today + timedelta(days=1)
    if "last month" in m:
        return today - timedelta(days=31), today + timedelta(days=1)
    return None

def search_history(db, user_id: int, message: str, *, max_hits: int = 3) -> List[dict]:
    """Relevant earlier USER messages for this user only (the query is always scoped by user_id)."""
    def _go():
        rows = (db.table("evosgpt_memory").select("role,content,created_at").eq("user_id", user_id)
                  .order("created_at", desc=True).limit(HISTORY_SCAN_LIMIT).execute().data or [])
        window = _time_window(message)
        topic = {t for t in content_tokens(message) if t not in _RECALL_VOCAB and len(t) > 2}
        hits = []
        for r in rows:
            if r.get("role") != "user":
                continue
            ts = _parse_ts(r.get("created_at"))
            if window and ts and not (window[0] <= ts < window[1]):
                continue
            toks = set(content_tokens(r.get("content", "")))
            if topic:
                overlap = len(topic & toks)
                if overlap == 0 or overlap / len(topic) < 0.5:
                    continue
                score = overlap / len(topic)
            else:
                score = 0.5          # no topic given: window/recency only
            hits.append({"content": r.get("content", ""), "created_at": r.get("created_at"), "score": score})
        hits.sort(key=lambda h: (h["score"], h["created_at"] or ""), reverse=True)
        return hits[:max_hits]
    return _guard(_go, [])

def format_recall_reply(hits: List[dict]) -> str:
    lines = []
    for h in hits:
        ts = _parse_ts(h.get("created_at"))
        when = ts.strftime("%d %b %Y") if ts else "earlier"
        snippet = re.sub(r"\s+", " ", h["content"]).strip()
        lines.append(f"- {when}: you said \"{snippet[:220]}{'…' if len(snippet) > 220 else ''}\"")
    return "Here's what I found in your earlier chats:\n" + "\n".join(lines) + "\n\nWant me to pick any of these up again?"

def format_history_context(hits: List[dict]) -> str:
    return "\n".join(f"- ({(h.get('created_at') or '')[:10]}) {re.sub(chr(10), ' ', h['content'])[:300]}" for h in hits)

# ---------------------------------------------------------------- B. personal memory (deterministic, no LLM)

_FACT_PATTERNS = [
    re.compile(r"\b(?:i am|i'm|im) (?:currently |now )?(?:working on|building|developing|making|creating|learning|studying|starting|running)\s+(?P<f>[^.!?\n]{4,120})", re.I),
    re.compile(r"\bmy (?:goal|plan|aim|dream|project|business|startup|company|app|website|brand) (?:is|are)\s+(?P<f>[^.!?\n]{4,120})", re.I),
    re.compile(r"\bi (?:want|need|plan|hope|intend) to\s+(?P<f>[^.!?\n]{4,120})", re.I),
    re.compile(r"\bi (?:work|worked) (?:as|in|at|with)\s+(?P<f>[^.!?\n]{3,100})", re.I),
    re.compile(r"\bi (?:prefer|like|love|enjoy|use)\s+(?P<f>[^.!?\n]{3,100})", re.I),
]
_FACT_LABEL = ["Working on/learning: ", "Goal/project: ", "Wants to: ", "Work: ", "Preference: "]

def extract_personal_facts(message: str) -> List[str]:
    out = []
    if not message or privacy.contains_secret(message):
        return out
    for rx, label in zip(_FACT_PATTERNS, _FACT_LABEL):
        for m in rx.finditer(message):
            clean = privacy.sanitize_for_memory(m.group("f"), 140)
            if clean and "[" not in clean:      # skip facts that needed redaction (they identified someone)
                out.append(label + clean.rstrip(" ,;"))
    return out[:3]

def merge_long_memory(existing: Optional[str], facts: List[str], max_chars: int = LONG_MEMORY_MAX_CHARS) -> Optional[str]:
    """Deterministic merge: dedupe (case-insensitive), newest last, oldest dropped past the cap."""
    if not facts:
        return None
    lines = [l.strip() for l in (existing or "").splitlines() if l.strip()]
    seen = {re.sub(r"\W+", "", l.lower()) for l in lines}
    for f in facts:
        k = re.sub(r"\W+", "", f.lower())
        if k not in seen:
            lines.append("- " + f if not f.startswith("- ") else f)
            seen.add(k)
    if len(lines) == len((existing or "").splitlines()) and existing:
        return None                                   # nothing new
    while len("\n".join(lines)) > max_chars and len(lines) > 1:
        lines.pop(0)
    return "\n".join(lines)

# ---------------------------------------------------------------- usage metrics

# USD per 1M tokens (input, output). ESTIMATES for reporting only; keep in sync with OpenAI pricing.
MODEL_PRICES = {"gpt-4o-mini": (0.15, 0.60), "gpt-4o": (2.50, 10.00)}

def estimate_cost(model: Optional[str], usage: Optional[dict]) -> Optional[float]:
    if not usage or model not in MODEL_PRICES:
        return None
    p_in, p_out = MODEL_PRICES[model]
    return round((usage.get("prompt_tokens", 0) * p_in + usage.get("completion_tokens", 0) * p_out) / 1_000_000, 6)

def record_usage(db, user_id: Optional[int], route: str, *, model: Optional[str] = None,
                 usage: Optional[dict] = None, purpose: str = "chat") -> None:
    """route: native | knowledge | history | openai.  purpose: chat | memory_maintenance."""
    def _go():
        db.table("evosgpt_usage_events").insert({
            "user_id": user_id, "route": route, "purpose": purpose, "model": model,
            "prompt_tokens": (usage or {}).get("prompt_tokens"),
            "completion_tokens": (usage or {}).get("completion_tokens"),
            "est_cost_usd": estimate_cost(model, usage),
            "created_at": _now().isoformat(),
        }).execute()
    _guard(_go)

def usage_summary(db, user_id: Optional[int] = None, limit: int = 5000) -> dict:
    def _go():
        q = db.table("evosgpt_usage_events").select("*")
        if user_id is not None:
            q = q.eq("user_id", user_id)
        rows = q.order("created_at", desc=True).limit(limit).execute().data or []
        s = {"total_requests": 0, "native": 0, "knowledge": 0, "history": 0, "openai_text": 0,
             "memory_maintenance_calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "est_cost_usd": 0.0,
             "tokens_known": 0, "tokens_unknown": 0}
        for r in rows:
            if r.get("purpose") == "memory_maintenance":
                s["memory_maintenance_calls"] += 1
            else:
                s["total_requests"] += 1
                if r.get("route") == "openai":
                    s["openai_text"] += 1
                elif r.get("route") in ("native", "knowledge", "history"):
                    s[r["route"]] += 1
            if r.get("route") == "openai" or r.get("purpose") == "memory_maintenance":
                if r.get("prompt_tokens") is None:
                    s["tokens_unknown"] += 1
                else:
                    s["tokens_known"] += 1
            s["prompt_tokens"] += int(r.get("prompt_tokens") or 0)
            s["completion_tokens"] += int(r.get("completion_tokens") or 0)
            s["est_cost_usd"] += float(r.get("est_cost_usd") or 0)
        s["est_cost_usd"] = round(s["est_cost_usd"], 6)
        answered_without_openai = s["native"] + s["knowledge"] + s["history"]
        s["answered_without_openai_pct"] = round(100 * answered_without_openai / s["total_requests"], 1) if s["total_requests"] else 0.0
        s["note"] = "Cost is an estimate from token counts; database and hosting costs are not included."
        return s
    return _guard(_go, {})

# ---------------------------------------------------------------- retention (separate from model context)

def apply_retention(db, user_id: int, retention_days: int = RETENTION_DAYS, max_rows: int = RETENTION_MAX_ROWS) -> int:
    """Delete only rows past the retention policy. The number of messages sent to the model is a separate,
    smaller window (get_short_memory(limit)); old rows are NOT deleted just to shrink that window."""
    deleted = 0
    def _go():
        nonlocal deleted
        if retention_days and retention_days > 0:
            cutoff = (_now() - timedelta(days=retention_days)).isoformat()
            res = db.table("evosgpt_memory").delete().eq("user_id", user_id).lt("created_at", cutoff).execute()
            deleted += len(res.data or [])
        if max_rows and max_rows > 0:
            rows = (db.table("evosgpt_memory").select("id").eq("user_id", user_id)
                      .order("created_at", desc=False).execute().data or [])
            excess = len(rows) - max_rows
            if excess > 0:
                ids = [r["id"] for r in rows[:excess]]
                db.table("evosgpt_memory").delete().eq("user_id", user_id).in_("id", ids).execute()
                deleted += len(ids)
    _guard(_go)
    return deleted
