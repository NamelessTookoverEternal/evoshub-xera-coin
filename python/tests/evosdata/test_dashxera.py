"""
DashXera test suite.

No database, no network. A fake Supabase client stands in for the real one,
so this runs anywhere:  python3 test_dashxera.py

Covers: reporting windows, the selling/base/agent price separation, historical
cost protection, agent reporting, order counts, undispatched detection,
provider health, low balance, Paystack, reprocessing, duplicate prevention,
audit logging, the optional XERA integration, and empty datasets.
"""
import os
import sys
import types
import logging
from datetime import datetime, timedelta, timezone

os.environ["ADMIN_TOKEN_SECRET"] = "test-token-secret"
os.environ["PAYSTACK_SECRET_KEY"] = ""
os.environ["DATAMART_API_KEY"] = ""
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ============================================================================
# FAKE SUPABASE
# ============================================================================

DB = {}


class Res:
    def __init__(self, data, count=None):
        self.data = data
        self.count = count


class Q:
    def __init__(self, name, rows):
        self.name = name
        self.rows = list(rows)
        self._pending = None
        self._insert = None
        self._count = False
        self._total = None

    def select(self, *a, **k):
        self._count = k.get("count") == "exact"
        return self

    def order(self, *a, **k):
        return self

    def limit(self, n):
        self.rows = self.rows[:n]
        return self

    def gte(self, c, v):
        self.rows = [r for r in self.rows if str(r.get(c, "")) >= v]
        return self

    def lte(self, c, v):
        self.rows = [r for r in self.rows if str(r.get(c, "")) <= v]
        return self

    def eq(self, c, v):
        self.rows = [r for r in self.rows if r.get(c) == v]
        return self

    def in_(self, c, vals):
        self.rows = [r for r in self.rows if r.get(c) in vals]
        return self

    def is_(self, c, v):
        self.rows = [r for r in self.rows if r.get(c) is v]
        return self

    def or_(self, expr):
        return self

    @property
    def not_(self):
        parent = self

        class Not:
            def is_(self, c, v):
                parent.rows = [r for r in parent.rows if r.get(c) is not v]
                return parent
        return Not()

    def range(self, a, b):
        self._total = len(self.rows)
        self.rows = self.rows[a:b + 1]
        return self

    def insert(self, payload):
        self._insert = dict(payload)
        return self

    def update(self, payload):
        self._pending = dict(payload)
        return self

    def execute(self):
        if self._insert is not None:
            row = self._insert
            row.setdefault("id", len(DB.setdefault(self.name, [])) + 1)
            # Real Postgres fills created_at from the column default.
            row.setdefault("created_at", datetime.now(timezone.utc).isoformat())
            DB[self.name].append(row)
            return Res([row])
        if self._pending is not None:
            # supabase-py chains .update({...}).eq(...) — the write must land
            # only on rows that survived the filters.
            for r in self.rows:
                r.update(self._pending)
        total = self._total if self._total is not None else len(self.rows)
        return Res(self.rows, count=total if self._count else None)


class FakeDB:
    def table(self, name):
        if name not in DB:
            raise Exception(f'relation "{name}" does not exist')
        return Q(name, DB[name])

    def rpc(self, name, params):
        # Off by default so the Python fallback paths get exercised. Section
        # 21 re-runs the key assertions with the aggregates enabled.
        raise Exception(f"function {name} does not exist")


def iso(dt):
    return dt.isoformat()


NOW = datetime.now(timezone.utc)
FAILS = []


def check(label, cond, extra=""):
    print(("  ok  " if cond else "  FAIL") + f"  {label}" + (f"   [{extra}]" if extra != "" else ""))
    if not cond:
        FAILS.append(label)


def section(title):
    print(f"\n{title}")


def reset_db(orders=None, **tables):
    DB.clear()
    DB["orders"] = orders if orders is not None else []
    DB["base_prices"] = tables.pop("base_prices", [])
    DB["users"] = tables.pop("users", [])
    DB["provider_routes"] = tables.pop("provider_routes", [])
    DB["provider_incidents"] = tables.pop("provider_incidents", [])
    DB["dashxera_actions"] = tables.pop("dashxera_actions", [])
    for key, value in tables.items():
        DB[key] = value


fake_main = types.ModuleType("services.evosdata.core")
fake_main.supabase = FakeDB()
fake_main.NETWORK_MAP = {"MTN": "YELLO"}
fake_main.extract_capacity = lambda b: b.replace("GB", "")
fake_main.REQUEST_TIMEOUT = 10
fake_main.get_provider_chain = lambda n: ["DATAMART", "BUNDLES_GHANA"]
fake_main.DATAMART_BASE = "https://example.invalid"
sys.modules["services.evosdata.core"] = fake_main

from services.evosdata import dashxera as dx  # noqa: E402

# Start the incident worker up front. Without it, any _INCIDENT_QUEUE.join()
# before install_log_capture() would block forever waiting on task_done().
dx._ensure_worker()

ADMIN = "tester"


# ============================================================================
section("[1] Reporting windows — 7 minimum, 90 maximum")
# ============================================================================
for value, expected in [(7, 7), (14, 14), (30, 30), (60, 60), (90, 90),
                        (1, 7), (3, 7), (500, 90), (None, 7), ("abc", 7)]:
    check(f"{value!r} -> {expected}", dx._window(value) == expected, dx._window(value))
