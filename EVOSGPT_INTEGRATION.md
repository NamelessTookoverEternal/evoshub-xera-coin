# EVOSGPT inside the Hub

EVOSGPT now runs inside the Hub, the same way EVOS Data does. No outside link, no second backend.

| Piece | Where |
|---|---|
| Backend | `python/services/evosgpt/core.py`, mounted at **`/api/evosgpt`** by `python/routes/evosgpt.py` (called from `main.py`) |
| Currency | `python/services/evosgpt/currency.py`, `GET /api/evosgpt/currency` |
| Frontend | `evosgpt/evosgpt-frontend`, built into `dist/evosgpt` and served at **`/evosgpt`** (`hub-frontend/scripts/build-evosgpt.mjs`) |
| Database | existing `users.evosgpt_tier`, `evosgpt_*` tables, **plus one additive migration** `supabase/migrations/20261017_evosgpt_supabase_first.sql` (see below). Chat keeps working if it hasn't been run yet, it just can't use or learn knowledge or record metrics |
| Tests | `python/tests/evosgpt/` (`test_evosgpt.py`, `test_evosgpt_routing.py`, shared fake in `conftest.py`) |

## Environment variables (Render backend)
| Variable | Needed? | Notes |
|---|---|---|
| `OPENAI_API_KEY` | **Yes** | chat, images, documents. Without it the Hub still boots; chat returns an error |
| `PAYSTACK_SECRET_KEY` | Already set for EVOS Data | EVOSGPT reuses it. Set `EVOSGPT_PAYSTACK_SECRET_KEY` only if EVOSGPT uses a different Paystack account |
| `XERA_TOKEN_SECRET` | Already set | signs the session token EVOSGPT now uses |
| `EVOSGPT_APP_URL` | Optional | default `https://evoshub.xyz/evosgpt`; Paystack returns the customer here |
| `EVOSGPT_ENABLED` | Optional | `false` boots the Hub without EVOSGPT |

`SUPABASE_URL` / `SUPABASE_KEY` / `SUPABASE_ANON_KEY` are no longer needed for EVOSGPT: it uses the Hub's shared Supabase client (same as EVOS Data). Frontend: nothing new, it reuses `VITE_API_BASE_URL`.

## Currency
Default is **GHS**. The visitor's country comes from their IP (a VPN exit country counts), first from the Hub edge (`/api/country`), else from the backend. Prices on the home and upgrade pages and the AI's own answers then use that country's currency.
- Display only: Paystack still bills in GHS, and the page says so.
- Rates come from open.er-api.com, cached 6 hours. If no rate has ever loaded, everyone sees GHS. A price is never invented.

## What changed in behaviour
- **Auth fixed.** The old backend trusted a `user_id` sent by the browser (anyone could read another user's chats or upgrade themselves). Every user route now needs the Hub session token for that same user. Login returns it; a Hub-signed-in visitor is signed in to EVOSGPT automatically.
- Existing sessions on the old site have no token: users sign in once again. Sessions last 24h (Hub rule).
- **Payments.** Upgrades are confirmed with Paystack when the customer returns (`/upgrade/verify`), checking amount and currency, so they work even if the Paystack dashboard webhook points at EVOS Data's URL. The EVOSGPT webhook is **`/api/evosgpt/webhook/evosgpt-paystack`** (its own name, separate from EVOS Data's `/webhook/paystack`; the old `/api/evosgpt/webhook/paystack` still works as an alias). It can no longer grant Founder. Paystack allows one webhook URL per account, so if both products share an account, `/upgrade/verify` is what completes EVOSGPT upgrades.
- Login accepts only plain username/email characters (it was building a filter string from raw input).
- The inline third-party analytics snippet is not in the Hub build (the Hub CSP blocks inline scripts).
- The app hub's EVOSGPT card opens `/evosgpt`.

## Go live
1. Set `OPENAI_API_KEY` on Render, redeploy the backend and the frontend.
2. Check `https://<api>/api/evosgpt/` returns `{"status":"ok", ...}` and `/evosgpt` loads.
3. Keep evosgpt.xyz on the old backend until you are happy, then point/redirect it to `https://evoshub.xyz/evosgpt` (not done here).


---

# Supabase-first chat (native engine, reviewed knowledge, fewer OpenAI calls)

