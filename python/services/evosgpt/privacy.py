"""
Deterministic privacy filter for EVOSGPT memory and shared knowledge.

Local regex/heuristic redaction only. Nothing here calls a network service, so a sensitive
message is never sent anywhere just to be filtered.

IMPORTANT: this is best-effort. It catches common, well-formed identifiers. It does NOT
guarantee anonymity (free-text names, unusual address formats and indirect identifiers can
slip through). That is why shared knowledge additionally refuses to learn from any message
the filter changed (see `is_clean`) and why AI-generated entries need human review.

The authenticated user's `user_id` remains a foreign key on private rows. This module only
cleans *text content*.
"""
import re
from typing import List, Optional, Tuple

# (label, compiled regex, replacement). Order matters: secrets first, then structured IDs.
_PATTERNS: List[Tuple[str, "re.Pattern", str]] = [
    # --- credentials / secrets ---
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)", re.S), "[REDACTED_KEY]"),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}\b"), "[REDACTED_KEY]"),
    ("api_key_prefixed", re.compile(r"\b(?:pk|rk|sk|ghp|gho|ghs|xox[abprs]|AKIA|AIza|eyJ)[A-Za-z0-9_\-\.]{16,}\b"), "[REDACTED_KEY]"),
    ("bearer", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9_\-\.=]{12,}"), "Bearer [REDACTED_TOKEN]"),
    ("secret_assignment", re.compile(
        r"(?i)\b(pass(?:word|wd|code)?|pwd|secret|token|api[_\- ]?key|access[_\- ]?key|private[_\- ]?key|pin|otp|cvv|cvc)\b"
        r"(\s*(?:is|=|:)\s*)(\S+)"), r"\1\2[REDACTED]"),
    ("seed_phrase", re.compile(r"(?i)\b(?:seed|recovery|mnemonic)\s+(?:phrase|words?)\b[^\n]{0,200}"), "[REDACTED_SEED]"),
    ("eth_private_key", re.compile(r"\b0x[a-fA-F0-9]{64}\b"), "[REDACTED_KEY]"),
    # --- financial ---
    ("card", re.compile(r"\b(?:\d[ \-]?){13,19}\b"), "[REDACTED_NUMBER]"),
    ("iban", re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"), "[REDACTED_ACCOUNT]"),
    ("momo_or_account", re.compile(r"(?i)\b(account|acct|a/c|momo|mobile money)\s*(?:number|no\.?|#)?\s*(?:is|:|=)?\s*\d[\d \-]{7,}\d"), r"\1 [REDACTED_ACCOUNT]"),
    # --- contact ---
    ("email", re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"), "[EMAIL]"),
    ("url_with_creds", re.compile(r"\bhttps?://[^\s/@:]+:[^\s/@]+@\S+"), "[REDACTED_URL]"),
    ("phone", re.compile(r"(?<![\w.])(?:\+|00)?\d{1,3}[\s\-.]?\(?\d{2,4}\)?[\s\-.]?\d{3}[\s\-.]?\d{3,4}(?![\w.])"), "[PHONE]"),
    ("ip", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "[IP]"),
    ("ghana_post", re.compile(r"\b[A-Z]{2}-\d{3}-\d{4}\b"), "[ADDRESS]"),   # Ghana Post digital address
    ("street_address", re.compile(
        r"(?i)\b\d{1,5}\s+[A-Za-z0-9.\- ]{2,40}\s(?:street|st|road|rd|avenue|ave|lane|ln|drive|dr|close|crescent|boulevard|blvd)\b\.?"), "[ADDRESS]"),
    ("uuid", re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"), "[ID]"),
    ("handle", re.compile(r"(?<![\w@])@[A-Za-z0-9_]{3,32}\b"), "[HANDLE]"),
]

# Self-identification: "my name is Ama Mensah", "I'm Kofi", "call me Yaw", "user id 42", "username: ama".
_NAME_PATTERNS: List[Tuple[str, "re.Pattern", str]] = [
    ("self_name", re.compile(r"(?i)\b(my (?:full |first |last )?name is|i am called|call me|this is)\s+([A-Z][\w'\-]+(?:\s+[A-Z][\w'\-]+){0,2})"), r"\1 [NAME]"),
    ("self_im", re.compile(r"\b(I'm|I am)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)(?=[\s,.!?]|$)"), r"\1 [NAME]"),
    ("username_field", re.compile(r"(?i)\b(user ?name|user ?id|my id)\b(\s*(?:is|=|:)?\s*)([\w.\-@]{2,})"), r"\1\2[ID]"),
]

# Words that follow "I'm"/"I am" and are NOT names (so "I'm Tired" style false positives are rarer).
_NOT_NAMES = {
    "Happy", "Sad", "Tired", "Fine", "Good", "Great", "Okay", "Sorry", "Sure", "Ready", "Here", "Back",
    "Trying", "Looking", "Working", "Building", "Learning", "Writing", "Making", "Doing", "Going", "Not",
    "Just", "Also", "Still", "Very", "Really", "Currently", "Planning", "Thinking", "Wondering", "Having",
}


def redact(text: Optional[str]) -> Tuple[str, List[str]]:
    """Returns (redacted_text, [labels of what was found]). Never raises."""
    if not text:
        return "", []
    out = text
    found: List[str] = []
    for label, rx, repl in _PATTERNS:
        if label == "card":
            def _card(m, _l=label):
                digits = re.sub(r"\D", "", m.group(0))
                if 13 <= len(digits) <= 19 and _luhn(digits):
                    found.append(_l)
                    return "[REDACTED_NUMBER]"
                return m.group(0)
            out = rx.sub(_card, out)
            continue
        new, n = rx.subn(repl, out)
        if n:
            found.append(label)
            out = new
    for label, rx, repl in _NAME_PATTERNS:
        if label == "self_im":
            def _im(m, _l=label):
                if m.group(2).split()[0] in _NOT_NAMES:
                    return m.group(0)
                found.append(_l)
                return f"{m.group(1)} [NAME]"
            out = rx.sub(_im, out)
            continue
        new, n = rx.subn(repl, out)
        if n:
            found.append(label)
            out = new
    return out, found


def _luhn(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def is_clean(text: Optional[str]) -> bool:
    """True when the filter found nothing to redact (used as a hard gate for shared knowledge)."""
    return not redact(text)[1]


_SECRET_LABELS = {
    "private_key", "openai_key", "api_key_prefixed", "bearer", "secret_assignment", "seed_phrase",
    "eth_private_key", "card", "iban", "momo_or_account", "url_with_creds",
}


def contains_secret(text: Optional[str]) -> bool:
    """Credentials / financial identifiers. Messages with these are never learned from at all."""
    return any(l in _SECRET_LABELS for l in redact(text)[1])


def sanitize_for_memory(text: Optional[str], max_len: int = 400) -> Optional[str]:
    """Redacted, length-capped text safe to keep as personal memory. None when it holds a secret."""
    if not text or contains_secret(text):
        return None
    cleaned, _ = redact(text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:max_len] or None


def sanitize_for_shared(text: Optional[str], max_len: int = 2000) -> Optional[str]:
    """Text for the shared knowledge base. Stricter than memory: refuses anything the filter
    would have changed, rather than storing a redacted copy of someone's private message."""
    if not text or not is_clean(text):
        return None
    return text.strip()[:max_len]
