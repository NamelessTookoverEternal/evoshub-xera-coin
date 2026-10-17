"""
EVOSGPT Supabase-first routing: native engine, reviewed knowledge, own-history recall, OpenAI fallback,
privacy filtering, retention, failure handling and measured OpenAI savings.

No network. OpenAI is replaced by a counting fake, Supabase by the in-memory FakeDB from conftest.py.
"""
from datetime import datetime, timedelta, timezone

import pytest

GEO = {"country_code": "GH", "local_time": "Saturday, 17 October 2026, 01:03 PM", "timezone": "UTC", "city": "Accra", "country": "Ghana"}


def hdr(core, uid):
    return {"Authorization": f"Bearer {core.make_user_token(uid)}"}


class FakeOpenAI:
    """Replaces core.call_openai: counts calls, records prompts, reports token usage like the real one."""
    def __init__(self, core, reply="Here is a generated answer that is long enough to be a sensible reply."):
        self.core, self.reply, self.calls = core, reply, []

    def __call__(self, model, system, user_msg, history=None):
        self.calls.append({"model": model, "system": system, "user": user_msg, "history": list(history or [])})
        self.core._LAST_USAGE.set({"prompt_tokens": 100, "completion_tokens": 50})
        return self.reply


@pytest.fixture()
def app(env):
    env.monkeypatch.setattr(env.core, "get_geo_context", lambda req: dict(GEO))
    env.ai = FakeOpenAI(env.core)
    env.monkeypatch.setattr(env.core, "call_openai", env.ai)
    for u in env.db.t["users"]:
        u["evosgpt_tier"] = "Pro"        # unlimited daily chats so volume tests are not capped

    def chat(uid, message, **extra):
        r = env.client.post("/api/evosgpt/chat", json={"user_id": uid, "message": message, **extra}, headers=hdr(env.core, uid))
        assert r.status_code == 200, r.text
        return r.json()
    env.chat = chat
    return env


def kb_row(**kw):
    now = datetime.now(timezone.utc).isoformat()
    row = {"id": 1, "question_key": "photosynthesis", "question": "What is photosynthesis?",
           "answer": "Photosynthesis is how plants turn light, water and carbon dioxide into sugar and oxygen.",
           "source": "admin_verified", "status": "approved", "confidence": 0.95, "seen_count": 3,
           "use_count": 0, "conflict_count": 0, "created_at": now, "updated_at": now, "expires_at": None}
    row.update(kw)
    return row


# ------------------------------------------------------------------ 1. native engine, no OpenAI

@pytest.mark.parametrize("msg", ["Hi", "hello there", "Hi, how are you?", "good morning", "thanks!", "bye", "ok cool",
                                 "who are you", "what is EVOSGPT", "what is 15 * 12", "what time is it"])
def test_supported_simple_messages_never_call_openai(app, msg):
    r = app.chat(1, msg)
    assert r["status"] == "ok" and r["source"] == "native" and r["reply"]
    assert app.ai.calls == []


def test_native_replies_are_saved_and_counted(app):
    app.chat(1, "Hi")
    rows = app.db.t["evosgpt_memory"]
    assert [x["role"] for x in rows] == ["user", "assistant"] and all(x["user_id"] == 1 for x in rows)
    assert app.db.t["evosgpt_daily_chats"][0]["count"] == 1          # daily limits still apply to native replies


def test_native_math_and_text_tasks_are_exact(app):
    assert "180" in app.chat(1, "what is 15 * 12")["reply"]
    assert app.chat(1, "word count: the quick brown fox")["reply"] == "That text has 4 words."
    assert app.chat(1, "uppercase: hello world")["reply"] == "HELLO WORLD"
    assert app.ai.calls == []


def test_native_tier_answer_uses_live_config_not_hardcoded_numbers(app):
    app.monkeypatch.setitem(app.core.TIERS["Pro"], "price_ghs", 99)
    assert "GHS 99" in app.chat(1, "what are the plans")["reply"]


def test_verified_facts_only_for_known_entities(app):
    assert app.chat(1, "what is evosdata")["source"] == "native"
    assert app.chat(1, "what is quantum chromodynamics")["source"] == "openai"   # unknown -> never invented


# ------------------------------------------------------------------ 4. complex requests are not handled natively