## Request flow (`POST /api/evosgpt/chat`)
1. Hub session token checked for exactly this `user_id` (unchanged). Daily limit checked (unchanged; native/knowledge replies still count as chats).
2. **Native engine** (`services/evosgpt/native.py`): greetings, thanks, farewells, verified EVOSGPT/EVOXERA/EVOS Data/XERA facts, tier info from the live `TIERS` config, simple help, exact arithmetic and a few text tasks. A complexity gate (essay, write, code, explain, translate, ...) always wins, so those never reach the native engine.
2b. **Own-history recall** (`knowledge.py`): "what did we discuss about X / yesterday" is answered from *this user's* `evosgpt_memory` rows only (query is always filtered by `user_id`). A "continue the project we discussed" request still goes to OpenAI, with the retrieved messages injected as context.
3. **Reviewed shared knowledge** (`evosgpt_knowledge`): only `status='approved'`, `confidence >= 0.7`, unexpired, and (for AI-generated rows) younger than 180 days; question similarity >= 0.85 with the same numbers and negations; and the question must be impersonal, non-volatile and non-creative (no "my", "latest", "price", "write", ...).
4. Otherwise **OpenAI** (existing `call_openai`, key stays server-side) with the recent-message window, long-term memory and any retrieved history.
5. Conversation saved (history is **not** deleted to fit a context window). Afterwards, in a background task: the question/answer is offered as a **pending** knowledge candidate (never served until reviewed), deterministic personal facts are merged into `evosgpt_long_memory`, and the retention policy runs now and then.
6. Each chat is recorded in `evosgpt_usage_events` (route, model, tokens when OpenAI reports them, estimated cost).

If Supabase is unreachable (or the new tables don't exist yet) each stage degrades: the read is skipped and the request falls through to OpenAI; a failed save no longer loses the reply.

## Deploy
1. Run `supabase/migrations/20261017_evosgpt_supabase_first.sql` in the shared Supabase SQL editor (idempotent, additive).
2. Redeploy the backend. No frontend change (the response gains a `source` field; `model` is `evosgpt-native` / `evosgpt-knowledge` / `evosgpt-history` for non-OpenAI replies, which the frontend does not read).
3. Review candidates: `SELECT id, question, answer, seen_count FROM evosgpt_knowledge WHERE status='pending' ORDER BY seen_count DESC;` then approve/reject with the `UPDATE` statements at the bottom of the migration.
4. Measure: `SELECT * FROM evosgpt_usage_daily;` (operator view) or `GET /api/evosgpt/usage/{user_id}` (a user's own counts).

## Optional environment variables
| Variable | Default | Meaning |
|---|---|---|
| `EVOSGPT_LLM_MEMORY` | `false` | `true` restores the paid OpenAI summarise-and-merge memory step (now every 5th chat of the day, metered as `memory_maintenance`) |
| `EVOSGPT_RETENTION_DAYS` | `365` | delete a user's history older than this (`0` = keep forever) |
| `EVOSGPT_RETENTION_MAX_ROWS` | `5000` | per-user cap; oldest rows beyond it are pruned |
| `EVOSGPT_KNOWLEDGE_MIN_SIMILARITY` | `0.85` | question match needed to reuse an approved answer |
| `EVOSGPT_KNOWLEDGE_MIN_CONFIDENCE` | `0.7` | minimum reviewed confidence to serve |
| `EVOSGPT_KNOWLEDGE_MAX_AGE_DAYS` | `180` | AI-generated entries older than this are not served |

## Known limitations
- The privacy filter is regex-based and best-effort (it will miss unusual formats, free-text names and indirect identifiers). That is why shared knowledge refuses any text the filter would change, instead of storing a redacted copy, and why nothing AI-generated is served without human review.
- Similarity is word-overlap (no embeddings), so paraphrases of an approved question may still go to OpenAI. Embeddings are a possible later step; they have their own cost.
- Image generation/editing, document generation and the letterhead classifier are not metered yet (they have no `user_id` in scope); only chat and memory-maintenance calls are.
- Knowledge candidates need a human in the SQL editor for now; there is no admin UI.
- Dollar figures are estimates from token counts and a small price table in `knowledge.py`; database and hosting costs are excluded.
