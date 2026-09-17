# XERA Blockchain — Hardening Status

**Status: NOT READY FOR MAINNET. Local/CI test coverage is now solid —
see section 6 for exactly what's still required before testnet.**

Every result below was actually executed in this repository, not just
written. Where something is unverified, it says so explicitly.

---

## 1. Verified test results

| Suite | Result | What it proves |
|---|---|---|
| BNB Hardhat contracts | **30/30 passing** | Token supply, 25/75 split, EIP-712 signing, replay/cap/pause/role controls, vesting math, Merkle migration |
| Backend pytest | **33/33 passing** | EIP-712 + TON signers, wallet-link verification, claim reservation, error mapping |
| Supabase SQL (real Postgres 16) | **16/16 assertions** | Global 75M cap, claim state machine, retry-without-replay, nonce binding |
| Supabase concurrency (real parallel sessions) | **2/2 passing** | Cap and nonce races both serialize correctly |
| Supabase privilege model | **7/7 passing** | anon/authenticated can't reach tables or RPCs; service_role can |
| TON claim-signature cross-verification | **4/4 passing** | Python-produced signature accepted by the real compiled Tact contract |
| TON settlement integration | **9/9 passing** | **Full mint → claim → 25/75 split → vesting tranche flow, end to end, for real** |

**92 total passing checks across four independent test runners.**

---

## 2. Real bugs found and fixed

Six distinct bugs this session, every one invisible to the Tact/Solidity
compilers — all of them were only found by actually executing a
transaction, not by reading the code.

### 2.1 TON claims could never settle (critical, fixed)

`mining_distributor.tact` mixed `SendPayGasSeparately` (leg 1, explicit
value) with `SendRemainingValue` (leg 2). Confirmed failing identically at
0.5, 1, and 2 TON attached — not a gas-tuning issue, a structural one.
Fixed: both legs now use explicit values. No funds were ever at risk
(action-phase abort rolls back the whole transaction), but zero TON claims
could ever have succeeded before this fix.

### 2.2 Mint credited a zero balance (critical, fixed)

Same root cause as 2.1, in `jetton_wallet.tact`'s `JettonTransferInternal`
handler: a fixed-value notification send followed by a
`SendRemainingValue` excess-refund send. Fixed by giving the excess refund
an explicit fixed value instead.

### 2.3 XeraMiningDistributor and XeraVesting had circular addresses (critical, fixed)

Each contract took the other's address as an init parameter — since a
TON contract's address is derived from its initial code+data, this made
each contract's address depend on the other's, which is circular and
**literally undeployable**. Fixed with two-phase wiring: `XeraVesting`
now deploys with a placeholder and an admin-only `SetDistributorWallet`
message sets the real value once both contracts exist.

### 2.4 Vesting checked the wrong field for the distributor's identity (critical, fixed)

