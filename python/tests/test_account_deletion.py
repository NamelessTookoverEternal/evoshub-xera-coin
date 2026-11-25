"""
Account deletion + name change routes: password check, database error -> friendly message, the sweep.
The rules themselves (blockers, forfeit, anonymise, idempotency) live in Postgres and were tested there
(migrations 20261125_xera_account_deletion_v1.sql and 20261124_xera_name_change_v1.sql). Supabase is a fake here.
"""
import types

import pytest
from fastapi import HTTPException

from xera import account_deletion as ad
from xera import name_change as nc
from xera.name_rules import check_real_name
from xera.routes_auth import pwd_context


class _Res:
    def __init__(self, data): self.data = data
    def execute(self): return self


class _Table:
    def __init__(self, fake, name): self.fake, self.name = fake, name
    def select(self, *_a, **_k): return self
    def eq(self, *_a): return self
    def limit(self, *_a): return self
    def insert(self, *_a, **_k): return self
    def execute(self): return _Res(self.fake.tables.get(self.name, []))


class _Fake:
    def __init__(self, tables=None, rpcs=None):
        self.tables, self.rpcs, self.calls = tables or {}, rpcs or {}, []
    def table(self, name): return _Table(self, name)
    def rpc(self, name, params):
        self.calls.append((name, params))
        h = self.rpcs[name]
        out = h(params) if callable(h) else h
        if isinstance(out, Exception):
            raise out
        return _Res(out)


def _req(): return types.SimpleNamespace(client=types.SimpleNamespace(host="1.2.3.4"), url=types.SimpleNamespace(path="/x"))


def _use(monkeypatch, fake):
    monkeypatch.setattr(ad, "supabase", fake)
    monkeypatch.setattr(ad, "_current_user_id", lambda r, a: 7)
    monkeypatch.setattr(ad, "_log_security_event", lambda *a, **k: None)


def test_wrong_password_never_reaches_the_database(monkeypatch):
    fake = _Fake(tables={"users": [{"password": pwd_context.hash("right-pass")}]})
    _use(monkeypatch, fake)
    with pytest.raises(HTTPException) as e:
        ad.request_deletion(_req(), ad.RequestDeletion(password="wrong"), "Bearer x")
    assert e.value.status_code == 403
    assert not fake.calls


def test_blocker_from_database_becomes_a_clear_message(monkeypatch):
    fake = _Fake(tables={"users": [{"password": pwd_context.hash("right-pass")}]},
                 rpcs={"xera_request_account_deletion": Exception("claim_in_progress"),
                       "xera_deletion_preview": [{"xera_balance": 0, "customer_wallet_ghs": 0, "agent_wallet_ghs": 0}]})
    _use(monkeypatch, fake)
    with pytest.raises(HTTPException) as e:
        ad.request_deletion(_req(), ad.RequestDeletion(password="right-pass"), "Bearer x")
    assert e.value.status_code == 409 and "claim" in e.value.detail.lower()


def test_sweep_erases_kyc_photos_only_for_finished_accounts(monkeypatch):
    erased = []
    monkeypatch.setattr(ad.kyc_documents, "purge_user", lambda uid, why: erased.append((uid, why)) or {"erased": 1, "failed": 0})
    done = {1: {"id": 5}, 2: None}          # user 2 was blocked at the last moment: nothing finished
    fake = _Fake(rpcs={"xera_due_account_deletions": [1, 2],
                       "xera_complete_account_deletion": lambda p: [done[p["p_user_id"]]] if done[p["p_user_id"]] else []})
    monkeypatch.setattr(ad, "supabase", fake)
    assert ad.process_due() == {"completed": 1, "waiting": 1}
    assert erased == [(1, "ACCOUNT_DELETED")]


def test_sweep_never_raises_when_migration_missing(monkeypatch):
    monkeypatch.setattr(ad, "supabase", _Fake(rpcs={"xera_due_account_deletions": Exception("does not exist")}))
    ad.process_due_safely()


