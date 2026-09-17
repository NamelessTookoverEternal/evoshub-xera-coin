# XERA — TON contracts

Standard TEP-74 Jetton implementation plus the settlement layer, mirroring
the BNB contracts in `blockchain/bnb/` (see that directory's contracts for
the more heavily-commented reference design — the TON contracts below
follow the same rules, adapted for TON's async message-passing model).

## Contracts

| File | Purpose |
|---|---|
| `contracts/jetton_minter.tact` | `XeraJettonMinter` — master Jetton contract. Mints once, up to the deployment-configured chain cap (`mintableSupply`), then `admin` is transferred away (to a multisig or burn address) to permanently disable further minting. |
| `contracts/jetton_wallet.tact` | `XeraJettonWallet` — standard, unmodified TEP-74 per-holder wallet. No locking, no restrictions (section 3 of the brief applies here exactly as it does to the BNB `XeraToken`). |
| `contracts/mining_distributor.tact` | `XeraMiningDistributor` — verifies backend-signed claims (Ed25519, since TON has no EIP-712 equivalent), splits 25/75, forwards the locked leg to `XeraVesting` via a Jetton transfer + forward payload. |
| `contracts/vesting.tact` | `XeraVesting` — one independent linear-vesting tranche per `referenceId`, exactly mirroring the BNB `XeraVesting`'s per-claim tranche design. |
| `contracts/messages.tact` | Shared TEP-74 + XERA-specific message/struct definitions. |

## Build

```bash
cd blockchain/ton
npm install
npm run build   # runs `tact --config tact.config.json`
```

This has been run in this repository already — `build/` contains the
compiled `.boc`, `.fif`, `.abi`, and TypeScript binding (`.ts`) output for
all four contracts, confirming they compile cleanly with
`@tact-lang/compiler` 1.6.13. Compiling is not the same as testing — see
"Testing" below for what's still required before testnet deployment.

## Testing

`tests/` and `wrappers/` are scaffolded but not yet written. Section 21 of
the brief requires local contract tests before testnet, and section 20
lists TON-specific cases explicitly (bounced messages, insufficient gas,
message ordering). Use the TON Blueprint framework:

```bash
npm install --save-dev @ton/blueprint @ton/sandbox @ton/test-utils
npx blueprint test
```

Required test coverage (mirrors the Hardhat suite in `blockchain/bnb/test/`
— do not consider TON done until these exist):

- `XeraJettonMinter`: mint up to `mintableSupply` succeeds; mint beyond it
  reverts; only `admin` can mint; `ChangeAdmin` correctly revokes the old
  admin's mint capability; `get_jetton_data()` reports correctly.
- `XeraJettonWallet`: standard TEP-74 transfer/burn behavior; a forged
  `JettonTransferInternal` from a non-minter, non-peer-wallet sender is
  rejected.
- `XeraMiningDistributor`: valid claim settles with exact 25/75 split;
  invalid signature rejected; modified amount/user/referenceId rejected
  (each invalidates the signed hash); expired claim rejected; replayed
  referenceId rejected; mining cap enforced; pause blocks new claims;
  signer rotation works; **bounced-message handling** if the Jetton
  transfer to `myWallet` bounces (TON-specific — has no BNB analogue).
- `XeraVesting`: tranche created correctly on `JettonTransferNotification`;
  duplicate referenceId rejected; `ReleaseOne` respects the linear
  schedule; premature release rejected; pause blocks new tranches but
  never blocks `ReleaseOne`; unauthorized `JettonTransferNotification`
  sender (not the distributor's own wallet) rejected.

## Known open item — TON claim signature format

`messages.tact`'s `Claim` message and `python/xera/chain/claims.py` both
flag this: the backend signs `sha256(opcode ‖ queryId ‖ user ‖ amount ‖
referenceId ‖ deadline)` with Ed25519 and the contract verifies with
`checkSignature()` over the same cell hash. This is implemented and
internally consistent on both sides *as specified here*, but — unlike the
BNB side, which reuses the battle-tested EIP-712 standard — this is a
**bespoke wire format with no external standard to check it against**.
Before mainnet: have this exact byte layout independently reviewed (ideally
by whoever also reviews the Solidity contracts), and wire up
`sign_claim()`'s TON branch in `python/xera/chain/claims.py` (currently
raises `ton_claim_signing_not_yet_wired` — deliberately not implemented
against an unreviewed format).

## Multisig / admin

Per section 14 of the brief: `admin` on `XeraMiningDistributor` and
`XeraVesting` should be a TON multisig, not a single EOA-equivalent key,
before mainnet. TON's ecosystem multisig contracts (e.g. the standard
`multisig.fc` used by major TON wallets) are the recommended vehicle —
deploy one and pass its address as `admin` at contract init.
