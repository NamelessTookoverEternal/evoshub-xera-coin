"""
Native Python response engine for EVOSGPT.

Scope is deliberately small: greetings, thanks, farewells, verified facts about EVOSGPT / EVOXERA
TECHNOLOGY, basic help, and a few deterministic text/maths tasks. Anything else returns None and the
caller falls back to OpenAI. The engine never invents facts: every factual answer comes from the
verified tables below or from live config passed in (tier names/limits).

Layers (kept separate on purpose):
  normalize()    -> text cleanup
  is_complex()   -> "needs generative intelligence" gate (always wins over classification)
  classify()     -> intent label or None
  respond()      -> builds the reply for an intent
  try_native()   -> the one public entry point
"""
import ast
import operator
import random
import re
from dataclasses import dataclass
from typing import Optional

# ------------------------------------------------------------------ normalisation

_WS = re.compile(r"\s+")
_PUNCT_EDGE = re.compile(r"^[\W_]+|[\W_]+$")


def normalize(text: str) -> str:
    t = (text or "").lower().replace("’", "'")
    t = re.sub(r"[^\w\s'+\-*/().%^]", " ", t)
    return _WS.sub(" ", t).strip()


def _words(text: str) -> list:
    return re.findall(r"[\w']+", (text or "").lower())


# ------------------------------------------------------------------ complexity gate

_COMPLEX_WORDS = {
    "write", "essay", "poem", "story", "script", "article", "blog", "letter", "email", "cv", "resume",
    "code", "program", "function", "debug", "fix", "implement", "build", "create", "generate", "design",
    "explain", "why", "analyse", "analyze", "compare", "summarise", "summarize", "translate", "solve",
    "prove", "derive", "plan", "strategy", "brainstorm", "rewrite", "rephrase", "improve", "review",
    "recommend", "suggest", "advise", "describe", "outline", "draft", "proofread", "edit",
}


def is_complex(message: str) -> bool:
    """True when the message needs real generative work. Checked BEFORE any native classification."""
    words = _words(message)
    if len(words) > 40:
        return True
    if "```" in message or "\n" in message.strip() and len(words) > 25:
        return True
    return any(w in _COMPLEX_WORDS for w in words)


# ------------------------------------------------------------------ verified knowledge

# Every entry here is verifiable from this repository (README / integration docs / TIERS config).
VERIFIED_FACTS = {
    "evosgpt": "EVOSGPT is the AI assistant built by EVOXERA TECHNOLOGY. It runs inside EVOS Hub at /evosgpt, remembers your past conversations, and can also generate images and PDF/Word documents on paid tiers.",
    "evoxera": "EVOXERA TECHNOLOGY is the company behind EVOS Hub and its products: EVOSGPT, EVOS Data, XERA and Website Creation.",
    "evoshub": "EVOS Hub (evoshub.xyz) is the portal that brings the EVOXERA TECHNOLOGY products together in one place.",
    "evosdata": "EVOS Data (evoshub.xyz/evosdata) lets you buy Ghana mobile data bundles instantly.",
    "xera": "XERA is the EVOXERA TECHNOLOGY token. The XERA app in EVOS Hub (/xera) has a wallet, 24-hour mining and reward claiming.",
    "website_creation": "Website Creation (/website-creation) lets you pick a package, submit a request and chat live with an EVOXERA agent.",
}

_ENTITY_PATTERNS = [
    ("evosgpt", re.compile(r"\bevos ?gpt\b")),
    ("evoxera", re.compile(r"\bevoxera( technology)?\b")),
    ("evosdata", re.compile(r"\bevos ?data( services)?\b")),
    ("evoshub", re.compile(r"\bevos ?(business )?hub\b")),
    ("xera", re.compile(r"\bxera( token| coin| app)?\b")),
    ("website_creation", re.compile(r"\bwebsite creation\b")),
]

# ------------------------------------------------------------------ intent patterns (whole-message)

_GREET = r"(?:hi+|hello+|hey+|heya|hiya|yo|howdy|sup|good (?:morning|afternoon|evening|day)|greetings|morning|afternoon|evening|hola|akwaaba|wassup|what's up|whats up)"
_ADDR = r"(?: (?:there|evosgpt|evos|buddy|friend|bro|chief|boss|my guy|everyone|all))*"
_HOW = r"(?:how are you(?: doing)?(?: today| now)?|how're you|how r u|how are u|how do you do|how is it going|how's it going|hows it going|how have you been|you good|u good|are you (?:ok|okay|well|good))"