check("45 snaps to a supported window", dx._window(45) in dx.ALLOWED_WINDOWS, dx._window(45))


# ============================================================================
section("[2] Section 24 worked example — sold / base / agent kept separate")
# ============================================================================
reset_db(
    orders=[
        {"id": 1, "created_at": iso(NOW - timedelta(days=1)), "status": "successful",
         "price": 5.31, "base_price": 4.00, "agent_price": 4.50, "agent_id": 7,
         "network": "MTN", "bundle": "1GB", "datamart_ref": "DM1", "paystack_ref": "ps1"},
        {"id": 2, "created_at": iso(NOW - timedelta(days=2)), "status": "successful",
         "price": 19.00, "base_price": 16.00, "agent_price": None, "agent_id": None,
         "network": "MTN", "bundle": "5GB", "datamart_ref": "DM2", "paystack_ref": "ps2"},
    ],
    users=[{"id": 7, "username": "johndata", "full_name": "John Mensah",
            "store_name": "John Data Hub"}],
)
s = dx.dashxera_summary(days=7, _=ADMIN)
f = s["financials"]
check("Total Sold = 24.31", f["total_sold"] == 24.31, f["total_sold"])
check("Total Base Cost = 20.00", f["total_base_cost"] == 20.00, f["total_base_cost"])
check("Gross Margin = 4.31", f["gross_margin"] == 4.31, f["gross_margin"])
check("Sold is not base price", f["total_sold"] != f["total_base_cost"])
check("Agent sold = 5.31 (selling price, not agent price)", f["agent_sold"] == 5.31, f["agent_sold"])
check("Agent price total = 4.50 (separate figure)", f["agent_price_total"] == 4.50, f["agent_price_total"])
check("Direct sold = 19.00", f["direct_sold"] == 19.00, f["direct_sold"])
check("Cost coverage 100%", f["cost_coverage"]["coverage_pct"] == 100.0)
check("Average sold = 12.16", f["average_sold"] == 12.16, f["average_sold"])
check("Average base = 10.00", f["average_base_cost"] == 10.00, f["average_base_cost"])

agents = dx.dashxera_agents(days=7, _=ADMIN)
john = agents["agents"][0]
check("Agent name from users.store_name", john["agent_name"] == "John Data Hub", john["agent_name"])
check("Agent sold 5.31", john["sold"] == 5.31)
check("Agent price 4.50", john["agent_price_total"] == 4.50)
check("Agent recorded cost 4.00", john["recorded_base_cost"] == 4.00)
check("Direct sale excluded from agent report", agents["agent_count"] == 1, agents["agent_count"])


# ============================================================================
section("[3] Historical cost is never overwritten by today's price list")
# ============================================================================
reset_db(
    orders=[
        # Recorded 4.00 historically; today's list says 9.00. Recorded wins.
        {"id": 1, "created_at": iso(NOW - timedelta(days=3)), "status": "successful",
         "price": 5.31, "base_price": 4.00, "agent_id": None,
         "network": "MTN", "bundle": "1GB", "datamart_ref": "DM1", "paystack_ref": "p1"},
        # No recorded cost — estimated and flagged, never silently merged.
        {"id": 2, "created_at": iso(NOW - timedelta(days=3)), "status": "successful",
         "price": 12.00, "base_price": None, "agent_id": None,
         "network": "MTN", "bundle": "1GB", "datamart_ref": "DM2", "paystack_ref": "p2"},
    ],
    base_prices=[{"network": "MTN", "bundle": "1GB", "cost_price": 9.00}],
)
s = dx.dashxera_summary(days=7, _=ADMIN)
f = s["financials"]
cov = f["cost_coverage"]
check("Recorded cost stays 4.00, not today's 9.00", f["recorded_base_cost"] == 4.00, f["recorded_base_cost"])
check("Estimated cost reported separately = 9.00", f["estimated_base_cost"] == 9.00, f["estimated_base_cost"])
check("Total cost = 13.00", f["total_base_cost"] == 13.00, f["total_base_cost"])
check("recorded_margin uses only recorded rows", f["recorded_margin"] == 1.31, f["recorded_margin"])
check("coverage reports 1 of 2",
      cov["orders_with_recorded_cost"] == 1 and cov["orders_without_recorded_cost"] == 1)
check("coverage 50%", cov["coverage_pct"] == 50.0, cov["coverage_pct"])
check("coverage note warns about the estimate", "not historical" in cov["note"])

rows = dx.dashxera_orders(days=7, status=None, agent_id=None, network=None,
                          search=None, page=1, page_size=50, _=ADMIN)["orders"]
by_id = {r["id"]: r for r in rows}
check("order 1 cost source = recorded", by_id[1]["base_cost_source"] == "recorded")
check("order 2 cost source = estimated", by_id[2]["base_cost_source"] == "estimated")
check("order 1 margin from historical cost", by_id[1]["margin"] == 1.31, by_id[1]["margin"])

reset_db(orders=[{"id": 1, "created_at": iso(NOW - timedelta(days=1)), "status": "successful",
                  "price": 10.0, "base_price": None, "agent_id": None,
                  "network": "TELECEL", "bundle": "99GB", "datamart_ref": "D", "paystack_ref": "p"}],
         base_prices=[{"network": "MTN", "bundle": "1GB", "cost_price": 9.0}])
