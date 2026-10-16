"""
Supabase client for EVOS Data.

EVOS Data and the Hub share one Supabase project (same `users` table, same
admin_agents). So by default Evosdata reuses the Hub's existing service-role
client — one connection pool, one set of credentials, no second SUPABASE_KEY.

If (and only if) EVOS Data's tables live in a DIFFERENT Supabase project, set
EVOSDATA_SUPABASE_URL and EVOSDATA_SUPABASE_KEY and a separate client is used.
"""
import os

from supabase import Client, create_client


def get_supabase() -> Client:
    url = os.getenv("EVOSDATA_SUPABASE_URL", "").strip().rstrip("/")
    key = os.getenv("EVOSDATA_SUPABASE_KEY", "").strip()
    if url and key:
        return create_client(url, key)
    from utils.xera_supabase import supabase as hub_supabase
    return hub_supabase
