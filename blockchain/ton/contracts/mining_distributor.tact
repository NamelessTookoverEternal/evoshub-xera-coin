import "@stdlib/deploy";
import "./messages.tact";
import "./jetton_wallet.tact";

// XeraMiningDistributor (TON) — mirrors blockchain/bnb/contracts/
// XeraMiningDistributor.sol conceptually. See messages.tact's `Claim`
// message docstring for the signature-format caveat that's still an open
// joint-spec item before this goes to mainnet.
//
// Section 17 cross-chain protection: this contract only ever sees TON
// state (its own `consumed` map). The actual cross-chain guarantee — a
// reference_id claimed on BNB can never be claimed on TON, and vice versa
// — is enforced by the backend's atomic Supabase reservation
// (xera_reserve_onchain_claim) before it will ever sign a claim for
// either chain. This contract's own `consumed` map is the second,
// independent layer, exactly like the BNB distributor's.
contract XeraMiningDistributor with Deployable {
    minter: Address;
    jettonWalletCode: Cell;
    vesting: Address;
    signerPublicKey: Int as uint256;
    admin: Address; // governance/multisig — rotates signer, pauses
    maxAllocation: Int as coins;
    totalDistributed: Int as coins;
    paused: Bool;
    consumed: map<Int, Bool>; // referenceId -> consumed

    init(minter: Address, jettonWalletCode: Cell, vesting: Address, signerPublicKey: Int, admin: Address, maxAllocation: Int) {
        self.minter = minter;
        self.jettonWalletCode = jettonWalletCode;
        self.vesting = vesting;
        self.signerPublicKey = signerPublicKey;
        self.admin = admin;
        self.maxAllocation = maxAllocation;
        self.totalDistributed = 0;
        self.paused = false;
    }

    // ------------------------------------------------------------------
    // Async settlement failure model (item 6 of the hardening brief).
    //
    // consumed[referenceId] and totalDistributed are set BEFORE the two
    // JettonTransfer sends below, which is only safe because of what
    // happens if one of those sends can't be delivered downstream:
    //
    //   - consumed[referenceId] is NEVER unset, even on bounce. This is
    //     deliberate, not an oversight: the invariant from day one is ONE
    //     reference_id = ONE settlement opportunity, and the backend's
    //     cross-chain reservation (xera_reserve_onchain_claim) already
    //     treats this reference_id as consumed the moment it signed this
    //     claim — un-consuming it here would let the SAME reference_id be
    //     signed again for the other chain while this chain's attempt is
    //     still potentially in flight, which is exactly the double-spend
    //     this whole architecture exists to prevent.
    //
    //   - totalDistributed IS corrected on bounce (see the two bounced()
    //     handlers below), because it exists purely to enforce this
    //     chain's allocation cap against tokens that actually left this
    //     contract's custody — overcounting it after a bounce would
    //     eventually make legitimate claims fail the cap check for tokens
    //     that were never really distributed.
    //
    //   - The bounced value itself is NOT lost: `bounce: true` on both
    //     legs means a failed downstream send returns the TON/any
    //     attached value to `myWallet` automatically, and myWallet's own
    //     bounced<JettonTransferInternal> handler (jetton_wallet.tact)
    //     restores its jetton balance. The tokens end up back in the
    //     distributor's own jetton wallet, not destroyed.
    //
    //   - Recovery is explicitly NOT automatic on-chain — TON contracts
    //     can't retry their own past sends. The backend's confirmation
    //     step (python/xera/chain/claims.py) is responsible for detecting
    //     an incomplete settlement (both legs must be independently
    //     verified — see onchain_indexer.py) and surfacing it as a FAILED
    //     claim for support/governance follow-up, which can re-deliver
    //     the shortfall from the distributor's own wallet balance (which
    //     still holds it) using an ordinary, separately-authorized
    //     transfer — never a second Claim message, since referenceId
    //     stays permanently consumed.
    // ------------------------------------------------------------------
    bounced(msg: bounced<JettonTransfer>) {
        self.totalDistributed = self.totalDistributed - msg.amount;
    }

    receive(msg: Claim) {
        require(!self.paused, "XeraMiningDistributor: paused");

        let ds: Slice = msg.data.beginParse();
        let user: Address = ds.loadAddress();
        let amount: Int = ds.loadCoins();
        let referenceId: Int = ds.loadUint(256);
        let deadline: Int = ds.loadUint(64);

        require(now() <= deadline, "XeraMiningDistributor: claim expired");
        require(self.consumed.get(referenceId) == null, "XeraMiningDistributor: reference already consumed");
        require(amount > 0, "XeraMiningDistributor: zero amount");
        require(self.totalDistributed + amount <= self.maxAllocation, "XeraMiningDistributor: mining cap exceeded");

        // Reconstruct the EXACT flat canonical payload cell the backend
        // signed (see messages.tact's Claim/ClaimData doc for why the wire
        // shape and the signed-payload shape differ) and hash THAT.
        let payload: Cell = beginCell()
            .storeUint(0x2000, 32)
            .storeUint(msg.queryId, 64)
            .storeAddress(user)
            .storeCoins(amount)
            .storeUint(referenceId, 256)
            .storeUint(deadline, 64)
            .endCell();

        require(checkSignature(payload.hash(), msg.signature, self.signerPublicKey), "XeraMiningDistributor: invalid signature");

        // Effects before interactions.
        self.consumed.set(referenceId, true);
        self.totalDistributed = self.totalDistributed + amount;

        let transferable: Int = (amount * 2500) / 10000;
        let locked: Int = amount - transferable;

        // Correct TEP-74 custody pattern: this contract is not itself a
        // JettonWallet, so it can never construct a raw JettonTransferInternal
        // and have a receiving wallet accept it (the wallet's own sender
        // check only accepts the minter or another matching-code wallet).
        // Instead, like any Jetton holder, it instructs ITS OWN JettonWallet
        // (funded once with the mining allocation, exactly like the BNB
        // distributor is funded — see deploy notes) to transfer out via a
        // standard `JettonTransfer` message.
        let myWallet: Address = self.ownJettonWallet();

        // Gas accounting for the two async legs below.
        //
        // IMPORTANT (found by blockchain/ton/tests/XeraSettlement.integration.spec.ts):
        // the two legs must BOTH use explicit values with
        // SendPayGasSeparately. An earlier version sent leg 1 with an
        // explicit value and leg 2 with SendRemainingValue — that always
        // failed in the ACTION phase with exit code 37 ("Not enough
        // Toncoin"), at every attachable gas level, because
        // SendRemainingValue computes the remaining *inbound* value
        // without subtracting the value already committed to leg 1, so the
        // two actions together always over-commit the message balance.
        // Compute phase succeeded (exitCode 0) and the action phase then
        // aborted, which rolls the whole transaction back — so no funds
        // were ever lost, but NO claim could ever settle on TON.
        require(context().value >= self.claimGasRequirement(), "XeraMiningDistributor: insufficient gas attached");

        // Leg 1: 25% straight to the user's own Jetton wallet.
        send(SendParameters{
            to: myWallet,
            value: ton("0.1"), // this wallet's outbound transfer + user wallet deploy-on-first-receive
            mode: SendPayGasSeparately,
            bounce: true,
            body: JettonTransfer{
                queryId: msg.queryId,
                amount: transferable,
                destination: user,
                responseDestination: null,
                customPayload: null,
                forwardTonAmount: ton("0.01"), // see jetton_minter.tact's Mint handler comment — 1 nanoton aborts the whole action list
                forwardPayload: emptySlice()
            }.toCell()
        });

        // Leg 2: 75% to the vesting contract's own Jetton wallet, with a
        // forward payload telling XeraVesting which user/referenceId this
        // credit belongs to — XeraVesting creates the tranche when it
        // receives the resulting JettonTransferNotification (see
        // vesting.tact). This is the TON equivalent of the BNB
        // distributor calling `vesting.deposit(user, amount, referenceId)`
        // directly — TON has no synchronous cross-contract calls, so the
        // "call" is this async message + the notification vesting reacts to.
        send(SendParameters{
            to: myWallet,
            value: ton("0.15"), // outbound transfer + vesting wallet deploy + the 0.02 forward below
            mode: SendPayGasSeparately,
            bounce: true,
            body: JettonTransfer{
                queryId: msg.queryId,
                amount: locked,
                destination: self.vesting,
                responseDestination: null,
                customPayload: null,
                forwardTonAmount: ton("0.02"),
                forwardPayload: beginCell().storeAddress(user).storeUint(referenceId, 256).asSlice()
            }.toCell()
        });
    }

    // Total TON a caller must attach to a Claim so both settlement legs
    // can be paid for. Exposed as a getter (below) so the frontend can
    // read it at runtime rather than hardcoding a value that drifts out
    // of sync with the contract.
    fun claimGasRequirement(): Int {
        return ton("0.3"); // 0.1 (leg 1) + 0.15 (leg 2) + headroom for this contract's own compute
    }

    fun ownJettonWallet(): Address {
        return contractAddress(initOf XeraJettonWallet(self.minter, myAddress(), self.jettonWalletCode));
    }

    receive(msg: RotateSigner) {
        let ctx: Context = context();
        require(ctx.sender == self.admin, "XeraMiningDistributor: not admin");
        self.signerPublicKey = msg.newSigner;
    }

    receive(msg: SetPaused) {
        let ctx: Context = context();
        require(ctx.sender == self.admin, "XeraMiningDistributor: not admin");
        self.paused = msg.paused;
    }

    get fun is_consumed(referenceId: Int): Bool {
        return self.consumed.get(referenceId) != null;
    }

    get fun total_distributed(): Int {
        return self.totalDistributed;
    }

    get fun claim_gas_requirement(): Int {
        return self.claimGasRequirement();
    }

    get fun max_allocation(): Int {
        return self.maxAllocation;
    }
}