rows = dx.dashxera_orders(days=7, status=None, agent_id=None, network=None,
                          search=None, page=1, page_size=50, _=ADMIN)["orders"]
check("unknown bundle -> source 'missing', margin None",
      rows[0]["base_cost_source"] == "missing" and rows[0]["margin"] is None)


# ============================================================================
section("[4] Order counts by status")
# ============================================================================
reset_db(orders=[
    {"id": 1, "created_at": iso(NOW - timedelta(days=1)), "status": "successful", "price": 10.0,
     "base_price": 8.0, "agent_id": None, "network": "MTN", "bundle": "1GB",
     "datamart_ref": "D1", "paystack_ref": "p1"},
    {"id": 2, "created_at": iso(NOW - timedelta(days=1)), "status": "processing", "price": 20.0,
     "base_price": 16.0, "agent_id": None, "network": "MTN", "bundle": "2GB",
     "datamart_ref": None, "paystack_ref": "p2"},
    {"id": 3, "created_at": iso(NOW - timedelta(days=1)), "status": "failed", "price": 30.0,
     "base_price": 24.0, "agent_id": None, "network": "MTN", "bundle": "3GB",
     "datamart_ref": None, "paystack_ref": "p3"},
    {"id": 4, "created_at": iso(NOW - timedelta(days=1)), "status": "pending_payment", "price": 40.0,
     "base_price": 32.0, "agent_id": None, "network": "MTN", "bundle": "4GB",
     "datamart_ref": None, "paystack_ref": "p4"},
])
s = dx.dashxera_summary(days=7, _=ADMIN)
o, f = s["orders"], s["financials"]
check("total 4", o["total"] == 4, o["total"])
check("successful 1", o["successful"] == 1)
check("processing 1", o["processing"] == 1)
check("failed 1", o["failed"] == 1)
check("awaiting_payment 1", o["awaiting_payment"] == 1)
check("paid orders = 3 (abandoned checkout excluded)", o["paid"] == 3, o["paid"])
check("undispatched 2", o["undispatched"] == 2, o["undispatched"])
check("sold excludes abandoned checkout", f["total_sold"] == 60.0, f["total_sold"])
check("failed value 30", f["failed_value"] == 30.0)
check("undispatched value 50", f["undispatched_value"] == 50.0, f["undispatched_value"])
check("success rate 50%", s["quality"]["success_rate"] == 50.0)
check("7-day series covers 8 days", len(s["series"]) == 8, len(s["series"]))

s90 = dx.dashxera_summary(days=90, _=ADMIN)
check("90-day window returns the same 4 orders", s90["orders"]["total"] == 4)
check("90-day series length 91", len(s90["series"]) == 91, len(s90["series"]))
check("90-day sold matches", s90["financials"]["total_sold"] == 60.0)


# ============================================================================
section("[5] Orders outside the window are excluded")
# ============================================================================
reset_db(orders=[
    {"id": 1, "created_at": iso(NOW - timedelta(days=3)), "status": "successful", "price": 10.0,
     "base_price": 8.0, "agent_id": None, "network": "MTN", "bundle": "1GB",
     "datamart_ref": "D1", "paystack_ref": "p1"},
    {"id": 2, "created_at": iso(NOW - timedelta(days=40)), "status": "successful", "price": 100.0,
     "base_price": 80.0, "agent_id": None, "network": "MTN", "bundle": "9GB",
     "datamart_ref": "D2", "paystack_ref": "p2"},
])
check("7-day sold = 10", dx.dashxera_summary(days=7, _=ADMIN)["financials"]["total_sold"] == 10.0)
check("60-day sold = 110", dx.dashxera_summary(days=60, _=ADMIN)["financials"]["total_sold"] == 110.0)


# ============================================================================
section("[6] Empty dataset")
# ============================================================================
reset_db(orders=[])
s = dx.dashxera_summary(days=7, _=ADMIN)
check("no crash, total 0", s["orders"]["total"] == 0)
check("sold 0.0", s["financials"]["total_sold"] == 0.0)
check("no divide-by-zero on averages", s["financials"]["average_sold"] == 0.0)
check("success rate 0", s["quality"]["success_rate"] == 0.0)
check("coverage note is the all-clear",
      "carries its own historical cost" in s["financials"]["cost_coverage"]["note"])
check("agents empty", dx.dashxera_agents(days=7, _=ADMIN)["agent_count"] == 0)
check("undispatched empty", dx.dashxera_undispatched(days=7, verify=False, page=1,
                                                     page_size=50, _=ADMIN)["total"] == 0)
check("orders page empty", dx.dashxera_orders(days=7, status=None, agent_id=None, network=None,
                                              search=None, page=1, page_size=50, _=ADMIN)["orders"] == [])


