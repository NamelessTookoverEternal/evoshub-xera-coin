"""Environment the merged backend needs to import (dummy values; no network, no real Supabase)."""
import os

os.environ.setdefault("SUPABASE_URL", "https://abc.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoic2VydmljZSJ9.abc")
os.environ.setdefault("XERA_TOKEN_SECRET", "y" * 40)
os.environ.setdefault("ADMIN_SECRET", "b" * 40)
