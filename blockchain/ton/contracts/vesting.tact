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
    distributor: Address; // the distributor CONTRACT's address (not its jetton wallet — see receive(JettonTransferNotification) below for why that distinction matters)
    admin: Address; // governance/multisig
    vestingDuration: Int as uint64;
    paused: Bool; // blocks new tranches only — NEVER blocks ReleaseOne, see below
    tranches: map<Int, Tranche>; // referenceId -> Tranche
    userLockedTotal: map<Address, Int>; // owner -> sum of (amount - released) across all their tranches

    init(minter: Address, jettonWalletCode: Cell, distributor: Address, admin: Address, vestingDurationSeconds: Int) {
        self.minter = minter;
        self.jettonWalletCode = jettonWalletCode;
        self.distributor = distributor;
        self.admin = admin;
        self.vestingDuration = vestingDurationSeconds;
        self.paused = false;
    }

    // Authenticating this credit requires checking TWO different things,
    // easy to conflate (an earlier version of this contract checked only
    // `ctx.sender == distributorJettonWallet`, which is simply wrong — see
    // below):
    //
    //   1. `ctx.sender` — the actual TON-level sender of THIS message — is
    //      the physical jetton wallet that sent it. Tracing the real
    //      message flow (Distributor -> Distributor's wallet -> Vesting's
    //      wallet -> Vesting): the JettonTransferNotification we're
    //      handling right now is always sent by OUR OWN jetton wallet
    //      (self.ownJettonWallet()), never by the distributor's wallet —
    //      the distributor's wallet only ever talks to OUR wallet, one
    //      hop earlier. So this must check self.ownJettonWallet(), not
    //      any address belonging to the distributor.
    //
    //   2. `msg.sender` — a field INSIDE the message, TEP-74's record of
    //      who originally initiated the transfer (propagated hop-by-hop
    //      by jetton_wallet.tact as `sender: self.owner` / `sender:
    //      msg.sender`) — this is what actually identifies the
    //      distributor: it will equal the distributor CONTRACT's address,
    //      because that's the `owner` of the wallet that started this
    //      transfer chain. This is the field a forged notification would
    //      need to fake, so it's the one that matters for authorization.
    receive(msg: JettonTransferNotification) {
        let ctx: Context = context();
        require(ctx.sender == self.ownJettonWallet(), "XeraVesting: notification not from our own jetton wallet");
        require(msg.sender == self.distributor, "XeraVesting: credit not from the authorized distributor");
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
                forwardTonAmount: ton("0.01"), // see jetton_minter.tact's Mint handler comment — 1 nanoton aborts the whole action list
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

    // ------------------------------------------------------------------
    // Deployment wiring: XeraVesting's `distributor` field and
    // XeraMiningDistributor's own contract address are mutually
    // referential (the distributor's init takes `vesting: Address`, and
    // correct authentication here requires knowing the distributor's
    // address) — TON/Tact addresses are a pure function of a contract's
    // OWN init data, so there is no init-parameter ordering that lets
    // each contract bake in the other's address up front.
    //
    // Resolved the standard way: deploy XeraVesting first with a
    // deliberately inert placeholder (e.g. the admin's own address, which
    // will never itself send a JettonTransferNotification), deploy
    // XeraMiningDistributor next now that vesting's real address is
    // known, then have admin call SetDistributor with the distributor's
    // real address before any real claim is submitted. Until that call,
    // every deposit attempt fails closed (wrong `msg.sender` check) —
    // there is no window where an incorrect/placeholder wiring is
    // exploitable, only one where it's simply non-functional.
    receive(msg: SetDistributor) {
        let ctx: Context = context();
        require(ctx.sender == self.admin, "XeraVesting: not admin");
        self.distributor = msg.distributor;
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
}