# ============================================================================
section("[7] Paid but not dispatched — eligibility rules")
# ============================================================================
reset_db(orders=[
    {"id": 1, "created_at": iso(NOW - timedelta(days=1)), "status": "failed", "price": 10.0,
     "base_price": 8.0, "agent_id": None, "network": "MTN", "bundle": "1GB",
     "datamart_ref": None, "paystack_ref": "p1"},
    {"id": 2, "created_at": iso(NOW - timedelta(days=1)), "status": "pending_payment", "price": 20.0,
     "base_price": 16.0, "agent_id": None, "network": "MTN", "bundle": "2GB",
     "datamart_ref": None, "paystack_ref": "p2"},
    {"id": 3, "created_at": iso(NOW - timedelta(days=1)), "status": "processing", "price": 30.0,
     "base_price": 24.0, "agent_id": None, "network": "MTN", "bundle": "3GB",
     "datamart_ref": None, "paystack_ref": "EVOS-AGT-XYZ"},
])
u = dx.dashxera_undispatched(days=7, verify=False, page=1, page_size=50, _=ADMIN)
rows = {r["id"]: r for r in u["orders"]}
check("failed order is eligible", rows[1]["eligible"] is True)
check("unpaid order is not eligible", rows[2]["eligible"] is False)
check("unpaid reason names the cause", "never completed payment" in rows[2]["eligibility_reason"])
check("agent wallet order flagged", rows[3]["wallet_order"] is True)
check("wallet payment state set", rows[3]["payment_state"] == "wallet_debited")
check("eligible count excludes unpaid", u["eligible_on_page"] == 2, u["eligible_on_page"])
check("value counts only eligible", u["value_on_page"] == 40.0, u["value_on_page"])
check("age_hours present", all("age_hours" in r for r in u["orders"]))

check("dispatched order ineligible",
      dx._is_eligible({"status": "processing", "datamart_ref": "DM9"})[0] is False)
check("fulfilled order ineligible",
      dx._is_eligible({"status": "successful", "datamart_ref": None})[0] is False)
check("no payment reference ineligible",
      dx._is_eligible({"status": "paid", "datamart_ref": None})[0] is False)


# ============================================================================
section("[8] Reprocessing")
# ============================================================================
BASE_ORDER = {
    "id": 5, "created_at": iso(NOW - timedelta(days=1)), "status": "failed", "price": 10.0,
    "base_price": 8.0, "agent_price": None, "agent_id": None, "network": "MTN",
    "bundle": "1GB", "datamart_ref": None, "paystack_ref": "EVOS-AGT-WALLET",
    "provider_priority": 1, "reprocess_count": 0,
}


def fresh_order(**over):
    reset_db(orders=[{**BASE_ORDER, **over}])


fresh_order()
dx._dispatch = lambda order, provider: {"ok": True, "ref": "DM-NEW-1", "order_id": "777"}
r = dx._reprocess_one(5, dx.ReprocessRequest(), ADMIN)
row = DB["orders"][0]
check("wallet order reprocesses without Paystack", r["outcome"] == "success", r)
check("provider chosen from chain", r["provider"] == "DATAMART")
check("datamart_ref written", row["datamart_ref"] == "DM-NEW-1")
check("status -> processing", row["status"] == "processing")
check("dispatch_provider recorded", row["dispatch_provider"] == "DATAMART")
check("reprocess_count incremented", row["reprocess_count"] == 1)
check("previous_status reported", r["previous_status"] == "failed")


# ============================================================================
section("[9] Duplicate protection")
# ============================================================================
r2 = dx._reprocess_one(5, dx.ReprocessRequest(), ADMIN)
check("second attempt skipped", r2["outcome"] == "skipped", r2)
check("reason names the existing reference", "Already dispatched" in r2["reason"], r2["reason"])
check("datamart_ref unchanged", DB["orders"][0]["datamart_ref"] == "DM-NEW-1")
check("reprocess_count still 1", DB["orders"][0]["reprocess_count"] == 1)

fresh_order(status="successful", datamart_ref=None)
r = dx._reprocess_one(5, dx.ReprocessRequest(force=True), ADMIN)
check("force cannot re-send a fulfilled order", r["outcome"] == "skipped", r)
check("reason names fulfilment", "already fulfilled" in r["reason"].lower(), r["reason"])

fresh_order(datamart_ref="DM-EXISTING")
r = dx._reprocess_one(5, dx.ReprocessRequest(force=True), ADMIN)
check("force cannot re-send a dispatched order", r["outcome"] == "skipped", r)

fresh_order(status="pending_payment", paystack_ref="ps-unpaid")
r = dx._reprocess_one(5, dx.ReprocessRequest(), ADMIN)
check("unpaid order refused without force", r["outcome"] == "skipped", r)
check("datamart_ref still empty", DB["orders"][0].get("datamart_ref") is None)

fresh_order()
lock = dx._order_lock(5)
lock.acquire()
r = dx._reprocess_one(5, dx.ReprocessRequest(), ADMIN)
lock.release()
check("concurrent attempt refused by lock", r["outcome"] == "skipped", r)
check("lock reason is explicit", "already running" in r["reason"])

fresh_order()
r = dx._reprocess_one(5, dx.ReprocessRequest(provider="SWIFT_DATA_LINK"), ADMIN)
check("provider outside the chain refused", r["outcome"] == "skipped", r)
check("reason names routing chain", "routing chain" in r["reason"])

fresh_order()
r = dx._reprocess_one(999, dx.ReprocessRequest(), ADMIN)
check("missing order handled", r["outcome"] == "skipped" and "not found" in r["reason"])


