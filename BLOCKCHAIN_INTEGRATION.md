# XERA Blockchain Integration — Implementation Report

Settlement/ownership layer built on top of the existing Supabase mining
system. Nothing in `mining.py`, `daily.py`, the mining RPCs, or
`xera_wallets.cached_balance` semantics was touched — Supabase remains the
sole source of truth for how much XERA a user has earned. This layer only
adds: (1) a way to settle a finalized entitlement on BNB or TON, and (2) a
one-time legacy-balance migration.

## 1. Approved chain supply split

The current approved aggregate XERA supply split is:

- BNB Smart Chain = 400,000,000 XERA
- TON = 100,000,000 XERA
- Combined = 500,000,000 XERA

BNB is the active initial production chain. TON remains in the repository
for future activation and is currently disabled in the user-facing
frontend as "Coming Soon".

## 2. Contract architecture

```
BNB (blockchain/bnb/contracts/)
├── XeraToken.sol              — fixed-supply BEP-20, standard, no restrictions
├── XeraMiningDistributor.sol  — EIP-712 signed claims, 25/75 split, mining cap
├── XeraVesting.sol            — per-claim linear-vesting tranches (75% leg)
└── XeraMigrationClaim.sol     — one-time Merkle legacy-balance claim

TON (blockchain/ton/contracts/)
├── jetton_minter.tact         — XeraJettonMinter (TEP-74 master)
├── jetton_wallet.tact         — XeraJettonWallet (TEP-74 wallet, unmodified)
├── mining_distributor.tact    — XeraMiningDistributor (Ed25519 signed claims)
├── vesting.tact               — XeraVesting (per-referenceId tranches)
└── messages.tact               — shared message/struct definitions
```

### Contract responsibilities

| Contract | Responsibility | Explicitly does NOT do |
|---|---|---|
| `XeraToken` | Mint fixed supply once, standard ERC20/BEP-20 transfers | Has no mint function; no concept of "locked" |
| `XeraMiningDistributor` (BNB+TON) | Verify signed entitlement, split 25/75, forward locked leg to vesting, enforce mining cap | Never calculates mining rates/allocation — trusts Supabase's finalized amount, authenticated only via the ClaimSigner's signature |
| `XeraVesting` (BNB+TON) | Hold the 75% leg, release linearly per-tranche | Cannot be paused for existing tranches — only new deposits |
| `XeraMigrationClaim` (BNB) | One-time Merkle claim of frozen legacy balances | No mechanism to add leaves after deployment; separate identifier space (`leafIndex`) from mining's `reference_id` |

## 3. Token supply configuration

```
Total XERA           = 500,000,000  (constant, both chains combined)
BNB chain supply     = <BLOCKED — see section 1>
TON chain supply     = <BLOCKED — see section 1>
BNB + TON            = 500,000,000  (must hold exactly)
```

## 4. Public / EVOXERA allocation

Unchanged from `XERA-smart-contract-architecture.md`'s approved Model A —
this integration does not re-litigate it, it only implements the
mechanism to move tokens per that model:

```
Public    = 425,000,000  (Mining 75M + Sale 125M + Community 25M + Liquidity 75M + Treasury-public 125M)
EVOXERA   = 75,000,000   (Treasury-operational)
```

`XeraToken`'s entire fixed supply mints to a single vault multisig at
deployment; that multisig then transfers out to Mining/Sale/Community/
Liquidity/Treasury addresses per this split. The token contract has no
notion of allocation buckets — enforcing the split is a multisig
operational step, documented in `blockchain/bnb/scripts/deploy.js`'s
printed follow-up instructions.

## 5. Mining cap configuration

`XeraMiningDistributor.maxAllocation` = 75,000,000 XERA (18 decimals),
passed at deployment, enforced independently on-chain
(`totalDistributed + amount <= maxAllocation`) — on top of, not instead
of, Supabase's own mining allocation enforcement.

## 6. 25/75 claim implementation

`XeraMiningDistributor.claim()`: `TRANSFERABLE_BPS = 2500`,
`LOCKED_BPS = 7500` (basis points, on-chain constants, not buried
arithmetic). 25% transfers directly to the user; 75% is forwarded to
`XeraVesting.deposit()` in the same transaction (BNB) or the same claim
flow via an async Jetton transfer + forward payload (TON).

## 7. Vesting schedule implemented

Linear vesting, one independent tranche per mining claim (keyed by
`reference_id`), default duration **180 days** (matches the 6-month
launch/mining phase). Governance can adjust `vestingDuration` for future
tranches only — never retroactively reshapes a tranche already created.
`release()` (BNB) / `ReleaseOne` (TON) is never gated by the admin pause
flag; only new deposits are pausable.

## 8. BNB configuration

