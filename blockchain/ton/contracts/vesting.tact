import "@stdlib/deploy";
import "./messages.tact";
import "./jetton_wallet.tact";

// XeraVesting (TON) — mirrors blockchain/bnb/contracts/XeraVesting.sol's
// design: one independent linear-vesting tranche per mining claim, never a
// single re-based running position (see the Solidity version's NatSpec for
// why re-basing per-deposit is the wrong design).
//
// Credits arrive as a standard Jetton credit (JettonTransferNotification)
// from the distributor's own Jetton wallet — see mining_distributor.tact's
// `Claim` handler, "Leg 2". The forwardPayload carries (user, referenceId);
// referenceId doubles as this tranche's map key, so a duplicate credit for
// an already-seen referenceId is rejected outright — belt-and-suspenders on
// top of the distributor's own `consumed` map and the backend's
// cross-chain reservation.
//
// Release model: TON has no dynamic-array message fields the way an EVM
// call can take `uint256[]`, so unlike the BNB `release()` (which sweeps
// every tranche for `msg.sender` in one call), the TON side releases ONE
// tranche per message (`ReleaseOne{ referenceId }`). The frontend/backend
// indexer knows which referenceIds belong to a user (from
// xera_onchain_claims) and sends one message per releasable tranche —
// functionally equivalent, just batched off-chain instead of on-chain.
//
// TWO-PHASE WIRING WITH XeraMiningDistributor (found via
// blockchain/ton/tests/XeraSettlement.integration.spec.ts — an earlier
// version took `distributorOwnerAddress` as an init parameter, which is
// WRONG: it makes this contract's address depend on the distributor's
// jetton-wallet address, while XeraMiningDistributor's own init takes
// THIS contract's address as a parameter, making the distributor's
// address depend on vesting's address. Two contract addresses each
// depending on the other's address is circular and literally
// undeployable — neither contract could ever be created first).
//
// The fix: `distributorOwnerAddress` is NOT part of init/address-
// determining state. It starts as an inert placeholder (self.admin, which
// can never itself be a jetton wallet contract) and `admin` wires the
// real value in AFTER both contracts exist, via `SetDistributorWallet`.
// Deployment order:
//   1. Deploy XeraVesting (placeholder wallet, deposits effectively
//      impossible until wired).
//   2. Deploy XeraMiningDistributor with `vesting` = the address from (1).
//   3. Compute the distributor's own jetton wallet address (derivable
//      once (2)'s address is known).
//   4. admin sends SetDistributorWallet with that address to (1).
struct Tranche {
    owner: Address;
    amount: Int as coins;
    released: Int as coins;
    start: Int as uint64;
    duration: Int as uint64;
}

message ReleaseOne {
    referenceId: Int as uint256;
}