`XeraVesting`'s deposit handler compared `ctx.sender` (which for a
`JettonTransferNotification` is *always* the vesting contract's own
wallet) against the distributor's address — a comparison that could
**never** pass. Every legitimate deposit was silently rejected
(fail-closed, not a fund-loss bug, but it meant the vesting leg of every
TON claim was structurally broken). Fixed by checking `ctx.sender` against
vesting's own recomputed wallet address (forgery protection) **and**
`msg.sender` against the distributor's contract address (correct identity
check) — both are required; checking only one either rejects everything or
opens a forgery hole (see the fix's own commentary for why).

### 2.5 Forward payload was silently discarded (critical, fixed)

`jetton_wallet.tact`'s `JettonTransferInternal` handler hardcoded
`forwardPayload: emptySlice()` in its outgoing notification instead of
propagating the incoming payload — so the distributor's `(user,
referenceId)` data for vesting never arrived, and vesting's parser
Cell-underflowed trying to read fields from nothing. Fixed by propagating
`msg.forwardPayload` through unchanged.

### 2.6 Supabase RPCs were callable by anon (critical, fixed)

`REVOKE EXECUTE ... FROM anon, authenticated` does nothing, because
Postgres grants `EXECUTE` to `PUBLIC` by default and both roles inherit
through it. Before the fix, an anon-key holder could call
`xera_reserve_onchain_claim` or `xera_link_external_wallet` for **any**
user_id via PostgREST, bypassing every FastAPI authorization check. Fixed
with `REVOKE ... FROM PUBLIC`; verified both attacks now fail.

### 2.7 TON `Claim` message exceeded the cell size limit (fixed)

opcode + queryId + address + coins + referenceId + deadline + a 512-bit
signature exceeds a TON cell's 1023-bit capacity. Fixed by moving the
claim fields into a ref cell; the *signed payload* is unchanged.

### 2.8 Wallet-link nonce had a TOCTOU race (fixed)

`consume_nonce` did SELECT-then-UPDATE, so two concurrent requests with
the same nonce could both pass. Replaced with a single atomic conditional
UPDATE. Verified with two genuinely parallel sessions: exactly one wins.

---

## 3. Known gaps (not bugs — absent work)

* **TON confirmation indexer** (`verify_ton_claim_tx`) is written but has
  never run against a live TON RPC. No network path in the build
  environment.
* **Phase 11 TON vesting edge cases beyond the happy path** — no tests yet
  for release at the halfway point, at exact completion, repeated
  release, multiple tranches, malicious notifications, or bounced
  transfers.
* **Bounce handlers** — no `bounced(...)` receiver exists on any TON
  contract. The async-failure test (`XeraSettlement.integration.spec.ts`)
  documents that an under-funded claim safely rolls back with no state
  change, but a settlement leg that bounces *after* being accepted
  on-chain has no recovery path defined.
* **Type safety in TON tests** — the `as any` casts on Tact message
  literals hid the `to`/`receiver` field-name bug during this session
  until it was caught by other means. They should be removed.
* **Static analysis** — Slither/Mythril not run on the Solidity contracts.
* **Deployment manifest** (Phase 14) and **formal report** (Phase 16) not
  written.
* **Multisig/timelock contracts** not deployed; the contracts take their
  addresses as constructor arguments but nothing deploys them.

---

## 4. Canonical configuration

Single source of truth: `blockchain/xera-economics.json`.

```
Total supply            500,000,000 XERA
  BNB chain cap         400,000,000
  TON chain cap         100,000,000   (sum validated by a DB trigger, fails closed)

Ecosystem allocation
  Public                425,000,000
  EVOXERA Technology     75,000,000

Mining allocation        75,000,000   GLOBAL across both chains
Claim split              25% transferable / 75% vested
Vesting duration         180 days
Bridge                   none
```

**The 75M mining cap is global, enforced by a row-locked counter in
Postgres** (`xera_mining_allocation_state`), not by the per-chain contract
caps. Each chain's contract `maxAllocation` is an independent secondary
ceiling — the two do **not** sum to the global cap and must never be read
as if they did.

---

## 5. Running the tests

```bash
# BNB contracts (solc comes from npm; no external download needed)
cd blockchain/bnb && npm install && npx hardhat test

# TON contracts
cd blockchain/ton && npm install && npm run build && npx jest --config jest.config.js

# Backend
cd python && pip install -r requirements.txt && python3 -m pytest

# Supabase — needs a real disposable Postgres; see supabase/tests/README.md
psql -d xera_test -f supabase/tests/test_global_mining_cap.sql
./supabase/tests/run_concurrency_test.sh localhost xera_test postgres
./supabase/tests/run_privilege_test.sh   localhost xera_test postgres
```

`node_modules/` is excluded from the archive — `npm install` restores it.

---

## 6. Before testnet

1. Write the Phase 11 TON vesting edge-case tests (release timing,
   multiple tranches, malicious notifications).
2. Design and implement bounce handling on the TON settlement legs.
3. Remove the `as any` casts from the TON test suites.
4. Run the TON confirmation indexer against a real testnet RPC.
5. Run Slither/Mythril on the Solidity contracts.
6. Deploy the multisig/timelock contracts.
7. Write the Phase 14 deployment manifest and Phase 16 formal report.

Mainnet is further out than testnet, and nothing here should be read as
mainnet-ready.