_RX = {
    "greeting_how": re.compile(rf"^{_GREET}{_ADDR} {_HOW}{_ADDR}$"),
    "greeting": re.compile(rf"^{_GREET}{_ADDR}$"),
    "how_are_you": re.compile(rf"^{_HOW}{_ADDR}$"),
    "farewell": re.compile(r"^(?:bye+|goodbye|good ?bye|see (?:you|ya)(?: later| soon| tomorrow)?|later|good night|goodnight|night|cya|ttyl|talk (?:to you )?later|take care|catch you later)" + _ADDR + r"$"),
    "thanks": re.compile(r"^(?:thanks?|thank you|thx|ty|thanks a lot|thank you so much|many thanks|much appreciated|appreciate it|cheers|medaase)" + _ADDR + r"(?: (?:very much|a lot|so much|a bunch))?$"),
    "ack": re.compile(r"^(?:(?:ok(?:ay)?|k|cool|great|nice|awesome|perfect|got it|i see|alright|sure|fine|noted|understood|sounds good|good|wow|lol|haha+|thanks|thank you)(?: |$)){1,3}" + _ADDR + r"$"),
    "who_are_you": re.compile(r"^(?:who are you|what are you|what is your name|what's your name|whats your name|who is evosgpt|who made you|who built you|who created you|who owns you|who developed you)$"),
    "capabilities": re.compile(r"^(?:what can you do|what do you do|help|help me|what are your features|how can you help(?: me)?|what are you able to do|what can evosgpt do)$"),
    "tiers": re.compile(r"^(?:what are the (?:tiers|plans)|what tiers (?:are there|do you have)|(?:tiers|plans|pricing|prices)|how much (?:is|does) (?:pro|core|founder|basic)(?: cost)?|how much (?:is|are) (?:the )?(?:tiers|plans|pricing)|what is the difference between (?:basic|pro|core)(?: and (?:pro|core|founder))*)$"),
    "how_image": re.compile(r"^(?:how (?:do i|can i|to) (?:generate|create|make|edit) (?:an )?(?:image|picture|photo)s?|how does image generation work|can you (?:generate|make|edit) images)$"),
    "how_document": re.compile(r"^(?:how (?:do i|can i|to) (?:generate|create|make|export|download) (?:a )?(?:pdf|word|document|docx)s?|how does document generation work|can you (?:generate|make) (?:pdf|word|documents?))$"),
    "how_upgrade": re.compile(r"^(?:how (?:do i|can i|to) upgrade|how do i get pro|how do i upgrade to (?:pro|core)|upgrade)$"),
    "how_clear_memory": re.compile(r"^(?:how (?:do i|can i|to) (?:clear|delete|reset|erase) (?:my )?(?:memory|history|chats?|conversations?)|clear my memory|delete my (?:memory|history))$"),
    "about_time": re.compile(r"^(?:what(?:'s| is) the time(?: now)?|what time is it(?: now)?|time|current time|what(?:'s| is) the time (?:right )?now)$"),
    "about_date": re.compile(r"^(?:what(?:'s| is) (?:the )?(?:date|day)(?: today)?|what day is (?:it|today)|today's date|date today)$"),
    "about_entity": re.compile(r"^(?:what is|what's|whats|who is|tell me about|what are) (?:the )?(?P<ent>[\w ]{3,40})$"),
    "evosdata_buy": re.compile(r"^(?:where (?:can|do) i (?:buy|get) (?:data|data bundles?|internet)|how (?:do i|can i) buy (?:data|data bundles?))$"),
}

# ------------------------------------------------------------------ safe arithmetic

_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos, ast.Mod: operator.mod}
_MATH_RX = re.compile(r"^(?:what(?:'s| is)|whats|calculate|compute|solve)?\s*([\d\s+\-*/().%^x×÷]+?)\s*(?:=|\?)?$")


def _eval(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        l, r = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and (abs(r) > 12 or abs(l) > 1e6):
            raise ValueError("too large")
        return _OPS[type(node.op)](l, r)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.operand))
    raise ValueError("unsupported")


