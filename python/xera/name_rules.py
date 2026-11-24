"""
Real-name rules for new accounts (and, later, the paid name change).

One place for the rules so every signup path and the future name-change
endpoint agree. Pure functions, no database access.

A name is a *declaration* here: we cannot check it against an ID until KYC.
These rules only stop obvious junk (handles, numbers, emoji) and names that
pretend to be the company or staff.
"""
from __future__ import annotations

import re

MIN_LEN = 3
MAX_LEN = 60

# Whole words that can't appear in a person's name: impersonation of the
# company, staff or the system. Matched case-insensitively as whole words.
RESERVED_WORDS = frozenset({
    "admin", "administrator", "support", "official", "moderator", "mod",
    "staff", "team", "help", "bot", "system", "root", "service",
    "evoxera", "evos", "evoshub", "xera", "evosdata", "evosgpt",
})

_ALLOWED_PUNCT = set(" -'.’")


def normalize_name(raw: str | None) -> str:
    """Trim and collapse runs of whitespace. Case is left as the user typed it."""
    return re.sub(r"\s+", " ", (raw or "").strip())


def check_real_name(raw: str | None) -> tuple[str, str | None]:
    """
    Returns (clean_name, error). error is None when the name is acceptable,
    otherwise a short user-facing message.
    """
    name = normalize_name(raw)
    if len(name) < MIN_LEN:
        return name, "Enter your real name as it appears on your ID."
    if len(name) > MAX_LEN:
        return name, f"Name is too long (max {MAX_LEN} characters)."

    for ch in name:
        if not (ch.isalpha() or ch in _ALLOWED_PUNCT):
            return name, "Use letters only in your name: no numbers, emojis or symbols."

    words = [w for w in re.split(r"[ ]", name) if w]
    letters_per_word = [sum(c.isalpha() for c in w) for w in words]
    if len(words) < 2 or any(n == 0 for n in letters_per_word):
        return name, "Enter your first and last name, as on your government ID."
    if sum(letters_per_word) < 4:
        return name, "Enter your first and last name, as on your government ID."

    lowered = {re.sub(r"[^a-z]", "", w.lower()) for w in words}
    if lowered & RESERVED_WORDS:
        return name, "That name can't be used. Enter your real name as on your ID."

    # e.g. "aaaa aaaa" or "xxx xxx"
    flat = re.sub(r"[^a-z]", "", name.lower())
    if flat and len(set(flat)) < 3:
        return name, "Enter your real name as it appears on your ID."

    return name, None
