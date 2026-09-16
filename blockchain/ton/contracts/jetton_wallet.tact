import "@stdlib/deploy";
import "./messages.tact";

// XeraJettonWallet — one per holder, deployed by the minter on first
// receipt. Standard, unmodified TEP-74 wallet logic: section 3 of the
// brief applies to TON exactly as it does to the BNB XeraToken — no
// locked balances, no transfer restrictions, no blacklist. Locking is
// handled entirely by XeraVesting simply not forwarding tokens to a
// user's wallet until they're releasable.
contract XeraJettonWallet {
    balance: Int as coins;
    owner: Address;
    minter: Address;
    jettonWalletCode: Cell;

    init(minter: Address, owner: Address, jettonWalletCode: Cell) {
        self.balance = 0;
        self.owner = owner;
        self.minter = minter;
        self.jettonWalletCode = jettonWalletCode;
    }

    // If the downstream JettonTransferInternal we just sent (in
    // receive(JettonTransfer) below) can't be delivered — the destination
    // wallet's deploy/compute fails, or it runs out of gas — TON bounces
    // it back to us (we send with bounce: true specifically so this
    // happens instead of silently vanishing tokens). Without this
    // handler, the balance we already debited in receive(JettonTransfer)
    // would never be restored: real value would be gone with no error
    // visible anywhere on-chain. This is what item 6 of the hardening
    // brief calls a "stuck funds" async-failure case — this handler is
    // the recovery mechanism for the jetton-wallet hop of it (the
    // distributor's own consumed/totalDistributed bookkeeping is a
    // separate, contract-level concern — see mining_distributor.tact's
    // header comment on the settlement/recovery model).
    //
    // Tact truncates a bounced message to what fits in the first ~224
    // bits after the opcode, so only `amount` (not `sender` or the rest)
    // is reliably available here — which is exactly what we need to
    // restore the balance correctly regardless of which transfer bounced.
    bounced(msg: bounced<JettonTransferInternal>) {
        self.balance = self.balance + msg.amount;
    }

    receive(msg: JettonTransferInternal) {
        let ctx: Context = context();
        // Only the minter (initial mint) or another XeraJettonWallet with
        // the same code (a peer-to-peer transfer) may credit this wallet.
        require(
            ctx.sender == self.minter || self.isValidWalletSender(ctx.sender, msg.sender),
            "XeraJettonWallet: unauthorized credit"
        );

        self.balance = self.balance + msg.amount;

        if (msg.forwardTonAmount > 0) {
            send(SendParameters{
                to: self.owner,
                value: msg.forwardTonAmount,
                mode: SendPayGasSeparately,
                bounce: false,
                body: JettonTransferNotification{
                    queryId: msg.queryId,
                    amount: msg.amount,
                    sender: msg.sender,
                    forwardPayload: msg.forwardPayload
                }.toCell()
            });
        }

        if (msg.responseDestination != null) {
            send(SendParameters{
                to: msg.responseDestination!!,
                value: 0,
                // SendRemainingValue (64) computes "remaining value of the
                // INBOUND message" independently of other actions already
                // queued in this same transaction — combined with the
                // notification send above (explicit value, paid
                // separately), the two together over-commit against this
                // wallet's actual balance and the whole action list aborts
                // with "not enough funds" (confirmed empirically in the
                // TON sandbox; the same failure mode already documented in
                // mining_distributor.tact's Claim handler for its own two
                // outgoing legs). SendRemainingBalance (128) instead sends
                // whatever the contract's balance ACTUALLY is at the point
                // this action executes — correct after an earlier
                // explicit-value send in the same transaction.
                mode: SendRemainingBalance,
                bounce: false,
                body: TokenExcesses{ queryId: msg.queryId }.toCell()
            });
        }
    }

    receive(msg: JettonTransfer) {
        let ctx: Context = context();
        require(ctx.sender == self.owner, "XeraJettonWallet: not owner");
        require(self.balance >= msg.amount, "XeraJettonWallet: insufficient balance");

        self.balance = self.balance - msg.amount;

        let winit: StateInit = initOf XeraJettonWallet(self.minter, msg.destination, self.jettonWalletCode);
        send(SendParameters{
            to: contractAddress(winit),
            value: 0,
            mode: SendRemainingValue,
            bounce: true,
            code: winit.code,
            data: winit.data,
            body: JettonTransferInternal{
                queryId: msg.queryId,
                amount: msg.amount,
                sender: self.owner,
                responseDestination: msg.responseDestination,
                forwardTonAmount: msg.forwardTonAmount,
                forwardPayload: msg.forwardPayload
            }.toCell()
        });
    }

    receive(msg: JettonBurn) {
        let ctx: Context = context();
        require(ctx.sender == self.owner, "XeraJettonWallet: not owner");
        require(self.balance >= msg.amount, "XeraJettonWallet: insufficient balance");

        self.balance = self.balance - msg.amount;

        send(SendParameters{
            to: self.minter,
            value: 0,
            mode: SendRemainingValue,
            bounce: true,
            body: JettonBurnNotification{
                queryId: msg.queryId,
                amount: msg.amount,
                sender: self.owner,
                responseDestination: msg.responseDestination
            }.toCell()
        });
    }

    fun isValidWalletSender(sender: Address, claimedOwner: Address): Bool {
        let expected: StateInit = initOf XeraJettonWallet(self.minter, claimedOwner, self.jettonWalletCode);
        return sender == contractAddress(expected);
    }

    get fun get_wallet_data(): WalletData {
        return WalletData{
            balance: self.balance,
            owner: self.owner,
            minter: self.minter,
            jettonWalletCode: self.jettonWalletCode
        };
    }
}