def _try_math(message: str) -> Optional[str]:
    m = _MATH_RX.match(message.strip().lower().replace("’", "'"))
    if not m:
        return None
    expr = m.group(1).strip()
    if not re.search(r"\d\s*[+\-*/%^x×÷]\s*[\d(]", expr):     # needs a real operator between numbers
        return None
    expr = expr.replace("×", "*").replace("÷", "/").replace("^", "**")
    expr = re.sub(r"(?<=\d)\s*x\s*(?=[\d(])", "*", expr)
    try:
        val = _eval(ast.parse(expr, mode="eval").body)
    except Exception:
        return None
    if isinstance(val, float):
        if val != val or val in (float("inf"), float("-inf")):
            return None
        val = round(val, 10)
        if val == int(val) and abs(val) < 1e15:
            val = int(val)
    return f"{expr.replace('**', '^')} = {val}"


# ------------------------------------------------------------------ deterministic text tasks

_TEXT_TASKS = [
    (re.compile(r"^(?:(?:count|how many) (?:the )?words(?: in| are in)?|word count(?: of| for)?)\s*[:\-]?\s*(?P<t>.+)$", re.I | re.S), "words"),
    (re.compile(r"^(?:(?:count|how many) (?:the )?(?:characters|letters|chars)(?: in| are in)?|(?:character|char|letter) count(?: of| for)?)\s*[:\-]?\s*(?P<t>.+)$", re.I | re.S), "chars"),
    (re.compile(r"^(?:make|convert|change|turn)\s+(?:this\s+|the following\s+)?(?:text\s+)?(?:to|into)\s+(?P<k>uppercase|lowercase|upper case|lower case|title case)\s*[:\-]\s*(?P<t>.+)$", re.I | re.S), "case"),
    (re.compile(r"^(?P<k>uppercase|lowercase|upper case|lower case|title case)\s*[:\-]\s*(?P<t>.+)$", re.I | re.S), "case"),
    (re.compile(r"^reverse(?: this| the text| the following)?\s*[:\-]\s*(?P<t>.+)$", re.I | re.S), "reverse"),
]


def _try_text_task(message: str) -> Optional[str]:
    raw = message.strip()
    for rx, kind in _TEXT_TASKS:
        m = rx.match(raw)
        if not m:
            continue
        t = m.group("t").strip().strip("\"'")
        if not t:
            return None
        if kind == "words":
            return f"That text has {len(t.split())} word{'s' if len(t.split()) != 1 else ''}."
        if kind == "chars":
            return f"That text has {len(t)} characters ({len(t.replace(' ', ''))} without spaces)."
        if kind == "reverse":
            return t[::-1]
        k = m.group("k").lower().replace(" ", "")
        return t.upper() if k == "uppercase" else t.lower() if k == "lowercase" else t.title()
    return None


# ------------------------------------------------------------------ response building

@dataclass
class NativeResult:
    reply: str
    intent: str
    confidence: float = 1.0


def classify(message: str) -> Optional[str]:
    """Intent label, or None. Only whole-message matches count, so 'hi, write me an essay' is NOT a greeting."""
    n = normalize(message)
    if not n or len(n.split()) > 14:
        return None
    for intent in ("greeting_how", "greeting", "how_are_you", "farewell", "thanks", "who_are_you", "capabilities",
                   "tiers", "how_image", "how_document", "how_upgrade", "how_clear_memory", "evosdata_buy",
                   "about_time", "about_date", "ack"):
        if _RX[intent].match(n):
            return intent
    m = _RX["about_entity"].match(n)
    if m and _entity(m.group("ent")):
        return "about_entity"
    return None


def _entity(text: str) -> Optional[str]:
    for key, rx in _ENTITY_PATTERNS:
        if rx.search(text):
            return key
    return None


def _tod(geo: Optional[dict]) -> Optional[str]:
    """Part of day from the user's local time string ('Saturday, 17 October 2026, 01:03 PM')."""
    lt = (geo or {}).get("local_time") or ""
    m = re.search(r"(\d{1,2}):\d{2}\s*(AM|PM)", lt, re.I)
    if not m:
        return None
    h = int(m.group(1)) % 12 + (12 if m.group(2).upper() == "PM" else 0)
    return "morning" if h < 12 else "afternoon" if h < 17 else "evening"


def _tier_summary(tiers: dict) -> str:
    parts = []
    for name, cfg in tiers.items():
        if name == "Founder":
            continue
        limit = cfg.get("day_limit")
        price = cfg.get("price_ghs")
        parts.append(f"{name}: {'free' if not price else f'GHS {price}'}, "
                     f"{'%d chats/day' % limit if limit else 'unlimited chats'}, "
                     f"remembers the last {cfg.get('memory_limit')} messages")
    return "; ".join(parts)


