# XERA Smart Contract Architecture & Specification
### EVOXERA TECHNOLOGY — Pre-Implementation Review Document

**Status:** Draft for review. No contract code has been written yet, per your instruction in section 14/15. Sections A–E below are the deliverables you asked for; section F (code) does not begin until you sign off on this document — and specifically on the two open decisions flagged in §0.

---

## 0. Decisions this document needs from you before code starts

Everything below is designed to work either way, but two things materially change the contract shapes, so I'm flagging them up front instead of guessing:

1. **Mining reward architecture (§4).** I'm recommending **Option A** — keep mining/claiming in Supabase as the source of truth, add a separate on-chain **distribution/claim** contract funded with exactly 75,000,000 XERA, and let users convert accrued off-chain balance into real on-chain tokens when they choose to. Reasoning is in §4. If you want Option B instead (every claim mints/transfers on-chain immediately), the mining contract spec changes shape — tell me before I write it.
2. **Allocation custody model (§3).** I'm recommending a **single fixed-supply mint at TGE (token generation event) into a multisig-controlled MasterVault**, with allocation "buckets" as internal, governance-adjustable accounting *until* tokens are actually moved out to a purpose contract (mining distributor, acquisition sale, liquidity pool, etc.). This is what lets the 500M cap be permanently fixed on day one while still letting you finalize the split between Sale/Community/Treasury later, per your instruction not to hard-code assumptions prematurely. Once tokens leave the vault into a specific contract, that allocation is committed.

If you're fine with both, say so and I'll move to contracts. If not, tell me what to change first.

---

## A. Architecture Document

### A.1 XERA token architecture (cross-chain)

XERA is **two separate, non-fungible-across-chains tokens that share one brand and one accounting model**:

- A BEP-20 token on BNB Smart Chain
- A Jetton on TON

There is **no native bridge** in this initial build. A BNB XERA token and a TON XERA token are not interchangeable by any contract mechanism — only by a future, explicitly-designed bridge (out of scope here, and not requested). This matters for the supply cap: **the 500,000,000 cap is a global ecosystem cap tracked by Supabase + governance policy, not a single on-chain number**, because no single chain can natively enforce a cap that spans two independent blockchains.

The way this is made safe: you decide, before deployment, how the 500M is *split* between the two chains (e.g. "X% of each allocation bucket is mintable on BNB, Y% on TON," or "some buckets exist only on one chain"). Each chain's contract is then hard-capped at its *own* fixed number, and the two numbers are chosen so they can never sum to more than 500M. Supabase records both chains' contract addresses and caps so the FastAPI layer can always report a truthful combined "circulating supply so far" without ever being the thing that *enforces* the cap — enforcement is always on-chain, per chain.

### A.2 BNB Smart Chain architecture

```
XeraToken (BEP-20, OpenZeppelin ERC20 + AccessControl)
   │  fixed cap, single TGE mint, MINTER_ROLE revoked after mint
   ▼
XeraMasterVault (multisig-owned, e.g. Gnosis Safe)
   │  holds the full 500M-chain-share at TGE; internal bucket accounting
   ├──► XeraMiningDistributor   (funded once with the mining bucket amount)
   ├──► XeraLockVesting         (funded with any bucket that has a lock schedule)
   ├──► XeraAcquisitionSale     (future — funded when Month-4 phase is approved)
   ├──► Liquidity reserve address (multisig-held, no contract needed until LP creation)
   └──► Community / Treasury multisig-held wallets
```

Every arrow above is a **transfer**, not a mint. Nothing downstream of `XeraToken` has minting rights after TGE.

### A.3 TON architecture

TON's token standard (Jetton) is structurally different from BEP-20: there is no single "token contract" holding all balances. Instead:

```
XeraJettonMinter (master contract — supply accounting, holds admin address)
   │  deploys/owns
   ▼
XeraJettonWallet (one per holder, standard TEP-74/TEP-89 Jetton wallet contract)
```