- Solidity 0.8.24, OpenZeppelin **5.0.2 pinned** (not `^5.0.2`) — newer OZ
  versions use the `mcopy` opcode (Cancun-only) in a transitively-imported
  utility; pinning avoids an assumption about BSC's EVM-version support
  that hasn't been verified.
- Roles: `CLAIM_SIGNER_ROLE` (backend signer, only signs), `GOVERNANCE_ROLE`
  (multisig/timelock — pause, signer rotation, vesting duration),
  `DEFAULT_ADMIN_ROLE` (role management only).
- EIP-712 domain: `name="XeraMiningDistributor", version="1"`, chain ID +
  contract address bind every signature to one chain and one contract.

## 9. TON configuration

- Tact 1.6.13 (compiled and verified in this repo — see section 12).
- Ed25519 signatures (TON has no EIP-712 equivalent) over
  `sha256(opcode ‖ queryId ‖ user ‖ amount ‖ referenceId ‖ deadline)`.
  **This exact byte layout is a bespoke format with no external standard
  to check it against** — flagged as an open item in
  `blockchain/ton/README.md` and in `xera.chain.claims.sign_claim()`
  (TON branch deliberately raises `ton_claim_signing_not_yet_wired` rather
  than implementing against an unreviewed format).
- Admin should be a TON multisig before mainnet (see TON README).

## 10. Database migrations

`supabase/migrations/20260912_xera_blockchain_v1.sql` (additive only):

- `xera_external_wallets` — verified wallet per (user, chain); partial
  unique index enforces one active verified wallet per chain per user
- `xera_wallet_link_nonces` — single-use nonce challenges (BNB sig / TON proof)
- `xera_wallet_change_cooldowns` — cooldown enforcement on wallet replacement
- `xera_onchain_claims` — one row per claim reservation; **the unique index
  on `reference_id` for active (`SIGNED`/`SUBMITTED`/`CONFIRMED`) rows is
  the actual cross-chain double-claim guard** — a reference_id can be
  reserved on exactly one chain, ever
- `xera_migration_snapshot` — one-time frozen legacy balances + Merkle proofs
- `xera_migration_config` — singleton describing the snapshot/root
- `xera_chain_config` — deployed contract addresses per chain
- RPCs: `xera_reserve_onchain_claim` (atomic, `FOR UPDATE`-locked reservation),
  `xera_confirm_onchain_claim`, `xera_link_external_wallet` (atomic
  cooldown + replace), `xera_claim_legacy_migration`
- `xera_onchain_reconciliation_report` — read-only view cross-checking
  confirmed on-chain claims against the mining ledger (admin review only,
  never auto-corrects — same pattern as the existing mining reconciliation)

## 11. API endpoints

All under `/api/xera/` (`python/xera/routes_chain.py`, mounted in `main.py`):

```
POST /wallet/link/nonce            — issue a nonce/ton_proof payload
POST /wallet/link/verify           — verify signature/proof, link wallet
GET  /wallet/linked                — list the user's linked wallets
POST /claim/sign                   — reserve + sign a mining entitlement
POST /claim/confirm                — independently verify + record settlement
GET  /onchain/status                — linked wallet + vesting status (display)
GET  /migration/status              — legacy snapshot status
POST /migration/claim/prepare       — leaf/proof for a legacy claim
POST /migration/claim/confirm       — verify + record a legacy claim
```

`claim/sign` never transfers tokens; it authenticates the user, checks the
entitlement against `xera_transactions`, checks a verified wallet exists,
atomically reserves the `reference_id` for exactly one chain, and returns
a signature. `claim/confirm` independently verifies the on-chain
transaction/event via `xera.chain.onchain_indexer` — it never trusts a
client-submitted hash at face value.

## 12. Frontend changes

New "Blockchain" tab in `hub-frontend/src/pages/xera/index.html` (wallet
connect for BNB/TON, claimable entitlements list with a chain selector,
vesting status, legacy migration claim, settlement history) driven by the
new `hub-frontend/src/js/xera-chain.js` module — the existing mining/
wallet/daily-claim UI and code paths are untouched. CSS additions are
scoped to new `.chain-*` classes in `hub-frontend/src/css/xera.css`.

BNB wallet connect uses `window.ethereum` (MetaMask-style, no new bundle
dependency); on-chain transaction submission uses `ethers` if already
loaded on the page. TON wallet connect expects the TonConnect UI SDK to be
loaded via a script tag (not bundled here) — documented in the JS file.

## 13. Test results

