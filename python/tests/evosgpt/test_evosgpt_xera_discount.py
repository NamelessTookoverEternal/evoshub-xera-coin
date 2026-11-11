"""XERA discount on EVOSGPT plan upgrades. No network: Paystack and the XERA hold/consume functions are stubbed."""
import os

os.environ.setdefault("XERA_TOKEN_SECRET", "test-secret-for-evosgpt")


def _hdr(core, uid):
    return {"Authorization": f"Bearer {core.make_user_token(uid)}"}


class _Resp:
    def __init__(self, data): self._d = data
    def json(self): return self._d


def _elig(price=20.0, discount=2.0):
    final = price - discount
    return {"enabled": True, "eligible": True, "reason": "ok", "message": "", "list_price": price,
            "discount_ghs": discount, "xera_amount": discount * 100, "final_price": final,
            "final_pesewas": int(round(final * 100)), "hold_minutes": 60, "_calc": {}}


def _setup(env, quote):
    xd = env.core.xera_discount
    env.core.PAYSTACK_SECRET = "sk_test"
    calls = {"hold": [], "release": [], "consume": [], "paystack": []}
    env.monkeypatch.setattr(xd, "quote", lambda *a, **k: quote)
    env.monkeypatch.setattr(xd, "place_hold", lambda sb, uid, ref, q, cfg=None: calls["hold"].append((uid, ref)))
    env.monkeypatch.setattr(xd, "release", lambda sb, ref: calls["release"].append(ref))
    env.monkeypatch.setattr(xd, "consume", lambda sb, ref: calls["consume"].append(ref))

    def fake_post(url, **kw):
        calls["paystack"].append(kw["json"])
        return _Resp({"status": True, "data": {"authorization_url": "https://pay.example/x"}})
    env.monkeypatch.setattr(env.core.requests, "post", fake_post)
    return calls


def test_quote_is_hidden_while_the_feature_is_off(env):
    env.monkeypatch.setattr(env.core.xera_discount, "load_config", lambda sb: {"enabled": False})
    r = env.client.get("/api/evosgpt/xera-discount/quote?user_id=1&tier=Pro", headers=_hdr(env.core, 1)).json()
    assert r == {"enabled": False}


def test_quote_needs_the_users_own_token(env):
    env.monkeypatch.setattr(env.core.xera_discount, "load_config", lambda sb: {"enabled": True})
    assert env.client.get("/api/evosgpt/xera-discount/quote?user_id=1&tier=Pro", headers=_hdr(env.core, 2)).status_code == 403


def test_toggle_charges_the_discounted_amount_and_holds_xera_under_the_same_reference(env):
    calls = _setup(env, _elig())
    r = env.client.post("/api/evosgpt/upgrade/init", json={"user_id": 1, "tier": "Pro", "email": "a@b.c", "use_xera": True},
                        headers=_hdr(env.core, 1)).json()
    assert r["status"] == "ok" and r["billing_amount"] == 18.0 and r["xera_discount"]["discount_ghs"] == 2.0
    assert calls["paystack"][0]["amount"] == 1800
    assert calls["hold"] == [(1, r["reference"])]
    assert env.db.t["evosgpt_purchases"][0]["reference"] == r["reference"]


def test_without_the_toggle_the_price_is_unchanged_and_no_hold_is_made(env):
    calls = _setup(env, _elig())
    r = env.client.post("/api/evosgpt/upgrade/init", json={"user_id": 1, "tier": "Pro", "email": "a@b.c"},
                        headers=_hdr(env.core, 1)).json()
    assert calls["paystack"][0]["amount"] == 2000 and calls["hold"] == [] and "xera_discount" not in r


def test_not_eligible_is_refused_not_silently_full_price(env):
    q = {"eligible": False, "message": "Earn 20 more XERA to get GH₵ 2 off."}
    calls = _setup(env, q)
    r = env.client.post("/api/evosgpt/upgrade/init", json={"user_id": 1, "tier": "Pro", "email": "a@b.c", "use_xera": True},
                        headers=_hdr(env.core, 1))
    assert r.status_code == 400 and calls["paystack"] == [] and calls["hold"] == []


def test_hold_is_released_if_paystack_fails(env):
    calls = _setup(env, _elig())
    env.monkeypatch.setattr(env.core.requests, "post", lambda *a, **k: _Resp({"status": False, "message": "nope"}))
    r = env.client.post("/api/evosgpt/upgrade/init", json={"user_id": 1, "tier": "Pro", "email": "a@b.c", "use_xera": True},
                        headers=_hdr(env.core, 1))
    assert r.status_code == 400 and len(calls["hold"]) == 1 and calls["release"] == [calls["hold"][0][1]]


def _purchase(env, ref="EVOS-GPT-1-ABCDEF12", tier="Pro"):
    env.db.t.setdefault("evosgpt_purchases", []).append({"user_id": 1, "tier": tier, "reference": ref, "status": "pending"})
    return ref


def test_verify_accepts_the_discounted_amount_and_takes_the_xera(env):
    calls = _setup(env, _elig())
    ref = _purchase(env)
    env.db.t["xera_discount_holds"] = [{"order_ref": ref, "discount_ghs": 2.0}]
    env.monkeypatch.setattr(env.core.requests, "get", lambda *a, **k: _Resp(
        {"status": True, "data": {"status": "success", "currency": "GHS", "amount": 1800}}))
    r = env.client.get(f"/api/evosgpt/upgrade/verify/{ref}", headers=_hdr(env.core, 1)).json()
    assert r["paid"] is True and env.db.t["users"][0]["evosgpt_tier"] == "Pro"
    assert calls["consume"] == [ref]


def test_verify_still_refuses_a_discounted_amount_when_there_is_no_hold(env):
    calls = _setup(env, _elig())
    ref = _purchase(env)
    env.monkeypatch.setattr(env.core.requests, "get", lambda *a, **k: _Resp(
        {"status": True, "data": {"status": "success", "currency": "GHS", "amount": 1800}}))
    assert env.client.get(f"/api/evosgpt/upgrade/verify/{ref}", headers=_hdr(env.core, 1)).json()["paid"] is False
    assert calls["consume"] == [] and env.db.t["users"][0]["evosgpt_tier"] == "Basic"


def test_webhook_payment_also_takes_the_xera(env):
    import hashlib, hmac, json
    calls = _setup(env, _elig())
    ref = _purchase(env)
    body = json.dumps({"event": "charge.success", "data": {"reference": ref, "metadata": {"user_id": 1, "tier": "Pro"}}}).encode()
    sig = hmac.new(b"sk_test", body, hashlib.sha512).hexdigest()
    r = env.client.post("/api/evosgpt/webhook/evosgpt-paystack", content=body, headers={"x-paystack-signature": sig}).json()
    assert r["status"] == "success" and calls["consume"] == [ref]