The minter contract is the only thing that can authorize new wallet balances (mint messages), and it is the minter — not a wallet — that we cap and then de-privilege. TON has no native concept of "revoke minting" the way OpenZeppelin's `AccessControl.renounceRole` does; instead, the **admin address on the minter is transferred to the zero/burn address (or a timelocked multisig that structurally cannot call mint)** once TGE is complete. Locking/vesting on TON has no standard equivalent to an ERC20 allowance-based vesting contract, so `XeraLockVesting` on TON is a **custom wrapper contract** that holds Jetton wallet balances on users' behalf and releases them per schedule — this is explicitly called out because it's the single biggest "don't assume BNB and TON work identically" point in this whole spec.

### A.4 Mining architecture — see §4 for the full analysis. Summary of the recommended shape:

```
Supabase (source of truth for accrued-but-unclaimed mining balance)
   │  user requests "move my XERA on-chain"
   ▼
FastAPI issues a signed claim (EIP-712 signature on BNB / equivalent authenticated
   message on TON) authorizing a specific amount, once, per user
   ▼
XeraMiningDistributor.claim(amount, signature) — verifies signature, checks it
   hasn't been used, transfers from its own (pre-funded, 75M-capped) balance
```

The distributor can never send more than it was funded with. It has no mint rights at all.

### A.5 Lock/unlock architecture

A generic vesting-style contract, **not** hard-coded to 25% or any specific ratio:

