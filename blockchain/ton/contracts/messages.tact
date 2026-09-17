// Shared message and struct definitions for the TON side of XERA.
// TEP-74 (Jetton standard) messages use their standard opcodes so any
// TEP-74-compliant wallet/indexer recognizes them; XERA-specific messages
// (Claim, Deposit, Release) use opcodes in a separate, clearly-marked range.

// ---- TEP-74 standard jetton messages ----

message(0x178d4519) JettonTransferInternal {
    queryId: Int as uint64;
    amount: Int as coins;
    sender: Address;
    responseDestination: Address?;
    forwardTonAmount: Int as coins;
    forwardPayload: Slice as remaining;
}

message(0x7362d09c) JettonTransferNotification {
    queryId: Int as uint64;
    amount: Int as coins;
    sender: Address;
    forwardPayload: Slice as remaining;
}

message(0xf8a7ea5) JettonTransfer {
    queryId: Int as uint64;
    amount: Int as coins;
    destination: Address;
    responseDestination: Address?;
    customPayload: Cell?;
    forwardTonAmount: Int as coins;
    forwardPayload: Slice as remaining;
}

message(0x595f07bc) JettonBurn {
    queryId: Int as uint64;
    amount: Int as coins;
    responseDestination: Address?;
    customPayload: Cell?;
}

message(0x7bdd97de) JettonBurnNotification {
    queryId: Int as uint64;
    amount: Int as coins;
    sender: Address;
    responseDestination: Address?;
}

message(0xd53276db) TokenExcesses {
    queryId: Int as uint64;
}

message(0xffffffff) JettonTransferError {
    queryId: Int as uint64;
}

struct JettonData {
    totalSupply: Int as coins;
    mintable: Bool;
    adminAddress: Address;
    jettonContent: Cell;
    jettonWalletCode: Cell;
}

struct WalletData {
    balance: Int as coins;
    owner: Address;
    minter: Address;
    jettonWalletCode: Cell;
}

// ---- XERA minter-admin messages (not part of TEP-74) ----

message(0x1000) Mint {
    queryId: Int as uint64;
    receiver: Address;
    amount: Int as coins;
}

message(0x1001) ChangeAdmin {
    newAdmin: Address;
}

// ---- XERA mining-distributor claim message (section 6/7) ----
//
// Mirrors the BNB side's EIP-712 Claim struct conceptually: user, amount,
// referenceId, deadline, all backend-authorized — but TON has no native
// typed-data standard, so the ClaimSigner instead signs the exact byte
// layout of a canonical payload cell (see python/xera/chain/ton_claim_signer.py
// and mining_distributor.tact's Claim handler, which reconstructs and
// hashes that exact same cell: opcode, queryId, user, amount, referenceId,
// deadline, packed together in ONE cell, in that order).
//
// IMPORTANT — this is NOT the same shape as the signed payload: opcode(32)
// + queryId(64) + address(267) + coins(~124 max) + referenceId(256) +
// deadline(64) + a 512-bit Ed25519 signature together exceed a single
// cell's 1023-bit capacity (found by an actual TON-sandbox integration
// test, not by inspection — see blockchain/ton/tests/XeraMiningDistributor.claimSignature.spec.ts).
// So the WIRE message below splits `user`/`amount`/`referenceId`/`deadline`
// into a ref cell (`data`), leaving root-cell room for the inline
// signature; the CONTRACT reconstructs the original flat canonical cell
// from the parsed ref before hashing, so the signed payload — and
// therefore the Python signer's output — is unaffected by this wire split.
struct ClaimData {
    user: Address;
    amount: Int as coins;
    referenceId: Int as uint256; // sha256 of the off-chain reference_id string, see ton_claim_signer.reference_id_to_uint256
    deadline: Int as uint64;
}

message(0x2000) Claim {
    queryId: Int as uint64;
    data: Cell;                    // ClaimData, ref-packed — see struct doc above for why
    signature: Slice as remaining; // Ed25519 signature (512 bits) over the canonical payload cell
}

message(0x2001) RotateSigner {
    newSigner: Int as uint256; // Ed25519 public key
}

message(0x2002) SetPaused {
    paused: Bool;
}

// Two-phase wiring for XeraMiningDistributor <-> XeraVesting (see
// vesting.tact's init NatSpec for why this exists: the two contracts'
// addresses would otherwise depend on each other, which is circular and
// undeployable).
message(0x2003) SetDistributorWallet {
    newWallet: Address;
}

// ---- XERA vesting messages (section 3/4/15) ----
// Deposits into XeraVesting arrive as a standard Jetton credit (a
// JettonTransferNotification whose forwardPayload encodes the user +
// referenceId — see mining_distributor.tact) rather than a bespoke
// message, so the credit and the "who it's for" metadata are atomic:
// there's no separate message that could arrive out of order with, or
// without, the actual token transfer.

message(0x3001) Release {
    queryId: Int as uint64;
}
