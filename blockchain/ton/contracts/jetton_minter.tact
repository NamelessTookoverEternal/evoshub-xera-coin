import "@stdlib/deploy";
import "./messages.tact";
import "./jetton_wallet.tact";

// XeraJettonMinter — TON master Jetton contract for XERA.
//
// Section 11 of the brief: standard TON Jetton implementation, no bridge.
// Section 12: hard on-chain supply cap for this chain's portion of XERA.
//
// Mint happens ONCE, at TGE, via `Mint` messages sent by `admin` up to
// `mintableSupply` (the deployment-configured TON-side cap — see
// BLOCKCHAIN_INTEGRATION.md "Blocking decision": this is a constructor
// argument, never a hard-coded guess). After TGE, `admin` transfers its own
// admin rights to the zero address (or a TON multisig) via `ChangeAdmin` —
// TON has no `AccessControl.renounceRole` equivalent, so "revoke minting"
// here means "there is no longer any address holding the admin role that
// can call Mint".
contract XeraJettonMinter with Deployable {
    totalSupply: Int as coins;
    mintableSupply: Int as coins; // hard cap — set once at deploy, never changed
    admin: Address;
    jettonWalletCode: Cell;
    content: Cell;

    init(admin: Address, mintableSupply: Int, jettonWalletCode: Cell, content: Cell) {
        self.totalSupply = 0;
        self.mintableSupply = mintableSupply;
        self.admin = admin;
        self.jettonWalletCode = jettonWalletCode;
        self.content = content;
    }

    receive(msg: Mint) {
        let ctx: Context = context();
        require(ctx.sender == self.admin, "XeraJettonMinter: not admin");
        require(self.totalSupply + msg.amount <= self.mintableSupply, "XeraJettonMinter: exceeds chain cap");

        self.totalSupply = self.totalSupply + msg.amount;

        let winit: StateInit = self.getJettonWalletInit(msg.receiver);
        send(SendParameters{
            to: contractAddress(winit),
            value: 0,
            mode: SendRemainingValue,
            bounce: false,
            code: winit.code,
            data: winit.data,
            body: JettonTransferInternal{
                queryId: msg.queryId,
                amount: msg.amount,
                sender: myAddress(),
                responseDestination: self.admin,
                forwardTonAmount: 1,
                forwardPayload: emptySlice()
            }.toCell()
        });
    }

    // Section 7/14 equivalent for TON: admin transfers itself away (to a
    // TON multisig, or to a burn/inert address) once TGE minting is done.
    // There is deliberately no "renounce back" — this is one-directional.
    receive(msg: ChangeAdmin) {
        let ctx: Context = context();
        require(ctx.sender == self.admin, "XeraJettonMinter: not admin");
        self.admin = msg.newAdmin;
    }

    receive(msg: JettonBurnNotification) {
        let ctx: Context = context();
        let expectedWallet: StateInit = self.getJettonWalletInit(msg.sender);
        require(ctx.sender == contractAddress(expectedWallet), "XeraJettonMinter: unauthorized burn notification");
        self.totalSupply = self.totalSupply - msg.amount;
    }

    fun getJettonWalletInit(owner: Address): StateInit {
        return initOf XeraJettonWallet(myAddress(), owner, self.jettonWalletCode);
    }

    get fun get_jetton_data(): JettonData {
        return JettonData{
            totalSupply: self.totalSupply,
            mintable: true,
            adminAddress: self.admin,
            jettonContent: self.content,
            jettonWalletCode: self.jettonWalletCode
        };
    }

    get fun get_wallet_address(owner: Address): Address {
        return contractAddress(self.getJettonWalletInit(owner));
    }

    get fun mintable_supply(): Int {
        return self.mintableSupply;
    }
}
