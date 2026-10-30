# EVOXERA (XERA) — BNB mainnet runbook

Token: name **EVOXERA**, symbol **XERA**, 18 decimals, fixed supply minted once to the vault. Name and symbol are permanent.
Nothing in this runbook is automatic. Each phase waits for your explicit go.

## 0. Before anything (no cost, no risk)
- [ ] Steps 1 and 2 deployed (claim fixes, `20261030_xera_mainnet_readiness_v1.sql` run BEFORE the backend, token rename).
- [ ] One more small testnet claim succeeds after step 1 (proves nothing regressed).
- [ ] Delete `blockchain/bnb/.env` from the repo; rotate any key that was ever in it.
- [ ] Create **fresh** keys (never reuse testnet keys):
  - Deployer wallet (funded with ~0.05 BNB; holds NO powers after deploy)
  - Claim-signer key (dedicated; its ADDRESS goes into the contract, its private key into backend secret `XERA_CLAIM_SIGNER_PRIVATE_KEY`)
  - Relayer wallet only if you want the admin pilot on mainnet
- [ ] Vault, governance and timelock should be multisig / timelock contracts (e.g. Safe). The script refuses plain wallets unless `XERA_ALLOW_EOA_ADMIN=true`.
- [ ] Confirm name/symbol spelling one last time.

## 1. Environment
Public (safe to show): `XERA_BNB_CHAIN_SUPPLY`, `XERA_MINING_ALLOCATION` (<= 75000000), `XERA_VAULT_MULTISIG_ADDRESS`, `XERA_GOVERNANCE_MULTISIG_ADDRESS`, `XERA_TIMELOCK_ADDRESS`, `XERA_CLAIM_SIGNER_ADDRESS`, `XERA_BNB_CHAIN_ID=56`, `XERA_BNB_CONFIRMATIONS` (default 5).
Secret (never in the repo, chat or frontend): `DEPLOYER_PRIVATE_KEY` (your shell only, for the deploy), `XERA_CLAIM_SIGNER_PRIVATE_KEY` (backend host only), relayer key, any RPC URL containing an API key (`XERA_BNB_RPC_URL`, `BSC_MAINNET_RPC_URL`), `BSCSCAN_API_KEY`, Supabase service key.

## 2. Dry run (sends nothing)
```
cd blockchain/bnb
npx hardhat run scripts/deploy-mainnet.js --network bscMainnet
```
Must print `DRY RUN OK`. Any `PRE-FLIGHT FAILED` line is a reason to stop.

## 3. Deploy (permanent)
```
XERA_MAINNET_BROADCAST=YES_DEPLOY_PERMANENTLY npx hardhat run scripts/deploy-mainnet.js --network bscMainnet
```
The script reads the chain back and checks name, symbol, supply, vault balance, maxAllocation and every role (and that the deployer holds none). It writes `deployments/bscMainnet.json` (public addresses) and refuses to run again while that file exists. If any post-deploy check fails: **do not open claims**.

## 4. Verify on BscScan
Run the three `npx hardhat verify ...` commands the script printed. Confirm on bscscan.com that source is verified, name/symbol/supply are right, and the roles match.

## 5. Multisig follow-ups (from the multisigs, not the deployer)
1. Vault -> transfer the mining allocation (75,000,000 XERA) to the distributor.
2. Governance -> `vesting.grantRole(DEPOSITOR_ROLE, <distributor>)`.

## 6. Wire the app (claims still CLOSED)
1. Supabase `xera_chain_config` BNB row: set the three mainnet addresses; keep `onchain_enabled = false`.
2. Backend env: `XERA_BNB_CHAIN_ID=56`, mainnet `XERA_BNB_RPC_URL`, new `XERA_CLAIM_SIGNER_PRIVATE_KEY`. Redeploy. New claim rows are now stamped `mainnet`; old testnet rows stay `testnet` and can't be reused.
3. Check `/chain/config` returns chain 56 and the mainnet explorer.

## 7. Canary (one wallet, tiny amount)
Use the admin pilot or one internal account: claim the minimum amount. Verify: tx on bscscan, `consumed[referenceId]` true, 25% in the wallet, 75% deposited in vesting, DB row `CONFIRMED` + `mainnet`, global counter increased by exactly that amount, mining sessions unaffected. Only then set `onchain_enabled = true`.

## 8. Rollback / emergency
- Stop new claims instantly: `onchain_enabled = false` (no deploy needed). Unfinished signed claims expire by deadline and release their reservation.
- On-chain: governance multisig pauses the distributor (`pause`). `XeraVesting.release()` is not pause-gated, so already-vested tokens stay withdrawable.
- Suspected signer leak: governance rotates the signer on the distributor, then put the new key in the backend. Old vouchers become invalid.
- Not reversible: tokens already paid out. That is why the canary and `maxAllocation` exist.
- Wrong deployment (e.g. bad address): do not "fix" by redeploying blindly. Stop, keep `deployments/bscMainnet.json`, decide with the multisig holders.

## 9. Go / no-go
Go only if every box is true: fresh keys, multisig vault/governance/timelock, dry run clean, post-deploy checks all passed, contracts verified, distributor funded, depositor role granted, canary clean, you have looked at the BscScan pages yourself.
