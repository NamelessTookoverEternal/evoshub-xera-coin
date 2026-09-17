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

    receive(msg: JettonTransferInternal) {
        let ctx: Context = context();
        // Only the minter (initial mint) or another XeraJettonWallet with
        // the same code (a peer-to-peer transfer) may credit this wallet.
        require(
            ctx.sender == self.minter || self.isValidWalletSender(ctx.sender, msg.sender),
            "XeraJettonWallet: unauthorized credit"
        );

        self.balance = self.balance + msg.amount;

        // NOTE (found via blockchain/ton/tests/debug_mint.spec.ts, same
        // class of bug as mining_distributor.tact's original two-leg send —
        // see that file's fix comment): sending an explicit-value message
        // first and then a SendRemainingValue (mode 64, "remaining value of
        // the CURRENT inbound message") message second still over-commits —
        // mode 64 does not subtract what the first send already spent
        // within the same transaction. A plain Mint (forwardTonAmount = 1
        // nanoton, responseDestination = admin) reliably failed the action
        // phase with exit code 37 ("Not enough Toncoin") until both sends
        // below were given explicit fixed values.
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
                    // BUG (found via blockchain/ton/tests/XeraSettlement.integration.spec.ts):
                    // this previously hardcoded emptySlice() instead of
                    // propagating the incoming forward payload, silently
                    // discarding whatever the ORIGINAL sender attached
                    // (e.g. mining_distributor.tact's (user, referenceId)
                    // payload for XeraVesting to read) — every downstream
                    // notification-payload consumer would Cell-underflow
                    // trying to parse an empty slice as real data.
                    forwardPayload: msg.forwardPayload
                }.toCell()
            });
        }

        if (msg.responseDestination != null) {
            send(SendParameters{
                to: msg.responseDestination!!,
                value: ton("0.005"), // small fixed gas refund — NOT the incoming message's true remaining value (see note above for why SendRemainingValue is unsafe here)
                mode: SendPayGasSeparately,
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