@pytest.mark.parametrize("msg", [
    "Hi, write me an original essay on climate change",
    "Write an original essay on climate change.",
    "explain why the sky is blue and derive the formula",
    "write a python function to sort a list",
    "help me draft a cover letter",
    "thanks, now translate that into French",
])
def test_complex_requests_go_to_openai(app, msg):
    r = app.chat(1, msg)
    assert r["source"] == "openai" and len(app.ai.calls) == 1


def test_complex_request_ignores_a_close_knowledge_match(app):
    app.db.t["evosgpt_knowledge"] = [kb_row(question="essay climate change", question_key="change climate essay")]
    assert app.chat(1, "Write an original essay on climate change")["source"] == "openai"


# ------------------------------------------------------------------ 2 + 3. reviewed knowledge, with fallback

def test_approved_knowledge_answers_without_openai(app):
    app.db.t["evosgpt_knowledge"] = [kb_row()]
    r = app.chat(1, "What is photosynthesis?")
    assert r["source"] == "knowledge" and "sugar and oxygen" in r["reply"] and app.ai.calls == []
    assert app.db.t["evosgpt_knowledge"][0]["use_count"] == 1


@pytest.mark.parametrize("override", [
    {"status": "pending"}, {"status": "rejected"}, {"confidence": 0.4},
    {"expires_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()},
    {"source": "ai_generated", "updated_at": (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()},
])
def test_unreliable_knowledge_is_not_served(app, override):
    app.db.t["evosgpt_knowledge"] = [kb_row(**override)]
    assert app.chat(1, "What is photosynthesis?")["source"] == "openai"


def test_a_database_hit_is_not_automatically_correct(app):
    app.db.t["evosgpt_knowledge"] = [kb_row()]
    assert app.chat(1, "What is photosynthesis not?")["source"] == "openai"           # negation differs
    app.db.t["evosgpt_knowledge"] = [kb_row(question="Why is 2 apples a pair?", question_key="2 apples pair")]
    assert app.chat(1, "Why is 3 apples a pair?")["source"] == "openai"               # number differs
    app.db.t["evosgpt_knowledge"] = [kb_row()]
    assert app.chat(1, "What is my photosynthesis project?")["source"] == "openai"    # personal context


def test_volatile_questions_are_never_answered_from_knowledge(app):
    app.db.t["evosgpt_knowledge"] = [kb_row(question="What is the latest price of cocoa?", question_key="cocoa latest price")]
    assert app.chat(1, "What is the latest price of cocoa?")["source"] == "openai"


def test_unfamiliar_question_falls_back_to_openai_and_is_saved(app):
    r = app.chat(1, "What is the boiling point of nitrogen?")
    assert r["source"] == "openai" and r["model"] == "gpt-4o" and len(app.ai.calls) == 1
    assert [x["role"] for x in app.db.t["evosgpt_memory"]] == ["user", "assistant"]


# ------------------------------------------------------------------ 5. history saved / retrieved, not deleted

def test_history_is_kept_beyond_the_model_context_window(app):
    app.monkeypatch.setitem(app.core.TIERS["Pro"], "memory_limit", 4)
    for i in range(6):
        app.chat(1, f"What is the boiling point of element number {i + 10}?")
    assert len(app.db.t["evosgpt_memory"]) == 12                    # all kept (the old trim_memory would leave 4)
    assert len(app.ai.calls[-1]["history"]) <= 4                    # ...but the model only gets the recent window


def test_conversation_id_is_stored_when_sent(app):
    app.chat(1, "Hi", conversation_id="conv-7")
    assert {x.get("conversation_id") for x in app.db.t["evosgpt_memory"]} == {"conv-7"}


def test_recall_answers_from_the_users_own_history(app):
    app.chat(1, "I am building a school fees payment app for Kumasi schools")
    n = len(app.ai.calls)
    r = app.chat(1, "What did we discuss about the school fees app?")
    assert r["source"] == "history" and "school fees" in r["reply"] and len(app.ai.calls) == n


def test_recall_never_leaks_another_users_conversation(app):
    app.chat(1, "I am building a school fees payment app for Kumasi schools")
    r = app.chat(2, "What did we discuss about the school fees app?")
    assert r["source"] == "openai" and "Kumasi" not in r["reply"]
    system = app.ai.calls[-1]["system"]
    assert "school fees" not in system and "Kumasi" not in system        # not even injected as context
    assert "can't find it" in system                                      # model is told not to guess


def test_continue_request_uses_openai_with_retrieved_context(app):
    app.chat(1, "I am building a website for my bakery called Sweet Crumbs")
    r = app.chat(1, "Continue the bakery website project we discussed")
    assert r["source"] == "openai"
    assert "Sweet Crumbs" in app.ai.calls[-1]["system"]


def test_recall_with_no_match_falls_back_instead_of_inventing(app):
    assert app.chat(1, "What did we discuss about the harbour project?")["source"] == "openai"


# ------------------------------------------------------------------ 6. personal memory vs shared knowledge

def test_personal_facts_go_to_long_memory_not_shared_knowledge(app):
    app.chat(1, "I am building a school fees payment app for Kumasi schools")
    mem = app.db.t["evosgpt_long_memory"][0]
    assert mem["user_id"] == 1 and "school fees" in mem["summary"]
    assert "school fees" not in str(app.db.t.get("evosgpt_knowledge", []))
    assert not any("user_id" in k for k in app.db.t.get("evosgpt_knowledge", []))


def test_ai_answers_become_pending_candidates_that_are_never_served(app):
    app.chat(1, "What is the boiling point of nitrogen?")
    [cand] = app.db.t["evosgpt_knowledge"]
    assert cand["status"] == "pending" and cand["source"] == "ai_generated" and "user_id" not in cand
    assert app.chat(2, "What is the boiling point of nitrogen?")["source"] == "openai"      # still unreviewed
    cand["status"] = "approved"; cand["confidence"] = 0.9                                    # human review
    assert app.chat(2, "What is the boiling point of nitrogen?")["source"] == "knowledge"


def test_approved_knowledge_is_not_overwritten_and_conflicts_send_it_back_to_review(app):
    from services.evosgpt import knowledge as kb
    app.db.t["evosgpt_knowledge"] = [kb_row(source="ai_generated", question="What is the boiling point of nitrogen?",
                                            question_key=kb.question_key("What is the boiling point of nitrogen?"),
                                            answer="Nitrogen boils at about minus 196 degrees Celsius at normal pressure.")]
    app.ai.reply = "Completely unrelated different statement regarding something else entirely here today."
    for _ in range(3):
        kb.learn_candidate(app.db, "What is the boiling point of nitrogen?", app.ai.reply)
    row = app.db.t["evosgpt_knowledge"][0]
    assert row["answer"].startswith("Nitrogen boils") and row["conflict_count"] == 3 and row["status"] == "pending"


def test_creative_personal_and_volatile_questions_are_not_learned(app):
    for q in ["Write a poem about the sea and the sky", "What is my best career option now?", "What is the weather today in Accra?"]:
        app.chat(1, q)
    assert app.db.t.get("evosgpt_knowledge", []) == []


# ------------------------------------------------------------------ 8. privacy filtering

def test_redaction_covers_common_identifiers():
    from services.evosgpt import privacy
    text = ("Email ama@example.com, call +233 24 123 4567, key sk-abcdefghijklmnopqrstuvwx, my password is hunter2, "
            "card 4111 1111 1111 1111, 12 Liberation Road, GA-123-4567, IP 192.168.1.20, call me Kwame Mensah")
    out, found = privacy.redact(text)
    for leaked in ["ama@example.com", "233 24 123", "sk-abcdefgh", "hunter2", "4111", "Liberation Road", "GA-123-4567", "192.168", "Kwame"]:
        assert leaked not in out, (leaked, out)
    assert {"email", "phone", "openai_key", "secret_assignment", "card", "street_address", "ghana_post", "ip", "self_name"} <= set(found)


def test_luhn_check_avoids_redacting_ordinary_long_numbers():
    from services.evosgpt import privacy
    assert privacy.redact("order 1234567890123456")[0] == "order 1234567890123456"


def test_shared_knowledge_refuses_anything_the_filter_would_change():
    from services.evosgpt import privacy
    assert privacy.sanitize_for_shared("Water boils at 100 degrees Celsius at sea level.") is not None
    assert privacy.sanitize_for_shared("Email the answer to ama@example.com") is None
    assert privacy.sanitize_for_shared("Water boils at 100C. My number is 0244123456 for questions.") is None


def test_secrets_are_never_saved_as_memory_or_knowledge(app):
    app.chat(1, "I am building a payment app and my password is hunter2 and my api key is sk-abcdefghijklmnopqrstuvwx")
    assert app.db.t.get("evosgpt_long_memory", []) == []
    blob = str(app.db.t.get("evosgpt_knowledge", [])) + str(app.db.t.get("evosgpt_long_memory", []))
    assert "hunter2" not in blob and "sk-abcdefgh" not in blob


def test_questions_containing_private_data_are_not_learned_even_redacted(app):
    app.chat(1, "What is the capital of Ghana for the user ama@example.com?")
    assert app.db.t.get("evosgpt_knowledge", []) == []


def test_filter_runs_locally_so_the_raw_message_is_not_sent_for_filtering(app):
    app.chat(1, "My email is ama@example.com, what is the boiling point of nitrogen?")
    assert len(app.ai.calls) == 1                                    # only the answer call; no extra "filter" call


# ------------------------------------------------------------------ 9. Supabase failures

def test_chat_survives_supabase_read_failures(app):
    real = app.db.table

    def flaky(name):
        if name in ("evosgpt_knowledge", "evosgpt_long_memory"):
            raise RuntimeError("supabase down")
        return real(name)
    app.monkeypatch.setattr(app.db, "table", flaky)
    app.monkeypatch.setattr(app.core.db_client, "table", flaky, raising=False)
    r = app.chat(1, "What is the boiling point of nitrogen?")
    assert r["status"] == "ok" and r["source"] == "openai"


def test_reply_is_delivered_even_if_saving_history_fails(app):
    real = app.db.table

    def flaky(name):
        if name == "evosgpt_memory":
            raise RuntimeError("write failed")
        return real(name)
    app.monkeypatch.setattr(app.db, "table", flaky)
    r = app.chat(1, "Hi")
    assert r["status"] == "ok" and r["source"] == "native"


def test_missing_new_tables_do_not_break_chat(app):
    real = app.db.table

    def flaky(name):
        if name in ("evosgpt_knowledge", "evosgpt_usage_events"):
            raise RuntimeError('relation "%s" does not exist' % name)
        return real(name)
    app.monkeypatch.setattr(app.db, "table", flaky)
    assert app.chat(1, "What is the boiling point of nitrogen?")["status"] == "ok"      # migration not run yet
    assert app.chat(1, "Hi")["source"] == "native"


# ------------------------------------------------------------------ 10. compatibility with existing behaviour

def test_daily_limit_still_applies_before_any_routing(app):
    app.db.t["users"][0]["evosgpt_tier"] = "Basic"
    from datetime import date
    app.db.t["evosgpt_daily_chats"] = [{"id": 1, "user_id": 1, "date": date.today().isoformat() if False else datetime.now(timezone.utc).date().isoformat(), "count": 10}]
    r = app.chat(1, "Hi")
    assert r["status"] == "limit_reached" and app.ai.calls == []


def test_response_shape_keeps_the_fields_the_frontend_reads(app):
    r = app.chat(1, "Hi")
    for key in ("status", "reply", "tier", "model", "today_count", "day_limit", "show_upgrade_nudge", "location"):
        assert key in r


def test_images_always_go_to_openai(app):
    r = app.chat(1, "Hi", image_base64="aGVsbG8=", image_mime="image/png")
    assert r["source"] == "openai" and len(app.ai.calls) == 1


def test_clear_memory_still_deletes_history_and_long_memory(app):
    app.chat(1, "I am building a school fees payment app for Kumasi schools")
    assert app.client.delete("/api/evosgpt/memory/1", headers=hdr(app.core, 1)).status_code == 200
    assert not [r for r in app.db.t["evosgpt_memory"] if r["user_id"] == 1]
    assert not app.db.t.get("evosgpt_long_memory")


# ------------------------------------------------------------------ retention policy

def test_retention_prunes_only_past_policy_and_only_that_user(app):
    from services.evosgpt import knowledge as kb
    old = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
    new = datetime.now(timezone.utc).isoformat()
    app.db.t["evosgpt_memory"] = (
        [{"id": i, "user_id": 1, "role": "user", "content": "x", "created_at": old} for i in range(1, 4)]
        + [{"id": 10 + i, "user_id": 1, "role": "user", "content": "y", "created_at": new} for i in range(5)]
        + [{"id": 30, "user_id": 2, "role": "user", "content": "z", "created_at": old}])
    kb.apply_retention(app.db, 1, retention_days=365, max_rows=4)
    mine = [r for r in app.db.t["evosgpt_memory"] if r["user_id"] == 1]
    assert len(mine) == 4 and all(r["created_at"] == new for r in mine)
    assert len([r for r in app.db.t["evosgpt_memory"] if r["user_id"] == 2]) == 1


def test_trim_memory_no_longer_deletes_history(app):
    for i in range(6):
        app.core.save_message(1, "user", f"m{i}")
    app.core.trim_memory(1, 2)
    assert len(app.db.t["evosgpt_memory"]) == 6


# ------------------------------------------------------------------ 11. measurable OpenAI reduction

def test_mixed_traffic_reduces_openai_calls_and_is_measured(app):
    app.db.t["evosgpt_knowledge"] = [kb_row()]
    simple = ["Hi", "how are you", "what is 7 + 5", "who are you", "thanks", "What is photosynthesis?", "bye", "what is evosgpt"]
    complex_ = ["Write an essay on cocoa farming in Ghana", "What is the boiling point of nitrogen?", "Debug this python function for me"]
    for m in simple + complex_:
        app.chat(1, m)
    total = len(simple) + len(complex_)
    assert len(app.ai.calls) == len(complex_)                    # old behaviour: one OpenAI call per chat (== total)
    assert len(app.ai.calls) < total

    usage = app.client.get("/api/evosgpt/usage/1", headers=hdr(app.core, 1)).json()["usage"]
    assert usage["total_requests"] == total
    assert usage["native"] + usage["knowledge"] == len(simple) and usage["openai_text"] == len(complex_)
    assert usage["memory_maintenance_calls"] == 0
    assert usage["answered_without_openai_pct"] == round(100 * len(simple) / total, 1)
    assert usage["prompt_tokens"] == 100 * len(complex_) and usage["est_cost_usd"] > 0


def test_no_per_message_or_periodic_summary_calls_by_default(app):
    for i in range(25):
        app.chat(1, f"What is the boiling point of element number {i + 20}?")
    assert len(app.ai.calls) == 25                               # and no hidden summarise/merge calls


def test_llm_memory_maintenance_is_opt_in_and_metered(app):
    app.monkeypatch.setattr(app.core, "LLM_MEMORY", True)
    for i in range(12):
        app.chat(1, f"What is the boiling point of element number {i + 20}?")
    assert len(app.ai.calls) > 12
    usage = app.client.get("/api/evosgpt/usage/1", headers=hdr(app.core, 1)).json()["usage"]
    assert usage["memory_maintenance_calls"] >= 1


def test_usage_endpoint_is_private_to_the_user(app):
    assert app.client.get("/api/evosgpt/usage/1").status_code == 403
    assert app.client.get("/api/evosgpt/usage/1", headers=hdr(app.core, 2)).status_code == 403


# ------------------------------------------------------------------ native engine unit tests

def test_native_engine_is_modular_and_conservative():
    from services.evosgpt import native
    assert native.try_native("Hi, write me an essay") is None
    assert native.try_native("hello") is not None
    assert native.classify("thanks") == "thanks"
    assert native.is_complex("write an essay")
    assert native.try_native("something completely unrecognised and vague") is None


def test_native_greetings_vary_but_stay_natural():
    import random
    from services.evosgpt import native
    replies = {native.try_native("hi", username="Ama", rng=random.Random(s)).reply for s in range(20)}
    assert len(replies) > 1 and all("Ama" in r for r in replies)


def test_replies_point_to_in_hub_products_not_standalone_sites(app):
    r = app.chat(1, "where can i buy data")["reply"] + app.chat(1, "what is evosdata")["reply"]
    assert "evoshub.xyz/evosdata" in r and "https://evosdata.xyz" not in r
    app.chat(1, "I'm running low on data, what should I do about it?")
    assert "evoshub.xyz/evosdata" in app.ai.calls[-1]["system"]