- Holds a token balance on behalf of many users (or a single bucket, depending on which allocations end up locked)
- Per-user (or per-bucket) unlock schedule stored as data, not code — schedule is set by the multisig **before** tokens become claimable, and the schedule itself is only editable by governance **for balances not yet unlocked**, with every change emitting an event (so it's auditable, never silent)
- `claimUnlocked()` — public function anyone can call for themselves; only ever releases what the schedule says is currently unlocked
- No function exists that lets an admin move a user's locked balance to another address, or credit a user extra balance out of thin air. The only admin-adjustable thing is the *schedule* (when things unlock), never *whether a specific user's recorded balance is correct*.

### A.6 Future acquisition architecture (Month-4, not built yet per your instruction)

A `Pausable`, `ReentrancyGuard`-protected sale contract, funded with exactly 125,000,000 XERA from the vault, that:
- Accepts a specified payment asset (USDT, exact contract address configured, not assumed)
- Computes XERA out at a **rate that is a mutable contract parameter**, not a hard-coded constant — so "1 USDT ≈ 1,000 XERA" is today's intended value but is never baked into the bytecode as a promise
- Enforces a hard cap on total XERA sold (its own funded balance is the cap — same pattern as mining)
- Optionally enforces a per-wallet purchase limit (configurable, off by default until you approve the exact mechanism)
- Explicitly does **not** exist in the first deployment — this section is architecture-only, so that when you do approve it, the shape is already agreed on.

### A.7 Future liquidity architecture

No contract is required for this phase yet. The 75,000,000 liquidity allocation sits in a multisig-held address (or the vault) until a liquidity-provisioning event is explicitly approved. **No price is ever written into `XeraToken` or any other core contract** — price only ever exists as the ratio in a future AMM pool, which is market-determined at the moment liquidity is added, not before.

### A.8 Supabase integration

```
Frontend → FastAPI → Supabase                (existing, unchanged)
                         │
                         ├─ mining_sessions, wallets, claims, users   (existing, unchanged)
                         ├─ NEW: onchain_wallets     (user's linked BNB/TON address, per chain)
                         ├─ NEW: onchain_claims      (signature issued, amount, tx hash, status)
                         ├─ NEW: contract_registry   (chain, contract name, address, cap, admin/multisig address)
                         └─ NEW: onchain_events       (indexed Transfer/Claim/Unlock/etc, for fast reads)

Blockchain RPC / indexer → FastAPI → Supabase (new — a lightweight event listener/indexer
                                                  service that watches the deployed contracts
                                                  and writes confirmed events into Supabase)
```

The critical rule from your spec (§10) is enforced structurally: **Supabase is never the thing that credits real XERA.** A row in `onchain_claims` moving to `status = 'confirmed'` only ever happens *after* the indexer sees the transaction actually confirmed on-chain — Supabase reflects the chain, it never substitutes for it. Any place in the UI that shows an "on-chain balance" reads it from the indexed data (or live RPC call), never from a value FastAPI computed itself.

### A.9 Admin architecture

- **No single EOA (individually-owned wallet) has standing privileged access to anything that can move real supply**, on either chain, after TGE.
- BNB: all vault/distributor/vesting admin functions are gated behind a Gnosis Safe multisig (recommend 3-of-5 initially, signers to be named by you).
- TON: minter admin address is a TON multisig (there are established multisig wallet contracts in the TON ecosystem) rather than a single key.
- Time-sensitive but non-emergency changes (e.g. adjusting the acquisition rate, editing a not-yet-unlocked vesting schedule) go through a **timelock** — proposed, visible on-chain for a delay window, then executable — so nothing privileged happens instantly and invisibly.
- **Pause** functions (acquisition sale, mining distributor) are the one exception allowed to be faster than the timelock, because their entire purpose is emergency response — but pausing can only ever *stop* new transactions, never move or alter existing balances.

---

## B. Contract Specification

### BNB Smart Chain

| Contract | Responsibility | Mint rights |
|---|---|---|
| `XeraToken.sol` | BEP-20-compatible token (OpenZeppelin `ERC20`, `ERC20Permit`, `AccessControl`). Enforces the fixed max supply for this chain's share. Performs exactly one mint call at TGE. | Yes, until revoked post-TGE, then never again. |
| `XeraMasterVault.sol` | Multisig-owned holding contract for the newly-minted supply. Internal bucket accounting (mining/sale/community/liquidity/treasury), reassignable **only for un-disbursed buckets**, every reassignment event-logged. Disburses to purpose contracts via plain transfers. | No |
| `XeraMiningDistributor.sol` | Funded once with the mining bucket. Verifies backend-issued signed claims (EIP-712) and releases XERA from its own balance. Tracks per-user claimed amount to prevent replay. Pausable. | No |
| `XeraLockVesting.sol` | Holds a token balance, tracks per-address (or per-bucket) unlock schedules, releases only what's currently unlocked. Schedule editable pre-unlock by multisig+timelock, fully event-logged. | No |
| `XeraAcquisitionSale.sol` *(future, not built now)* | Funded with the acquisition bucket. Accepts configured payment asset, computes XERA at a mutable rate parameter, enforces its own balance as the hard cap, optional per-wallet limit, pausable, reentrancy-guarded. | No |

### TON

| Contract | Responsibility | Mint rights |
|---|---|---|
| `XeraJettonMinter.fc/.tact` | Master Jetton contract. Tracks total minted supply against the fixed chain-cap. Performs the TGE mint(s) to the vault's Jetton wallet. Admin address transferred to a TON multisig (or burned) after TGE. | Yes, until admin is transferred/burned, then structurally unusable. |
| `XeraJettonWallet.fc/.tact` | Standard per-holder Jetton wallet (TEP-74/89 compliant), deployed per address by the minter on first receipt. | No — this is the standard, unmodified wallet logic. |
| `XeraVaultWallet` | The vault's own Jetton wallet, controlled by the TON multisig, functioning the same custodial role as `XeraMasterVault` on BNB. | No |
| `XeraMiningDistributor.fc/.tact` | TON equivalent of the BNB distributor — funded once, verifies backend-authenticated claim messages, releases from its own Jetton wallet balance. | No |
| `XeraLockVesting.fc/.tact` | Custom vesting wrapper (TON has no standard equivalent) — same behavioral spec as the BNB version. | No |
| `XeraAcquisitionSale.fc/.tact` *(future, not built now)* | Same responsibility as the BNB version, adapted to TON's message/gas model. | No |

**Not built in this phase, on either chain:** the mining-boost contract (§7 — explicitly deferred by you), the acquisition sale contract (§6 — explicitly "do not implement until approved"), and any liquidity-pool contract (§8 — later phase).

---

## C. Security Model — every privileged function

### BNB

| Function | Who can call | Why it exists | Blast radius if compromised | Disabled after launch? |
|---|---|---|---|---|
| `XeraToken.mint()` | `MINTER_ROLE` (assigned to deployer only at construction) | One-time TGE issuance of the fixed supply | Unlimited new supply — the single most dangerous function in the whole system | **Yes — `renounceRole` called immediately after the TGE mint, in the same deployment script, so there is no window where it's callable and forgotten.** |
| `XeraToken.pause()/unpause()` *(if included)* | Multisig | Emergency halt of transfers if a critical bug is found | Could freeze all user transfers | No — kept permanently as an emergency brake, but multisig-gated and expected to be used rarely if ever |
| `XeraMasterVault.reassignBucket()` | Multisig + timelock | Adjust un-disbursed allocation amounts before final tokenomics lock-in, per your §3 instruction | Could shift supply intended for one purpose (e.g. community) to another (e.g. treasury) before it's disbursed | Recommend disabling (or requiring a higher signer threshold) once you confirm tokenomics are final |
| `XeraMasterVault.disburse()` | Multisig | Move a bucket's tokens to its purpose contract (fund the mining distributor, fund the vesting contract, etc.) | Sends real tokens to a contract address — a compromised multisig here is equivalent to a rogue transfer | No — this is the vault's whole job; risk is mitigated by multisig threshold, not by disabling the function |
| `XeraMiningDistributor.setSigner()` | Multisig | Rotate the backend key authorized to issue valid mining claims | A compromised signer could authorize fraudulent claims **up to the distributor's remaining balance** (hard-capped at 75M total, never more) | No — needs to remain rotatable in case the backend signing key is ever compromised |
| `XeraMiningDistributor.pause()` | Multisig (fast path, no timelock) | Stop claims immediately if fraud/exploit is detected | N/A — this is the safety valve | No |
| `XeraLockVesting.setSchedule()` | Multisig + timelock | Finalize the real unlock schedule once tokenomics are confirmed (per §5, not hard-coded to 25%) | Could delay or accelerate unlocks | Recommend restricting to "only for balances not yet unlocked" at the contract level (not just a policy) — i.e., make it structurally impossible to rewrite history |

### TON

| Function | Who can call | Why it exists | Blast radius if compromised | Disabled after launch? |
|---|---|---|---|---|
| `XeraJettonMinter.mint()` | Admin address | TGE issuance | Same as BNB — unlimited new supply | **Yes — admin address transferred to burn/timelocked-multisig immediately post-TGE** |
| `XeraJettonMinter.changeAdmin()` | Current admin | Transfer/rotate admin control (used exactly once, to revoke) | Whoever holds admin can eventually mint if not yet revoked | Effectively self-disables once used for revocation |
| `XeraMiningDistributor.setSigner()` / `pause()` | TON multisig | Same as BNB equivalents | Same bound: distributor's own funded balance | No (rotation/pause stay available), same reasoning as BNB |
| `XeraLockVesting.setSchedule()` | TON multisig + timelock | Same as BNB equivalent | Same | Same recommendation |

**General principle applied everywhere:** the *only* function anywhere in the system capable of creating supply out of nothing is the one-time TGE mint on each chain, and both are irreversibly disabled in the same transaction/script that performs the mint — not as a follow-up step that could be forgotten.

---

## D. Tokenomics Mapping — 500,000,000 XERA

| Allocation | Amount | % of total | Custody until disbursed | Disbursed to | Cap enforcement |
|---|---|---|---|---|---|
| Mining | 75,000,000 | 15% | `XeraMasterVault` (BNB) / vault wallet (TON) | `XeraMiningDistributor` | Distributor funded with exactly this amount, once; has no mint rights; can never pay out more than its own balance |
| Sale / Acquisition | 125,000,000 | 25% | Vault | `XeraAcquisitionSale` (future) | Same pattern — sale contract funded with exactly this amount when the phase is approved |
| Community | 25,000,000 | 5% | Vault | Community-controlled multisig wallet(s), or a dedicated distribution contract if needed later | Fixed transfer amount from vault; no further minting possible |
| Liquidity | 75,000,000 | 15% | Vault | Liquidity-provisioning address, only at the liquidity phase | Fixed transfer amount; no price assumption anywhere in the contracts |
| Treasury | 200,000,000 | 40% | Vault | Treasury multisig | Fixed transfer amount |
| **Total** | **500,000,000** | **100%** | | | **Enforced once, globally, by the fact that the TGE mint call — the only mint call that will ever exist — mints exactly 500,000,000 (split across the two chains per your §A.1 decision) and the minting capability is then permanently revoked.** |

**How this resolves the §3 contradiction** (allocations must stay adjustable pre-launch, but supply must be provably capped): the cap is enforced at the **token contract level** (one mint, then revoked — nothing about the 5-way split matters to this guarantee). The 5-way split is enforced at the **vault level**, which is just internal bookkeeping over a fixed pool of already-minted tokens — so you can freely rebalance Sale vs. Community vs. Treasury numbers right up until the moment the vault actually disburses to a given purpose contract, without ever touching the supply cap itself. Once a bucket is disbursed, it's final — the receiving contract's own balance becomes the new cap for that specific use.

---

## E. Test Plan

### BNB (Hardhat + Foundry, Slither for static analysis)

**Deployment & supply**
- [ ] Deploys with zero initial supply; TGE mint brings supply to exactly the agreed chain-share
- [ ] `MINTER_ROLE` has exactly one holder before revocation, zero holders after
- [ ] Attempting to call `mint()` after revocation reverts, from any address including the original deployer
- [ ] Sum of vault bucket balances equals total minted supply at all times (invariant test)

**Transfers**
- [ ] Standard BEP-20/ERC20 transfer, transferFrom, approve behavior (OpenZeppelin's own test suite as baseline, plus our overrides if any)
- [ ] Transfers respect lock/unlock state where applicable (locked balance cannot move even via `transferFrom`)

**Allocation & mining distributor**
- [ ] Distributor cannot be funded with more than its assigned bucket amount
- [ ] Valid signed claim releases the correct amount exactly once
- [ ] Replayed/duplicate claim signature reverts
- [ ] Claim for more than the distributor's remaining balance reverts (never partial-fills silently)
- [ ] Non-multisig address cannot rotate the signer or pause/unpause
- [ ] Fuzz test: random claim amounts/signatures never allow total distributed to exceed 75,000,000

**Lock/vesting**
- [ ] Unlock schedule releases exactly the scheduled amount at each checkpoint, never early
- [ ] `claimUnlocked()` is safe to call by anyone, repeatedly, without over-releasing
- [ ] Schedule edits revert if attempted on already-unlocked history
- [ ] Admin cannot directly credit/debit a user's recorded balance (function doesn't exist — test asserts the absence, e.g. via interface/selector check)

**Admin & governance**
- [ ] All privileged functions revert when called by a non-multisig address
- [ ] Timelocked functions cannot execute before the delay elapses
- [ ] Pause halts the intended functions and only those; unaffected functions keep working

**Security**
- [ ] Reentrancy: attempted reentrant call during a claim/transfer fails (guard active)
- [ ] Integer edge cases: zero-amount claims, max-uint inputs, rounding in any rate calculation
- [ ] Slither run with zero unresolved high/medium findings before testnet deployment
- [ ] Gas cost benchmarked for `claim()` under realistic batch sizes

### TON (current TON testing tooling — e.g. Blueprint/sandbox)

- [ ] Minter deploys with zero supply; TGE mint brings supply to the agreed chain-share
- [ ] Minter admin is transferred/burned post-TGE; subsequent mint attempts fail
- [ ] Jetton wallet deployment-on-first-receive works per standard
- [ ] Transfers between wallets behave per TEP-74; locked-balance transfers blocked where applicable
- [ ] Distributor claim flow mirrors BNB test cases (replay protection, balance-capped payout, signer rotation, pause)
- [ ] Vesting wrapper mirrors BNB test cases
- [ ] Unauthorized messages to any admin-gated method are rejected
- [ ] Edge cases specific to TON's async message-passing model (bounced messages, insufficient gas for a message, message ordering) are explicitly tested — this is the biggest source of TON-specific bugs and has no BNB analogue

---

## What happens next

I have **not** written any contract code — this document is the review checkpoint you asked for. Once you confirm:

1. Option A vs. B for mining (§0.1)
2. The vault/allocation custody model (§0.2)
3. The BNB/TON supply split for the 500M cap (§A.1)
4. Multisig signer counts/thresholds for BNB and TON

...I'll move to writing `XeraToken.sol` and the TON minter first (the two things everything else depends on), then the supporting contracts, then the Hardhat/Foundry test suite — nothing touching the existing FastAPI/Supabase mining code.