contract XeraVesting with Deployable {
    minter: Address;
    jettonWalletCode: Cell;
    distributorOwnerAddress: Address; // the DISTRIBUTOR CONTRACT'S OWN address (== JettonTransferNotification.sender for a
    // legitimate deposit — see that handler), NOT its Jetton wallet address. Wired post-deployment, NOT an init param — see NatSpec above.
    distributorWalletConfigured: Bool; // extra explicit guard — see receive(JettonTransferNotification)
    admin: Address; // governance/multisig
    vestingDuration: Int as uint64;
    paused: Bool; // blocks new tranches only — NEVER blocks ReleaseOne, see below
    tranches: map<Int, Tranche>; // referenceId -> Tranche
    userLockedTotal: map<Address, Int>; // owner -> sum of (amount - released) across all their tranches

    init(minter: Address, jettonWalletCode: Cell, admin: Address, vestingDurationSeconds: Int) {
        self.minter = minter;
        self.jettonWalletCode = jettonWalletCode;
        self.distributorOwnerAddress = admin; // inert placeholder, see NatSpec
        self.distributorWalletConfigured = false;
        self.admin = admin;
        self.vestingDuration = vestingDurationSeconds;
        self.paused = false;
    }

    // admin-only, one-time-in-practice (callable again only for a
    // deliberate distributor migration — see section 14/deployment docs).
    // Despite the message name (kept for ABI/wire compatibility), the
    // value wired in is the DISTRIBUTOR CONTRACT'S OWN address, not its
    // Jetton wallet address — see distributorOwnerAddress's field comment
    // and the JettonTransferNotification handler below for why.
    receive(msg: SetDistributorWallet) {
        let ctx: Context = context();
        require(ctx.sender == self.admin, "XeraVesting: not admin");
        self.distributorOwnerAddress = msg.newWallet;
        self.distributorWalletConfigured = true;
    }

    receive(msg: JettonTransferNotification) {
        let ctx: Context = context();
        require(self.distributorWalletConfigured, "XeraVesting: distributor wallet not configured yet");

        // TWO separate checks are required here, not one — conflating them
        // is exactly the bug this replaced (see below):
        //
        // 1. ctx.sender must be genuinely OUR OWN Jetton wallet. Without
        //    this, anyone could deploy an arbitrary dummy contract and
        //    send a JettonTransferNotification directly to this contract
        //    with a FORGED `sender` field claiming to be the distributor's
        //    wallet, backed by zero real tokens — creating a fraudulent
        //    vesting tranche out of thin air. contractAddress(initOf ...)
        //    recomputes the one true address our own wallet code+data
        //    would deploy to, so this can't be spoofed.
        // 2. msg.sender (the field TEP-74 notifications carry, filled in
        //    by the SENDING wallet with the original transferring party)
        //    must equal the distributor's wallet specifically — otherwise
        //    any real token holder could deposit into vesting and create
        //    a tranche for themselves.
        //
        // An earlier version checked ONLY `ctx.sender == distributorOwnerAddress`
        // directly, conflating both checks into one that could never be
        // simultaneously correct: ctx.sender for a JettonTransferNotification
        // is ALWAYS the notifying contract's OWN wallet (that's what a
        // wallet-to-owner forward is), never the distributor's wallet
        // address itself — so every legitimate deposit was silently
        // rejected (fail-closed, not a fund-loss bug, but it meant NO TON
        // claim could ever complete its vesting leg). Found via
        // blockchain/ton/tests/XeraSettlement.integration.spec.ts.
        let expectedOwnWallet: Address = self.ownJettonWallet();
        require(ctx.sender == expectedOwnWallet, "XeraVesting: notification not from our own wallet");
        require(msg.sender == self.distributorOwnerAddress, "XeraVesting: unauthorized credit source");
        require(!self.paused, "XeraVesting: deposits paused");

        let fwd: Slice = msg.forwardPayload;
        let user: Address = fwd.loadAddress();
        let referenceId: Int = fwd.loadUint(256);

        require(self.tranches.get(referenceId) == null, "XeraVesting: referenceId already deposited");

        self.tranches.set(referenceId, Tranche{
            owner: user,
            amount: msg.amount,
            released: 0,
            start: now(),
            duration: self.vestingDuration
        });

        let prior: Int = self.lockedOf(user);
        self.userLockedTotal.set(user, prior + msg.amount);
    }

    // NOT gated by `self.paused` — see contract-level NatSpec and the
    // matching BNB XeraVesting.release() comment. An admin pausing new
    // deposits can never freeze a tranche a user is already vesting into.
    // Permissionless by referenceId (anyone can trigger the release
    // transaction), but funds always go to the tranche's recorded owner,
    // never to the caller.
    receive(msg: ReleaseOne) {
        let t: Tranche? = self.tranches.get(msg.referenceId);
        require(t != null, "XeraVesting: unknown referenceId");
        let tranche: Tranche = t!!;

        let amount: Int = self.releasableOf(tranche);
        require(amount > 0, "XeraVesting: nothing to release");

        tranche.released = tranche.released + amount;
        self.tranches.set(msg.referenceId, tranche);

        let prior: Int = self.lockedOf(tranche.owner);
        self.userLockedTotal.set(tranche.owner, prior - amount);

        send(SendParameters{
            to: self.ownJettonWallet(),
            value: 0,
            mode: SendRemainingValue,
            bounce: true,
            body: JettonTransfer{
                queryId: 0,
                amount: amount,
                destination: tranche.owner,
                responseDestination: null,
                customPayload: null,
                forwardTonAmount: 1,
                forwardPayload: emptySlice()
            }.toCell()
        });
    }

    fun releasableOf(t: Tranche): Int {
        let elapsed: Int = now() - t.start;
        let vested: Int = t.amount;
        if (elapsed < t.duration) {
            vested = (t.amount * elapsed) / t.duration;
        }
        if (vested <= t.released) {
            return 0;
        }
        return vested - t.released;
    }

    fun lockedOf(owner: Address): Int {
        let v: Int? = self.userLockedTotal.get(owner);
        if (v == null) {
            return 0;
        }
        return v!!;
    }

    fun ownJettonWallet(): Address {
        return contractAddress(initOf XeraJettonWallet(self.minter, myAddress(), self.jettonWalletCode));
    }

    receive(msg: SetPaused) {
        let ctx: Context = context();
        require(ctx.sender == self.admin, "XeraVesting: not admin");
        self.paused = msg.paused;
    }

    get fun releasable(referenceId: Int): Int {
        let t: Tranche? = self.tranches.get(referenceId);
        if (t == null) {
            return 0;
        }
        return self.releasableOf(t!!);
    }

    get fun locked_remaining(owner: Address): Int {
        return self.lockedOf(owner);
    }

    get fun tranche_of(referenceId: Int): Tranche? {
        return self.tranches.get(referenceId);
    }

    get fun distributor_wallet_configured(): Bool {
        return self.distributorWalletConfigured;
    }
}
