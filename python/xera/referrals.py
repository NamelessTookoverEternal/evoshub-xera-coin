"""
XERA referral helpers.

The referral identity lives on the SHARED `users` row (users.referral_code /
users.referred_by — the same columns EVOSGPT and EVOS Data already write), so
a referral made in any EVOS product carries across all of them. See
supabase/migrations/20260930_xera_referrals_v1.sql for the schema and the
first-touch rule.
"""

import re
import uuid

from utils.supabase_admin import get_public_user_by_referral_code

# Superset of every format in the ecosystem: EVOS-ABCD-1F3A9C (EVOSGPT / XERA)
# and username_1234 (EVOS Data). Strict allow-list: this value is later
# compared inside SQL and echoed into URLs, so nothing else gets through.
_REF_CODE_RE = re.compile(r"^[A-Za-z0-9_-]{3,64}$")


def clean_ref(raw: str | None) -> str | None:
    """Returns a well-formed referral code, or None if absent/malformed."""
    if not raw:
        return None
    code = raw.strip()
    return code if _REF_CODE_RE.match(code) else None


def _candidate_code(username: str) -> str:
    prefix = re.sub(r"[^A-Za-z0-9]", "", username or "")[:4].upper() or "USER"
    return f"EVOS-{prefix}-{uuid.uuid4().hex[:6].upper()}"


async def new_unique_code(username: str) -> str:
    """Generates a code nobody owns yet (the DB unique index is the backstop)."""
    for _ in range(6):
        code = _candidate_code(username)
        if not await get_public_user_by_referral_code(code):
            return code
    # Astronomically unlikely; fall back to a longer random suffix.
    return f"EVOS-{uuid.uuid4().hex[:12].upper()}"


def mask_username(username: str | None) -> str:
    """Referrers see who joined, but not full usernames of other people."""
    u = (username or "").strip()
    if len(u) <= 2:
        return (u[:1] or "?") + "***"
    return u[:2] + "***"