# ============================================================================
section("[10] Failed reprocess records incident, error and audit")
# ============================================================================
fresh_order()
dx._dispatch = lambda order, provider: {"ok": False, "error": "Insufficient wallet balance on DataMart"}
r = dx._reprocess_one(5, dx.ReprocessRequest(), ADMIN)
dx._INCIDENT_QUEUE.join()
check("outcome failed", r["outcome"] == "failed", r)
check("last_error saved on the order", "Insufficient" in (DB["orders"][0].get("last_error") or ""))
check("incident persisted", len(DB["provider_incidents"]) == 1, len(DB["provider_incidents"]))
check("classified as low_balance", DB["provider_incidents"][0]["kind"] == "low_balance")
check("severity critical", DB["provider_incidents"][0]["severity"] == "critical")
audit = DB["dashxera_actions"][-1]
check("audit records the failure", audit["outcome"] == "failed")
check("audit records the actor", audit["actor"] == ADMIN)
check("audit records previous status", audit["previous_status"] == "failed")
check("audit records the provider", audit["provider"] == "DATAMART")


# ============================================================================
section("[11] Audit log on success")
# ============================================================================
fresh_order()
dx._dispatch = lambda order, provider: {"ok": True, "ref": "DM-OK", "order_id": "9"}
dx._reprocess_one(5, dx.ReprocessRequest(), ADMIN)
audit = DB["dashxera_actions"][-1]
check("action is reprocess", audit["action"] == "reprocess")
check("outcome success", audit["outcome"] == "success")
check("previous_status failed", audit["previous_status"] == "failed")
check("new_status processing", audit["new_status"] == "processing")
check("provider_ref stored", audit["provider_ref"] == "DM-OK")
check("order_id stored", audit["order_id"] == 5)
check("audit endpoint returns it",
      dx.dashxera_audit(days=7, order_id=None, page=1, page_size=50, _=ADMIN)["total"] >= 1)


# ============================================================================
section("[12] Bulk reprocessing re-checks each order")
# ============================================================================
reset_db(orders=[
    {**BASE_ORDER, "id": 10},
    {**BASE_ORDER, "id": 11, "datamart_ref": "ALREADY"},
    {**BASE_ORDER, "id": 12, "status": "successful"},
])
dx._dispatch = lambda order, provider: {"ok": True, "ref": f"DM-{order['id']}", "order_id": "1"}
bulk = dx.dashxera_reprocess_bulk(dx.BulkReprocessRequest(order_ids=[10, 11, 12, 10]), ADMIN)
check("duplicate id de-duplicated", len(bulk["results"]) == 3, len(bulk["results"]))
check("1 success, 2 skipped",
      bulk["summary"].get("success") == 1 and bulk["summary"].get("skipped") == 2, bulk["summary"])
check("already-dispatched untouched", DB["orders"][1]["datamart_ref"] == "ALREADY")
check("fulfilled order untouched", DB["orders"][2].get("datamart_ref") is None)

try:
    dx.dashxera_reprocess_bulk(dx.BulkReprocessRequest(order_ids=[]), ADMIN)
    check("empty bulk rejected", False)
except Exception as exc:
    check("empty bulk rejected", "at least one" in str(exc))

try:
    dx.dashxera_reprocess_bulk(dx.BulkReprocessRequest(order_ids=list(range(1, 60))), ADMIN)
    check("oversized bulk rejected", False)
except Exception as exc:
    check("oversized bulk rejected", "at most 50" in str(exc))


# ============================================================================
section("[13] Error classification")
# ============================================================================
for message, expected in {
    "Insufficient wallet balance to complete purchase": "low_balance",
    "Please top up your account to continue": "low_balance",
    "DataMart returned 429 Too Many Requests": "rate_limited",
    "HTTPSConnectionPool: Read timed out": "provider_down",
    "No active BG bundle for MTN 5GB": "out_of_stock",
    "401 Unauthorized: invalid api key": "auth",
    "Something odd happened": "purchase_failed",
}.items():
    got = dx.classify_provider_error(message)
    check(f"{expected:<16} <- {message[:38]!r}", got == expected, got)

check("DATAMART detected", dx.detect_provider("PURCHASE ERROR: DATAMART rejected") == "DATAMART")
check("BG alias detected", dx.detect_provider("BG order failed: no funds") == "BUNDLES_GHANA")
check("unknown falls back", dx.detect_provider("mystery failure") == "UNKNOWN")


# ============================================================================
section("[14] Log capture and deduplication")
# ============================================================================
reset_db(orders=[])
dx.install_log_capture()
prod = logging.getLogger("evos_prod_test")
prod.error("PURCHASE ERROR: DATAMART order 8813 failed - Insufficient wallet balance")
prod.info("PURCHASE ERROR: info level, must be ignored")
prod.error("an unrelated error nobody cares about")
dx._INCIDENT_QUEUE.join()
check("exactly one incident captured", len(DB["provider_incidents"]) == 1, len(DB["provider_incidents"]))
check("order id extracted from the log line", DB["provider_incidents"][0]["order_id"] == 8813)

prod.error("PURCHASE ERROR: DATAMART order 9999 failed - Insufficient wallet balance")
dx._INCIDENT_QUEUE.join()
check("repeat collapses into one row", len(DB["provider_incidents"]) == 1)
check("occurrences incremented", DB["provider_incidents"][0]["occurrences"] == 2,
      DB["provider_incidents"][0]["occurrences"])