def test_sweep_route_is_hidden_without_a_key_and_checks_it(monkeypatch):
    monkeypatch.delenv("ACCOUNT_DELETION_CRON_KEY", raising=False)
    with pytest.raises(HTTPException) as e:
        ad.sweep(_req(), "anything")
    assert e.value.status_code == 404
    monkeypatch.setenv("ACCOUNT_DELETION_CRON_KEY", "secret")
    with pytest.raises(HTTPException) as e:
        ad.sweep(_req(), "nope")
    assert e.value.status_code == 403


def test_name_change_error_mapping_and_validation(monkeypatch):
    fake = _Fake(rpcs={"xera_change_name": Exception("kyc_locked")})
    monkeypatch.setattr(nc, "supabase", fake)
    monkeypatch.setattr(nc, "_current_user_id", lambda r, a: 7)
    monkeypatch.setattr(nc, "_log_security_event", lambda *a, **k: None)
    monkeypatch.setattr(nc.money_lock, "is_locked", lambda uid: False)
    with pytest.raises(HTTPException) as e:                       # junk name is refused before the database
        nc.name_change(_req(), nc.ChangeNameRequest(new_name="Admin Kofi", request_id="abcdefgh12"), "Bearer x")
    assert e.value.status_code == 400 and not fake.calls
    with pytest.raises(HTTPException) as e:                       # a locked name is explained
        nc.name_change(_req(), nc.ChangeNameRequest(new_name="Kofi Mensah", request_id="abcdefgh12"), "Bearer x")
    assert e.value.status_code == 403 and "locked" in e.value.detail.lower()


@pytest.mark.parametrize("name,ok", [
    ("Kwame Mensah", True), ("Mary-Jane O'Neil", True), ("José Álvarez", True), ("Yaa Asantewaa", True),
    ("Rebirth", False), ("rebirth_8943", False), ("John 2", False), ("EVOXERA Support", False), ("aaa aaa", False),
])
def test_real_name_rules(name, ok):
    assert (check_real_name(name)[1] is None) is ok


# ---------- v2: two-step flow (preview -> popup 2 -> request), wallets of every product ----------

_PW = pwd_context.hash("right-pass")


def _prev(xera=0, cust=0, agent=0, is_agent=False, tier="Basic"):
    return {"xera_balance": xera, "customer_wallet_ghs": cust, "agent_wallet_ghs": agent, "is_agent": is_agent, "evosgpt_tier": tier}


def _flow(monkeypatch, preview, blocker=None, pending=False, request_rpc=None):
    tables = {"users": [{"password": _PW}],
              "xera_account_deletion_config": [{"enabled": True, "grace_days": 7}],
              "xera_account_deletions": [{"id": 1, "requested_at": "x", "purge_after": "y"}] if pending else [],
              "xera_wallets": [{"cached_balance": 5}]}
    rpcs = {"xera_deletion_preview": [preview], "xera_deletion_blocker": blocker,
            "xera_request_account_deletion": request_rpc if request_rpc is not None else [{"id": 1}]}
    fake = _Fake(tables=tables, rpcs=rpcs)
    _use(monkeypatch, fake)
    return fake


def test_preview_wrong_password_shows_nothing(monkeypatch):
    fake = _flow(monkeypatch, _prev(xera=10))
    with pytest.raises(HTTPException) as e:
        ad.preview_deletion(_req(), ad.PreviewDeletion(password="nope"), "Bearer x")
    assert e.value.status_code == 403 and not fake.calls


def test_preview_lists_every_product_and_schedules_nothing(monkeypatch):
    fake = _flow(monkeypatch, _prev(xera=1250, cust="12.50", agent="30", is_agent=True, tier="Pro"))
    out = ad.preview_deletion(_req(), ad.PreviewDeletion(password="right-pass"), "Bearer x")
    names = [p["name"] for p in out["products"]]
    assert names == ["XERA", "EVOS Data", "EVOSGPT"]
    data = next(p for p in out["products"] if p["key"] == "evosdata")
    assert [w["label"] for w in data["wallets"]] == ["Customer wallet", "Agent wallet"]
    assert all(w["lost"] for w in data["wallets"])
    assert out["totals"] == {"xera": "1250", "ghs": "42.50"} and out["has_balance"] is True
    assert any("Pro" in n for n in next(p for p in out["products"] if p["key"] == "evosgpt")["notes"])
    assert "xera_request_account_deletion" not in [c[0] for c in fake.calls]     # nothing scheduled by the preview