def respond(intent: str, message: str, *, username: str = "", geo: Optional[dict] = None,
            tiers: Optional[dict] = None, rng: Optional[random.Random] = None) -> Optional[str]:
    rng = rng or random.Random()
    name = (username or "").strip()
    pick = lambda opts: rng.choice(opts)
    tod = _tod(geo)

    if intent in ("greeting", "greeting_how"):
        opener = pick([f"Hi{', ' + name if name else ''}!", f"Hello{' ' + name if name else ''}!", f"Hey{' ' + name if name else ''}!"])
        if tod and re.search(r"good (morning|afternoon|evening)", normalize(message)):
            opener = f"Good {tod}{', ' + name if name else ''}!"
        tail = pick(["What can I help you with today?", "What are we working on?", "How can I help?"])
        if intent == "greeting_how":
            return f"{opener} I'm doing well, thanks for asking. {tail}"
        return f"{opener} {tail}"
    if intent == "how_are_you":
        return pick(["I'm doing well, thanks for asking! How about you?", "All good on my side. How are you doing?", "Doing great. What can I help with?"])
    if intent == "farewell":
        return pick(["Goodbye! Come back any time.", "See you later! Take care.", "Take care! I'll be here when you need me."])
    if intent == "thanks":
        return pick(["You're welcome!", "Happy to help!", "Anytime. Let me know if there's anything else."])
    if intent == "ack":
        return pick(["Great. Let me know what's next.", "Okay! Anything else I can help with?", "Got it. I'm here if you need anything."])
    if intent == "who_are_you":
        return VERIFIED_FACTS["evosgpt"]
    if intent == "capabilities":
        return ("I can chat and answer questions, help with writing and code, read images you upload, remember your past conversations, "
                "and on Pro and above generate images (🎨 button) and PDF/Word documents (📄 button).")
    if intent == "tiers":
        return ("EVOSGPT tiers: " + _tier_summary(tiers or {}) + ". Founder is by invitation. Prices are billed in GHS."
                if tiers else None)
    if intent == "how_image":
        return "Use the 🎨 button to generate an image, or attach an image and choose Edit. Image generation and editing are available on Pro tier and above."
    if intent == "how_document":
        return "Use the 📄 button next to the message box to generate a PDF or Word (.docx) file. It's available on Pro tier and above."
    if intent == "how_upgrade":
        return "Open the upgrade option in EVOSGPT and pick Pro or Core. Payment is handled securely by Paystack, and your tier updates once it's confirmed. If you have a coupon code, you can redeem it in the same place."
    if intent == "how_clear_memory":
        return "You can clear your EVOSGPT memory from the memory/settings option in the app. That deletes your saved conversation history and your long-term summary, and EVOSGPT starts fresh."
    if intent == "evosdata_buy":
        return VERIFIED_FACTS["evosdata"] + " You can start at https://evoshub.xyz/evosdata."
    if intent == "about_time":
        lt = (geo or {}).get("local_time")
        return f"It's {lt} where you are (based on your approximate location)." if lt else None
    if intent == "about_date":
        lt = (geo or {}).get("local_time")
        parts = [p.strip() for p in (lt or "").split(",")]
        return f"Today is {parts[0]}, {parts[1]}." if len(parts) >= 2 and parts[1] else None
    if intent == "about_entity":
        m = _RX["about_entity"].match(normalize(message))
        key = _entity(m.group("ent")) if m else None
        return VERIFIED_FACTS.get(key) if key else None
    return None


def try_native(message: str, *, username: str = "", geo: Optional[dict] = None, tiers: Optional[dict] = None,
               rng: Optional[random.Random] = None) -> Optional[NativeResult]:
    """Return a NativeResult only when the message is simple AND answerable reliably. Otherwise None."""
    # Deterministic tasks carry their own payload text, so they run before the complexity-word gate
    # (e.g. "uppercase: write a poem" is still just a case conversion).
    task = _try_text_task(message)
    if task:
        return NativeResult(task, "text_task")
    if is_complex(message):
        return None
    math = _try_math(message)
    if math:
        return NativeResult(math, "math")
    intent = classify(message)
    if not intent:
        return None
    reply = respond(intent, message, username=username, geo=geo, tiers=tiers, rng=rng)
    return NativeResult(reply, intent) if reply else None