**Backend (Python/pytest)** — `cd python && python3 -m pytest`:
**22 passed**, 0 failed. Covers: EIP-712 signature generation/recovery
against the exact Solidity typehash, contract/chain-ID binding, BNB nonce
signature verification (valid/wrong-signer/tampered-nonce/garbage), TON
Ed25519 proof verification (valid/wrong-key/tampered-payload/malformed
address), wallet linking + reuse + cooldown enforcement, claim signing
with real 25/75 math, cross-chain reservation collision, missing-wallet
and unknown-entitlement rejection, onchain-disabled flag, and
claim-ownership mismatch on confirm.

**BNB contracts (Solidity)** — the Solidity sources and full Hardhat test
suite are present. In the current review environment the checked-in
`node_modules` is incomplete, so Hardhat/solc could not actually be
executed. The test suite therefore remains **NOT RUN in this environment**.
Run it in a complete Node environment with:
`cd blockchain/bnb && npm install && npx hardhat test`.

**TON contracts (Tact)** — all 4 contracts **compile successfully** with
`@tact-lang/compiler` 1.6.13; build artifacts (`.boc`, `.abi`, `.ts`
bindings) are checked in under `blockchain/ton/build/`. No test suite
exists yet for the TON side — `blockchain/ton/README.md` documents exactly
what's required (Blueprint/sandbox) before testnet.

**Cross-implementation validation**: the Merkle tree builder
(`blockchain/bnb/migration_snapshot/build_tree.py`) and the JS test helper
(`blockchain/bnb/test/helpers/merkle.js`) were run against the same input
and produce **byte-identical roots and proofs** — strong independent
confirmation that both match `XeraMigrationClaim.sol`'s leaf encoding.

## 14. Security findings / notes

- Pinned OpenZeppelin to 5.0.2 to avoid an unverified assumption about
  BSC's Cancun-opcode (`mcopy`) support — see section 8.
- `XeraMiningDistributor.rescueForeignToken` explicitly excludes the XERA
  token itself, so it can never become a disguised withdrawal path for
  claim funds.
- No contract has a mint function reachable after deployment on either
  chain (BNB: none exists at all; TON: `Mint` is capped by
  `mintableSupply` and `admin` is designed to be transferred away after
  TGE).
- The actual cross-chain double-claim guard lives in Postgres (a unique
  index + `FOR UPDATE` lock in `xera_reserve_onchain_claim`), not in
  either chain's contract — each chain's own `consumed`/`referenceId`
  mapping is a second, independent layer, not the primary guarantee. This
  is architecturally necessary (neither chain can observe the other) but
  means the backend's reservation step is on the critical security path;
  it should be code-reviewed with that in mind.
- **TON claim signature format is unreviewed** — do not wire up TON claim
  signing in production until this gets a second pair of eyes (see
  section 9).
- Static analysis (Slither/Mythril for Solidity) was not run in this
  sandbox (no network access to install them) — run before mainnet.

## 15. Remaining blockers / follow-ups

1. **BNB/TON supply split decision** (section 1) — hard blocker for mainnet prep.
2. TON claim signature format needs independent review (section 9).
3. Hardhat test suite needs to actually be executed in an environment with
   full network access (`npm install && npx hardhat test`) — written and
   manually reviewed, not yet run.
4. TON test suite (Blueprint/sandbox) doesn't exist yet — see TON README.
5. Multisig/timelock addresses for `GOVERNANCE_ROLE`/`admin` need to be
   deployed before mainnet — this integration assumes they exist and takes
   them as constructor arguments, but doesn't deploy them itself.
6. Static analysis tooling (Slither, Mythril) not run.
7. `GET /onchain/status` and the frontend's claim history currently reuse
   the existing transactions endpoint rather than a dedicated paginated
   `xera_onchain_claims` listing — fine at current volume, worth revisiting.

## 16. Testnet deployment instructions

```bash
cd blockchain/bnb
npm install
cp .env.example .env   # fill in every value — script refuses to run with any missing
npm run deploy:testnet
# Follow the printed instructions: fund the distributor from the vault
# multisig, grant DEPOSITOR_ROLE on XeraVesting to the distributor address.
```

```bash
cd blockchain/ton
npm install
npm run build
# Deploy via Blueprint (npx blueprint run) once wrappers/ exists — see TON README.
```

Then populate `xera_chain_config` in Supabase with the deployed addresses
for `chain='BNB'` (and `'TON'` once deployed) and set `onchain_enabled = true`.

## 17. Mainnet deployment checklist