check("fingerprint ignores order numbers",
      dx._fingerprint("DM", "low_balance", "order 1 failed: insufficient")
      == dx._fingerprint("DM", "low_balance", "order 2 failed: insufficient"))
check("fingerprint separates different errors",
      dx._fingerprint("DM", "low_balance", "insufficient")
      != dx._fingerprint("DM", "low_balance", "timeout"))


# ============================================================================
section("[15] Incident endpoint")
# ============================================================================
inc = dx.dashxera_incidents(days=7, include_resolved=False, kind=None, page=1, page_size=50, _=ADMIN)
check("incident returned", len(inc["incidents"]) == 1)
check("critical counted", inc["counts"]["critical"] == 1)
check("capture caveat is stated", "not recoverable" in inc["capture_note"])
try:
    dx.dashxera_incidents(days=7, include_resolved=False, kind="nonsense",
                          page=1, page_size=50, _=ADMIN)
    check("unknown kind rejected", False)
except Exception as exc:
    check("unknown kind rejected", "Unknown incident kind" in str(exc))

dx.dashxera_resolve_incident(DB["provider_incidents"][0]["id"], None, ADMIN)
check("resolve sets resolved_by", DB["provider_incidents"][0]["resolved_by"] == ADMIN)
check("resolve sets timestamp", DB["provider_incidents"][0]["resolved_at"] is not None)


# ============================================================================
section("[16] Provider health and low balance")
# ============================================================================
reset_db(
    orders=[],
    provider_routes=[
        {"provider": "DATAMART", "active": True},
        {"provider": "BUNDLES_GHANA", "active": True},
        {"provider": "SWIFT_DATA_LINK", "active": True},
        {"provider": "RETIRED_ONE", "active": False},
    ],
    provider_incidents=[
        {"id": 1, "provider": "DATAMART", "kind": "low_balance", "severity": "critical",
         "message": "Insufficient wallet balance", "occurrences": 5,
         "last_seen_at": iso(NOW - timedelta(hours=1)), "resolved_at": None},
        {"id": 2, "provider": "BUNDLES_GHANA", "kind": "provider_down", "severity": "warning",
         "message": "Read timed out", "occurrences": 2,
         "last_seen_at": iso(NOW - timedelta(hours=2)), "resolved_at": None},
    ],
)
p = dx.dashxera_providers(days=7, _=ADMIN)
health = {x["provider"]: x for x in p["providers"]}
check("inactive route excluded", "RETIRED_ONE" not in health, list(health))
check("DATAMART flagged LOW", health["DATAMART"]["health"] == "LOW", health["DATAMART"]["health"])
check("low balance message surfaced", "Insufficient" in health["DATAMART"]["latest_low_balance"])
check("BUNDLES_GHANA DEGRADED", health["BUNDLES_GHANA"]["health"] == "DEGRADED")
check("quiet provider is IDLE", health["SWIFT_DATA_LINK"]["health"] == "IDLE")
check("no fabricated provider balance", all(x["balance_available"] is False for x in p["providers"]))
check("balance absence is explained", "No balance endpoint" in health["DATAMART"]["balance_note"])
check("DATAMART in attention list", any(x["provider"] == "DATAMART" for x in p["attention"]))


# ============================================================================
section("[17] Paystack health")
# ============================================================================
check("no secret -> balance unavailable", p["paystack"]["balance_available"] is False)
check("health is UNKNOWN, not a guess", p["paystack"]["health"] == "UNKNOWN", p["paystack"]["health"])
check("reason given", "secret" in p["paystack"].get("reason", "").lower())


# ============================================================================
section("[18] Attention feed")
# ============================================================================
reset_db(
    orders=[{"id": 1, "created_at": iso(NOW - timedelta(days=1)), "status": "failed",
             "price": 25.0, "base_price": 20.0, "agent_id": None, "network": "MTN",
             "bundle": "1GB", "datamart_ref": None, "paystack_ref": "p1"}],
    provider_routes=[{"provider": "DATAMART", "active": True}],
    provider_incidents=[{"id": 1, "provider": "DATAMART", "kind": "low_balance",
                         "severity": "critical", "message": "Balance too low",
                         "occurrences": 1, "last_seen_at": iso(NOW), "resolved_at": None}],
)
a = dx.dashxera_attention(days=7, actor=ADMIN)
kinds = {i["kind"] for i in a["items"]}
check("undispatched money flagged", "undispatched" in kinds, kinds)
check("provider trouble flagged", "provider" in kinds)
check("amount stated in the detail", any("25.0" in i["detail"] for i in a["items"]))


