"""
One-time legacy balance snapshot + Merkle tree builder (section 10).

Run ONCE, at the chosen migration cutoff. This script:

  1. Reads every xera_wallets.cached_balance as of "now" (the cutoff)
  2. Writes one frozen row per user into xera_migration_snapshot
     (leaf_index assigned here, sequentially — this is the ONLY place
     leaf_index is ever assigned)
  3. Builds a Merkle tree over (leaf_index, user's linked wallet address,
     legacy_balance) — NOTE: a user must have a VERIFIED external wallet
     for the target chain before they can be included, since the leaf
     commits to a specific claiming address, not a user_id (the contract
     has no notion of user_id, only addresses)
  4. Stores each user's proof back into xera_migration_snapshot.merkle_proof
  5. Writes the root + total into xera_migration_config
  6. Prints the exact constructor arguments for XeraMigrationClaim.sol

This script NEVER runs twice against the same cutoff — it refuses to run
if xera_migration_config.frozen is already true. A second migration, if
ever needed, is a new contract deployment with a new root (see
blockchain/bnb/contracts/XeraMigrationClaim.sol's NatSpec), not a mutation
of this one.

Leaf encoding matches XeraMigrationClaim.claim() exactly:
    leaf = keccak256(keccak256(abi.encode(leafIndex, account, amount)))
    (OpenZeppelin's "sorted pair" convention for internal nodes)

Requires: pip install web3 eth-abi eth-utils supabase
"""

import argparse
import os
import sys

from eth_abi import encode as abi_encode
from eth_utils import keccak, to_checksum_address

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "python"))


def hash_leaf(leaf_index: int, account: str, amount_wei: int) -> bytes:
    inner = keccak(abi_encode(["uint256", "address", "uint256"], [leaf_index, to_checksum_address(account), amount_wei]))
    return keccak(inner)


def hash_pair(a: bytes, b: bytes) -> bytes:
    x, y = (a, b) if int.from_bytes(a, "big") < int.from_bytes(b, "big") else (b, a)
    return keccak(x + y)


def build_tree(leaves: list[bytes]) -> tuple[bytes, list[list[bytes]]]:
    """Returns (root, layers) — layers[0] is the leaf layer."""
    layers = [leaves]
    level = leaves
    while len(level) > 1:
        nxt = []
        for i in range(0, len(level), 2):
            if i + 1 < len(level):
                nxt.append(hash_pair(level[i], level[i + 1]))
            else:
                nxt.append(level[i])
        layers.append(nxt)
        level = nxt
    return level[0], layers


def get_proof(layers: list[list[bytes]], index: int) -> list[bytes]:
    proof = []
    idx = index
    for layer in layers[:-1]:
        pair_idx = idx + 1 if idx % 2 == 0 else idx - 1
        if pair_idx < len(layer):
            proof.append(layer[pair_idx])
        idx //= 2
    return proof


def main():
    parser = argparse.ArgumentParser(description="Build the one-time XERA legacy migration snapshot + Merkle tree.")
    parser.add_argument("--chain", required=True, choices=["BNB", "TON"])
    parser.add_argument("--decimals", type=int, default=18)
    parser.add_argument("--dry-run", action="store_true", help="Print the tree/root without writing to Supabase.")
    args = parser.parse_args()

    # Imported here (not at module top) so --help works without the app's
    # full env being configured.
    from main import supabase  # noqa: E402  (reuses the app's existing Supabase client)

    cfg_res = supabase.table("xera_migration_config").select("*").eq("id", 1).execute()
    if cfg_res.data and cfg_res.data[0].get("finalized"):
        print("REFUSING: xera_migration_config is already finalized. A second migration needs a new contract deployment.")
        sys.exit(1)

    wallets_res = supabase.table("xera_wallets").select("user_id, cached_balance").gt("cached_balance", 0).execute()
    entries = []
    skipped_no_wallet = []

    for row in wallets_res.data or []:
        user_id = row["user_id"]
        addr_res = (
            supabase.table("xera_external_wallets")
            .select("address")
            .eq("user_id", user_id).eq("chain", args.chain).eq("status", "VERIFIED")
            .limit(1).execute()
        )
        if not addr_res.data:
            skipped_no_wallet.append(user_id)
            continue
        amount_wei = int(round(float(row["cached_balance"]) * (10 ** args.decimals)))
        entries.append({"user_id": user_id, "address": addr_res.data[0]["address"], "amount_wei": amount_wei,
                         "legacy_balance": row["cached_balance"]})

    if skipped_no_wallet:
        print(f"WARNING: {len(skipped_no_wallet)} users have a legacy balance but no VERIFIED {args.chain} wallet — "
              f"excluded from this snapshot (their balance is NOT lost, they just can't be included until they link a "
              f"wallet; re-run before finalizing if you want to wait for them).")

    entries.sort(key=lambda e: e["user_id"])  # deterministic leaf_index assignment
    for i, e in enumerate(entries):
        e["leaf_index"] = i

    leaves = [hash_leaf(e["leaf_index"], e["address"], e["amount_wei"]) for e in entries]
    if not leaves:
        print("No eligible entries — nothing to build.")
        sys.exit(1)

    root, layers = build_tree(leaves)
    total_wei = sum(e["amount_wei"] for e in entries)

    print(f"Entries: {len(entries)}")
    print(f"Merkle root: 0x{root.hex()}")
    print(f"Total snapshot amount (wei): {total_wei}")
    print(f"Total snapshot amount (tokens): {total_wei / (10 ** args.decimals)}")
    print("\nXeraMigrationClaim constructor args:")
    print(f"  merkleRoot_          = 0x{root.hex()}")
    print(f"  totalSnapshotAmount_ = {total_wei}")

    if args.dry_run:
        print("\n--dry-run: not writing to Supabase.")
        return

    for e in entries:
        proof = get_proof(layers, e["leaf_index"])
        supabase.table("xera_migration_snapshot").upsert({
            "leaf_index": e["leaf_index"],
            "user_id": e["user_id"],
            "legacy_balance": e["legacy_balance"],
            "merkle_proof": ["0x" + p.hex() for p in proof],
        }, on_conflict="user_id").execute()

    supabase.table("xera_migration_config").update({
        "merkle_root": "0x" + root.hex(),
        "total_snapshot_amount": total_wei / (10 ** args.decimals),
        "chain": args.chain,
        "cutoff_at": "now()",
        "generated_at": "now()",
        "finalized": False,  # set true manually only after the contract is deployed with this exact root
    }).eq("id", 1).execute()

    print("\nWrote snapshot + proofs to Supabase. xera_migration_config.finalized is still FALSE — "
          "set it to true only after XeraMigrationClaim is deployed with the root printed above.")


if __name__ == "__main__":
    main()
