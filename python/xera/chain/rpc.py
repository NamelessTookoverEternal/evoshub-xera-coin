"""
Helpers for reading supabase-py RPC results.

A Postgres function declared `RETURNS some_table` (a single composite row,
not SETOF) comes back from PostgREST as ONE JSON object, so `res.data` is a
dict. A `RETURNS SETOF ...` / table query comes back as a list. Indexing a
dict with `[0]` raises KeyError(0) — and when that happens AFTER the RPC has
already committed, the caller sees a 500 for an operation that actually
succeeded. Always go through `first_row` instead of `res.data[0]`.
"""
from typing import Any, Optional


def first_row(data: Any) -> Optional[dict]:
    """Return the single row from an RPC/table result, or None if empty."""
    if not data:
        return None
    if isinstance(data, list):
        return data[0]
    return data