# ============================================================================
section("[19] Ecosystem sales — XERA optional")
# ============================================================================
reset_db(
    orders=[{"id": 1, "created_at": iso(NOW - timedelta(days=1)), "status": "successful",
             "price": 50.0, "base_price": 40.0, "agent_id": None, "network": "MTN",
             "bundle": "1GB", "datamart_ref": "D", "paystack_ref": "p"}],
    evosgpt_purchases=[
        {"id": 1, "tier": "Pro", "status": "paid", "created_at": iso(NOW - timedelta(days=1))},
        {"id": 2, "tier": "Core", "status": "pending", "created_at": iso(NOW - timedelta(days=1))},
    ],
    website_requests=[
        {"id": "a", "package": "business", "status": "closed", "created_at": iso(NOW - timedelta(days=1))},
        {"id": "b", "package": "starter", "status": "new", "created_at": iso(NOW - timedelta(days=1))},
    ],
)
# xera_purchases deliberately absent.
e = dx.dashxera_ecosystem(days=7, _=ADMIN)
prods = e["products"]
check("EVOSDATA revenue = 50", prods["evosdata"]["revenue"] == 50.0)
check("EVOSDATA is not an estimate", prods["evosdata"]["estimated"] is False)
check("EVOSGPT Pro = 20", prods["evosgpt"]["revenue"] == 20.0)
check("EVOSGPT marked estimated", prods["evosgpt"]["estimated"] is True)
check("EVOSGPT explains the estimate", "tier" in prods["evosgpt"]["estimate_reason"])
check("EVOSGPT pending counted", prods["evosgpt"]["pending"] == 1)
check("EVOSHUB business = 2000", prods["evoshub"]["revenue"] == 2000.0)
check("XERA not connected", prods["xera"]["available"] is False)
check("XERA revenue is zero, not fabricated", prods["xera"]["revenue"] == 0.0)
check("XERA has a label for the UI", prods["xera"]["status_label"] == "Not connected")
check("total excludes XERA", e["total_revenue"] == 2070.0, e["total_revenue"])
check("estimates are declared", e["includes_estimates"] is True)

DB["xera_purchases"] = [
    {"id": 1, "price_ghs": 300.0, "xera_amount": 1000, "status": "paid",
     "created_at": iso(NOW - timedelta(days=1))},
    {"id": 2, "price_ghs": 100.0, "xera_amount": 300, "status": "pending_payment",
     "created_at": iso(NOW - timedelta(days=1))},
]
e = dx.dashxera_ecosystem(days=7, _=ADMIN)
check("XERA connects when the table appears", e["products"]["xera"]["available"] is True)
check("XERA revenue counts only paid", e["products"]["xera"]["revenue"] == 300.0)
check("XERA tokens reported", e["products"]["xera"]["tokens_sold"] == 1000.0)
check("total now includes XERA", e["total_revenue"] == 2370.0, e["total_revenue"])


# ============================================================================
section("[20] Pagination and filters")
# ============================================================================
reset_db(
    orders=[
        {"id": i, "created_at": iso(NOW - timedelta(hours=i)), "status": "successful",
         "price": 10.0, "base_price": 8.0, "agent_id": 7 if i % 2 else None,
         "network": "MTN" if i % 2 else "TELECEL", "bundle": "1GB",
         "datamart_ref": f"D{i}", "paystack_ref": f"p{i}"}
        for i in range(1, 13)
    ],
    users=[{"id": 7, "username": "jd", "full_name": "John M", "store_name": "John Data Hub"}],
)
page1 = dx.dashxera_orders(days=7, status=None, agent_id=None, network=None,
                           search=None, page=1, page_size=5, _=ADMIN)
check("page size respected", len(page1["orders"]) == 5, len(page1["orders"]))
check("total reported", page1["total"] == 12, page1["total"])
check("has_more true", page1["has_more"] is True)
page3 = dx.dashxera_orders(days=7, status=None, agent_id=None, network=None,
                           search=None, page=3, page_size=5, _=ADMIN)
check("last page has 2", len(page3["orders"]) == 2, len(page3["orders"]))
check("has_more false on last page", page3["has_more"] is False)

filtered = dx.dashxera_orders(days=7, status=None, agent_id=7, network=None,
                              search=None, page=1, page_size=50, _=ADMIN)
check("agent filter works", all(o["agent_id"] == 7 for o in filtered["orders"]))
check("agent name attached", filtered["orders"][0]["agent_name"] == "John Data Hub")
check("sale_type agent", filtered["orders"][0]["sale_type"] == "agent")

net = dx.dashxera_orders(days=7, status=None, agent_id=None, network="telecel",
                         search=None, page=1, page_size=50, _=ADMIN)
check("network filter is case-insensitive", len(net["orders"]) == 6, len(net["orders"]))
check("direct sales marked direct", all(o["sale_type"] == "direct" for o in net["orders"]))

dirty = dx.dashxera_orders(days=7, status=None, agent_id=None, network=None,
                           search="p1%,()'\"", page=1, page_size=50, _=ADMIN)
check("hostile search string handled", dirty["status"] is True)


# ============================================================================
section("[21] Postgres aggregate path produces the same shape")
# ============================================================================


class RpcDB(FakeDB):
    def rpc(self, name, params):
        if name == "dashxera_order_summary":
            return Q("_rpc", [{
                "total_orders": 2, "awaiting_payment": 0, "processing_orders": 0,
                "successful_orders": 2, "failed_orders": 0, "other_orders": 0,
                "paid_orders": 2, "sold": 24.31, "base_cost": 20.00,
                "orders_with_base": 2, "orders_missing_base": 0, "sold_missing_base": 0,
                "failed_value": 0, "undispatched_orders": 0, "undispatched_value": 0,
                "agent_orders": 1, "agent_sold": 5.31, "agent_price_total": 4.50,
                "direct_orders": 1, "direct_sold": 19.00,
            }])
        if name == "dashxera_daily_series":
            return Q("_rpc", [])
        if name == "dashxera_agent_summary":
            return Q("_rpc", [{"agent_id": 7, "agent_name": "John Data Hub",
                               "agent_username": "jd", "orders": 1, "sold": 5.31,
                               "agent_price_total": 4.50, "base_cost": 4.00,
                               "orders_with_base": 1, "successful_orders": 1,
                               "failed_orders": 0}])
        raise Exception(f"function {name} does not exist")