def test_preview_hides_agent_wallet_for_customers_and_flags_no_balance(monkeypatch):
    _flow(monkeypatch, _prev())
    out = ad.preview_deletion(_req(), ad.PreviewDeletion(password="right-pass"), "Bearer x")
    data = next(p for p in out["products"] if p["key"] == "evosdata")
    assert [w["label"] for w in data["wallets"]] == ["Customer wallet"] and out["has_balance"] is False


def test_preview_is_refused_with_the_reason_when_blocked(monkeypatch):
    _flow(monkeypatch, _prev(), blocker="claim_in_progress")
    with pytest.raises(HTTPException) as e:
        ad.preview_deletion(_req(), ad.PreviewDeletion(password="right-pass"), "Bearer x")
    assert e.value.status_code == 409 and "claim" in e.value.detail.lower()


# ---------- v3: a stuck EVOS Data order blocks the first press only ----------

def _json(resp):
    import json
    return json.loads(resp.body)


def test_stuck_order_first_press_shows_the_notice_and_says_it_can_continue(monkeypatch):
    fake = _flow(monkeypatch, _prev(), blocker="evosdata_in_progress")
    resp = ad.preview_deletion(_req(), ad.PreviewDeletion(password="right-pass"), "Bearer x")
    body = _json(resp)
    assert resp.status_code == 409 and body["code"] == "evosdata_in_progress" and body["can_continue"] is True
    assert "in progress" in body["detail"].lower()
    assert "xera_request_account_deletion" not in [c[0] for c in fake.calls]


def test_stuck_order_second_press_opens_popup_2_with_a_warning(monkeypatch):
    fake = _flow(monkeypatch, _prev(cust="20"), blocker="evosdata_in_progress")
    fake.rpcs["xera_deletion_blocker_v3"] = lambda p: None if p["p_skip_busy"] else "evosdata_in_progress"
    fake.rpcs["xera_deletion_evosdata_busy"] = True
    out = ad.preview_deletion(_req(), ad.PreviewDeletion(password="right-pass", continue_busy=True), "Bearer x")
    assert out["status"] == "ok" and out["has_balance"] is True
    assert len(out["warnings"]) == 1 and "in progress" in out["warnings"][0].lower()
    assert [p["name"] for p in out["products"]] == ["XERA", "EVOS Data", "EVOSGPT"]


def test_second_press_does_not_skip_any_other_blocker(monkeypatch):
    fake = _flow(monkeypatch, _prev(), blocker="evosdata_in_progress")
    fake.rpcs["xera_deletion_blocker_v3"] = "kyc_in_review"            # a different blocker is still there
    with pytest.raises(HTTPException) as e:
        ad.preview_deletion(_req(), ad.PreviewDeletion(password="right-pass", continue_busy=True), "Bearer x")
    assert e.value.status_code == 409 and "identity" in e.value.detail.lower()


def test_second_press_without_migration_v3_still_blocks_safely(monkeypatch):
    fake = _flow(monkeypatch, _prev(), blocker="evosdata_in_progress")  # v3 rpc missing in the fake -> raises -> old blocker
    resp = ad.preview_deletion(_req(), ad.PreviewDeletion(password="right-pass", continue_busy=True), "Bearer x")
    assert resp.status_code == 409


def test_request_with_continue_busy_uses_the_v3_schedule_function(monkeypatch):
    fake = _flow(monkeypatch, _prev())
    fake.rpcs["xera_request_account_deletion_v3"] = [{"id": 1}]
    ad.request_deletion(_req(), ad.RequestDeletion(password="right-pass", continue_busy=True, seen_xera="0", seen_ghs="0"), "Bearer x")
    names = [c[0] for c in fake.calls]
    assert "xera_request_account_deletion_v3" in names and "xera_request_account_deletion" not in names
    assert [c for c in fake.calls if c[0] == "xera_request_account_deletion_v3"][0][1] == {"p_user_id": 7, "p_skip_busy": True}


def test_request_without_continue_busy_keeps_using_the_old_function(monkeypatch):
    fake = _flow(monkeypatch, _prev())
    ad.request_deletion(_req(), ad.RequestDeletion(password="right-pass", seen_xera="0", seen_ghs="0"), "Bearer x")
    assert "xera_request_account_deletion" in [c[0] for c in fake.calls]