- [ ] BNB/TON supply split decided and both `.env` files updated
- [ ] Vault, governance, and EVOXERA-allocation multisigs deployed and addresses confirmed
- [ ] TON claim signature format independently reviewed
- [ ] Hardhat test suite run and passing in CI (not just this sandbox's offline compile check)
- [ ] TON test suite written and passing
- [ ] Slither/Mythril run on all Solidity contracts, findings resolved
- [ ] Contracts deployed to testnet, full flow (mining → claim → confirm → vesting release) exercised end-to-end by a real user
- [ ] Legacy migration snapshot generated (`migration_snapshot/build_tree.py`), reviewed, and `XeraMigrationClaim` deployed with the resulting root
- [ ] `xera_migration_config.finalized` set to `true` only after the above
- [ ] ClaimSigner key generated and stored per section 7 (never alongside `XERA_TOKEN_SECRET`/`ADMIN_TOKEN_SECRET`)
- [ ] `xera_chain_config` populated for both chains, `onchain_enabled = true`

## 18. Exact environment variables required

**Backend** (`python/.env` or equivalent secret store):
```
XERA_CLAIM_SIGNER_PRIVATE_KEY=      # BNB EIP-712 signer — separate from XERA_TOKEN_SECRET/ADMIN_TOKEN_SECRET
XERA_CLAIM_SIGNER_TON_SEED=         # TON Ed25519 signer seed — separate key from the above
XERA_BNB_RPC_URL=
BNB_CHAIN_ID=97                     # 56 for mainnet
```

**BNB contracts** (`blockchain/bnb/.env`):
```
DEPLOYER_PRIVATE_KEY=
BSC_TESTNET_RPC_URL=
BSC_MAINNET_RPC_URL=
BSCSCAN_API_KEY=
XERA_BNB_CHAIN_SUPPLY=400000000     # BNB allocation
XERA_VAULT_MULTISIG_ADDRESS=
XERA_GOVERNANCE_MULTISIG_ADDRESS=
XERA_TIMELOCK_ADDRESS=
XERA_CLAIM_SIGNER_ADDRESS=          # public address matching XERA_CLAIM_SIGNER_PRIVATE_KEY
XERA_MINING_ALLOCATION=75000000
```

**Supabase** (`xera_chain_config` table, not env vars): deployed contract
addresses per chain, populated after deployment.

---

## Change safety (section 25)

```
FILES CREATED
  blockchain/bnb/contracts/XeraToken.sol
  blockchain/bnb/contracts/XeraMiningDistributor.sol
  blockchain/bnb/contracts/XeraVesting.sol
  blockchain/bnb/contracts/XeraMigrationClaim.sol
  blockchain/bnb/package.json, hardhat.config.js, .env.example
  blockchain/bnb/scripts/deploy.js
  blockchain/bnb/test/*.test.js, test/helpers/merkle.js
  blockchain/bnb/tools/verify_compile_offline.js
  blockchain/bnb/migration_snapshot/build_tree.py
  blockchain/ton/contracts/*.tact
  blockchain/ton/package.json, tact.config.json
  blockchain/ton/README.md
  python/xera/chain/*.py (config, eip712_signer, bnb_verify, ton_verify,
    nonces, wallet_link, onchain_indexer, claims, migration)
  python/xera/routes_chain.py
  python/tests/conftest.py, test_eip712_signer.py, test_bnb_verify.py,
    test_ton_verify.py, test_wallet_link.py, test_claims.py
  python/pytest.ini
  supabase/migrations/20260912_xera_blockchain_v1.sql
  hub-frontend/src/js/xera-chain.js
  BLOCKCHAIN_INTEGRATION.md (this file)

FILES MODIFIED
  python/main.py                — registered xera_chain_router (2-line addition)
  python/requirements.txt       — added web3, eth-account, eth-abi, eth-utils, pynacl
  hub-frontend/src/pages/xera/index.html — added "Blockchain" tab-nav-item + panel, script include
  hub-frontend/src/css/xera.css — added .chain-* classes (additive block)

DATABASE MIGRATIONS CREATED
  20260912_xera_blockchain_v1.sql (see section 10)

CONTRACTS CREATED
  BNB: XeraToken, XeraMiningDistributor, XeraVesting, XeraMigrationClaim
  TON: XeraJettonMinter, XeraJettonWallet, XeraMiningDistributor, XeraVesting

API ROUTES CREATED
  See section 11 (9 endpoints under /api/xera/)

FRONTEND COMPONENTS MODIFIED
  hub-frontend/src/pages/xera/index.html (new tab, additive)
  hub-frontend/src/css/xera.css (new classes, additive)
  hub-frontend/src/js/xera-chain.js (new file)

TESTS CREATED
  22 backend pytest tests (all passing)
  Hardhat test suite for all 4 BNB contracts (written, not executed — see section 13)

Nothing in mining.py, daily.py, routes.py, routes_admin.py, routes_auth.py,
user_auth.py, wallet.py, admin_auth.py, or the existing migrations was
touched. EVOS Data Services, EVOSGPT, TopTVGH, and EVOS Business Hub
components outside XERA were not touched.
```