reset_db(orders=[])
fake_main.supabase = RpcDB()
s = dx.dashxera_summary(days=7, _=ADMIN)
check("rpc sold = 24.31", s["financials"]["total_sold"] == 24.31)
check("rpc base = 20.00", s["financials"]["recorded_base_cost"] == 20.00)
check("rpc margin = 4.31", s["financials"]["gross_margin"] == 4.31)
check("rpc agent sold = 5.31", s["financials"]["agent_sold"] == 5.31)
check("rpc agent price = 4.50", s["financials"]["agent_price_total"] == 4.50)
check("rpc series still backfilled", len(s["series"]) == 8)
ag = dx.dashxera_agents(days=7, _=ADMIN)
check("rpc agent name", ag["agents"][0]["agent_name"] == "John Data Hub")
check("rpc agent coverage 100%", ag["agents"][0]["cost_coverage_pct"] == 100.0)
fake_main.supabase = FakeDB()


# ============================================================================
section("[22] Missing DashXera tables degrade instead of crashing")
# ============================================================================
DB.clear()
DB["orders"] = []
DB["base_prices"] = []
check("incidents endpoint survives", dx.dashxera_incidents(
    days=7, include_resolved=False, kind=None, page=1, page_size=50, _=ADMIN)["incidents"] == [])
check("audit endpoint survives", dx.dashxera_audit(
    days=7, order_id=None, page=1, page_size=50, _=ADMIN)["actions"] == [])
check("providers endpoint survives", dx.dashxera_providers(days=7, _=ADMIN)["status"] is True)
check("migration hint given", "migration" in dx.dashxera_audit(
    days=7, order_id=None, page=1, page_size=50, _=ADMIN)["note"])


# ============================================================================
section("[23] require_dashxera_admin — admin_agents-gated login")
# ============================================================================
from services.evosdata import admin_auth as aa  # noqa: E402


class FakeRequest:
    def __init__(self, headers):
        self.headers = headers


reset_db(orders=[], admin_agents=[{"user_id": 7, "is_active": True, "display_name": "John Admin"}])

good_token = aa.make_admin_token(7)
actor = dx.require_dashxera_admin(FakeRequest({"Authorization": f"Bearer {good_token}"}))
check("valid session returns the admin_agents display name", actor == "John Admin", actor)

try:
    dx.require_dashxera_admin(FakeRequest({}))
    check("missing Authorization header rejected", False)
except Exception as exc:
    check("missing Authorization header rejected", getattr(exc, "status_code", None) == 401, exc)

try:
    dx.require_dashxera_admin(FakeRequest({"Authorization": "Bearer garbage.garbage"}))
    check("malformed token rejected", False)
except Exception as exc:
    check("malformed token rejected", getattr(exc, "status_code", None) == 401, exc)

try:
    dx.require_dashxera_admin(FakeRequest({"Authorization": "Bearer " + good_token[:-3] + "xxx"}))
    check("tampered signature rejected", False)
except Exception as exc:
    check("tampered signature rejected", getattr(exc, "status_code", None) == 401, exc)

# The OLD shared-secret header must do nothing now — DashXera no longer
# has any concept of X-Admin-Secret.
try:
    dx.require_dashxera_admin(FakeRequest({"X-Admin-Secret": "whatever-the-old-secret-was"}))
    check("old shared secret header no longer works", False)
except Exception as exc:
    check("old shared secret header no longer works", getattr(exc, "status_code", None) == 401, exc)

# Revocation takes effect on the very next request, same still-valid token.
DB["admin_agents"][0]["is_active"] = False
try:
    dx.require_dashxera_admin(FakeRequest({"Authorization": f"Bearer {good_token}"}))
    check("revoked admin_agents row blocks a still-valid token", False)
except Exception as exc:
    check("revoked admin_agents row blocks a still-valid token",
          getattr(exc, "status_code", None) == 403, exc)
DB["admin_agents"][0]["is_active"] = True

# A user with no admin_agents row at all — token is well-formed, but there's
# nothing to grant access.
stranger_token = aa.make_admin_token(999)
try:
    dx.require_dashxera_admin(FakeRequest({"Authorization": f"Bearer {stranger_token}"}))
    check("no admin_agents row at all is blocked", False)
except Exception as exc:
    check("no admin_agents row at all is blocked", getattr(exc, "status_code", None) == 403, exc)

# A blank display_name still resolves to something usable for the audit log,
# rather than an empty actor string.
reset_db(orders=[], admin_agents=[{"user_id": 7, "is_active": True, "display_name": ""}])
blank_name_token = aa.make_admin_token(7)
actor = dx.require_dashxera_admin(FakeRequest({"Authorization": f"Bearer {blank_name_token}"}))
check("blank display_name falls back to admin-<id>", actor == "admin-7", actor)


print("\n" + ("ALL PASS" if not FAILS else f"{len(FAILS)} FAILURES:\n  - " + "\n  - ".join(FAILS)))
sys.exit(1 if FAILS else 0)