def test_status_keeps_the_delete_button_enabled_for_a_stuck_order(monkeypatch):
    fake = _flow(monkeypatch, _prev(), blocker="evosdata_in_progress")
    fake.rpcs["xera_deletion_blocker_v3"] = None                       # with the stuck order skipped, nothing blocks
    out = ad.deletion_status(_req(), "Bearer x")
    assert out["blocked_reason"] is None


def test_request_needs_the_second_warning_when_money_is_at_stake(monkeypatch):
    fake = _flow(monkeypatch, _prev(cust="20"))
    with pytest.raises(HTTPException) as e:
        ad.request_deletion(_req(), ad.RequestDeletion(password="right-pass", seen_xera="0", seen_ghs="20"), "Bearer x")
    assert e.value.status_code == 409 and "balances" in e.value.detail.lower()
    assert "xera_request_account_deletion" not in [c[0] for c in fake.calls]


def test_request_goes_through_after_the_user_accepts_the_loss(monkeypatch):
    fake = _flow(monkeypatch, _prev(cust="20"))
    out = ad.request_deletion(_req(), ad.RequestDeletion(password="right-pass", acknowledge_loss=True, seen_xera="0", seen_ghs="20.00"), "Bearer x")
    assert out["status"] == "ok" and "xera_request_account_deletion" in [c[0] for c in fake.calls]


def test_request_with_no_balance_needs_no_second_warning(monkeypatch):
    fake = _flow(monkeypatch, _prev())
    ad.request_deletion(_req(), ad.RequestDeletion(password="right-pass", seen_xera="0", seen_ghs="0"), "Bearer x")
    assert "xera_request_account_deletion" in [c[0] for c in fake.calls]


def test_request_is_refused_when_balances_changed_since_the_popup(monkeypatch):
    fake = _flow(monkeypatch, _prev(cust="50"))                # GHS 30 was topped up after the popup showed 20
    with pytest.raises(HTTPException) as e:
        ad.request_deletion(_req(), ad.RequestDeletion(password="right-pass", acknowledge_loss=True, seen_xera="0", seen_ghs="20"), "Bearer x")
    assert e.value.status_code == 412
    assert "xera_request_account_deletion" not in [c[0] for c in fake.calls]


def test_new_blocker_from_database_becomes_a_clear_message(monkeypatch):
    _flow(monkeypatch, _prev(), request_rpc=Exception("evosdata_in_progress"))
    with pytest.raises(HTTPException) as e:
        ad.request_deletion(_req(), ad.RequestDeletion(password="right-pass"), "Bearer x")
    assert e.value.status_code == 409 and "in progress" in e.value.detail.lower()


def test_sweep_erases_evosgpt_files_only_for_finished_accounts(monkeypatch):
    seen = []
    monkeypatch.setattr(ad.kyc_documents, "purge_user", lambda uid, why: {"erased": 0, "failed": 0})
    monkeypatch.setattr(ad, "_erase_evosgpt_files", lambda uid: seen.append(uid) or 0)
    done = {1: {"id": 5}, 2: None}
    fake = _Fake(rpcs={"xera_due_account_deletions": [1, 2],
                       "xera_complete_account_deletion": lambda p: [done[p["p_user_id"]]] if done[p["p_user_id"]] else []})
    monkeypatch.setattr(ad, "supabase", fake)
    ad.process_due()
    assert seen == [1]


def test_evosgpt_folder_erase_removes_files_in_both_buckets(monkeypatch):
    removed = {}

    class _Store:
        def __init__(self, b): self.b = b
        def list(self, path): return [{"name": "a.png"}, {"name": "b.png"}] if path == "9" else []
        def remove(self, paths): removed[self.b] = paths

    class _Storage:
        def from_(self, b): return _Store(b)

    monkeypatch.setattr(ad, "supabase", types.SimpleNamespace(storage=_Storage()))
    assert ad._erase_evosgpt_files(9) == 4
    assert removed["evosgpt-images"] == ["9/a.png", "9/b.png"] and set(removed) == {"evosgpt-images", "evosgpt-documents"}
