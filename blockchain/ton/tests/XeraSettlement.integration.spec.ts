import { Blockchain, SandboxContract, TreasuryContract } from '@ton/sandbox';
import { toNano, Address, beginCell, Cell } from '@ton/core';
import '@ton/test-utils';
import { keyPairFromSeed, sign as tonSign } from '@ton/crypto';
import { XeraJettonMinter } from '../build/XeraJettonMinter_XeraJettonMinter';
import { XeraMiningDistributor } from '../build/XeraMiningDistributor_XeraMiningDistributor';
import { XeraVesting } from '../build/XeraVesting_XeraVesting';
import { XeraJettonWallet } from '../build/XeraJettonMinter_XeraJettonWallet';

// ============================================================
// Full TON mining-settlement integration test (Phases 9/10/11).
//
// Deploys the REAL minter + distributor + vesting together and drives an
// actual signed claim through the whole async flow, asserting the 25/75
// split lands where it should. Tact compiling is not evidence that TON
// works — this is.
// ============================================================

const SIGNER_SEED = Buffer.alloc(32, 0x11);
const MINING_CAP = 75_000_000n * 10n ** 18n;
const TON_CHAIN_SUPPLY = 100_000_000n * 10n ** 18n;
const VESTING_DURATION = 180n * 24n * 60n * 60n; // six months, matches the BNB side

function refId(s: string): bigint {
    return BigInt('0x' + require('crypto').createHash('sha256').update(s).digest('hex'));
}

function claimCellHash(queryId: bigint, user: Address, amount: bigint, reference: bigint, deadline: bigint): Buffer {
    return beginCell()
        .storeUint(0x2000, 32)
        .storeUint(queryId, 64)
        .storeAddress(user)
        .storeCoins(amount)
        .storeUint(reference, 256)
        .storeUint(deadline, 64)
        .endCell()
        .hash();
}

function claimData(user: Address, amount: bigint, reference: bigint, deadline: bigint): Cell {
    return beginCell()
        .storeAddress(user)
        .storeCoins(amount)
        .storeUint(reference, 256)
        .storeUint(deadline, 64)
        .endCell();
}


// Reads XeraJettonWallet's compiled code cell out of the generated Tact
// wrapper (which embeds it as a literal BOC hex string).
function readJettonWalletCode(): Cell {
    const fs = require('fs');
    const path = require('path');
    const src = fs.readFileSync(
        path.join(__dirname, '..', 'build', 'XeraJettonMinter_XeraJettonWallet.ts'), 'utf8'
    );
    const match = src.match(/Cell\.fromHex\('([0-9a-fA-F]+)'\)/);
    if (!match) throw new Error('could not locate XeraJettonWallet code cell in build output');
    return Cell.fromHex(match[1]);
}

describe('TON mining settlement — full integration', () => {
    let blockchain: Blockchain;
    let deployer: SandboxContract<TreasuryContract>;
    let admin: SandboxContract<TreasuryContract>;
    let user: SandboxContract<TreasuryContract>;
    let minter: SandboxContract<XeraJettonMinter>;
    let distributor: SandboxContract<XeraMiningDistributor>;
    let vesting: SandboxContract<XeraVesting>;
    const keyPair = keyPairFromSeed(SIGNER_SEED);

    beforeEach(async () => {
        blockchain = await Blockchain.create();
        blockchain.now = Math.floor(Date.now() / 1000);
        deployer = await blockchain.treasury('deployer');
        admin = await blockchain.treasury('admin');
        user = await blockchain.treasury('user');

        // XeraJettonWallet's compiled CODE cell is fixed (only its data
        // cell varies per minter/owner), so it's read straight from the
        // Tact build output. This also sidesteps XeraJettonWallet's
        // circular init signature, which takes its own code cell as an
        // argument.
        const jettonWalletCode: Cell = readJettonWalletCode();

        const content = beginCell().storeUint(0, 8).storeStringTail('XERA').endCell();

        minter = blockchain.openContract(
            await XeraJettonMinter.fromInit(admin.address, TON_CHAIN_SUPPLY, jettonWalletCode, content)
        );
        await minter.send(deployer.getSender(), { value: toNano('1') }, { $$type: 'Deploy', queryId: 0n } as any);

        vesting = blockchain.openContract(
            await XeraVesting.fromInit(
                minter.address, jettonWalletCode,
                admin.address, // inert placeholder — see SetDistributor wiring below
                admin.address, VESTING_DURATION
            )
        );

        distributor = blockchain.openContract(
            await XeraMiningDistributor.fromInit(
                minter.address, jettonWalletCode, vesting.address,
                BigInt('0x' + keyPair.publicKey.toString('hex')), admin.address, MINING_CAP
            )
        );
        await distributor.send(deployer.getSender(), { value: toNano('1') }, { $$type: 'Deploy', queryId: 0n } as any);

        // Wire vesting to the now-known real distributor address (see
        // vesting.tact's SetDistributor doc for why this two-step
        // deploy-then-wire sequence is required).
        await vesting.send(
            admin.getSender(), { value: toNano('0.05') },
            { $$type: 'SetDistributor', distributor: distributor.address } as any
        );
    });

    it('deploys the minter with the exact TON chain supply cap and no post-cap mint path', async () => {
        const data = await minter.getGetJettonData();
        expect(data.totalSupply).toBe(0n);

        // Mint the mining allocation to the distributor, as the real
        // deployment would.
        await minter.send(
            admin.getSender(), { value: toNano('1') },
            { $$type: 'Mint', queryId: 0n, receiver: distributor.address, amount: MINING_CAP } as any
        );
        const after = await minter.getGetJettonData();
        expect(after.totalSupply).toBe(MINING_CAP);

        // Minting beyond the chain cap must fail.
        const over = await minter.send(
            admin.getSender(), { value: toNano('1') },
            { $$type: 'Mint', queryId: 0n, receiver: distributor.address, amount: TON_CHAIN_SUPPLY } as any
        );
        expect(over.transactions).toHaveTransaction({ success: false });

        const final = await minter.getGetJettonData();
        expect(final.totalSupply).toBe(MINING_CAP); // unchanged
    });

    it('rejects Mint from a non-admin sender', async () => {
        const result = await minter.send(
            user.getSender(), { value: toNano('1') },
            { $$type: 'Mint', queryId: 0n, receiver: user.address, amount: 1000n } as any
        );
        expect(result.transactions).toHaveTransaction({ success: false });
        expect((await minter.getGetJettonData()).totalSupply).toBe(0n);
    });

    it('enforces the per-chain distributor mining cap on a signed claim', async () => {
        const deadline = BigInt(blockchain.now! + 3600);
        const reference = refId('over-cap');
        const amount = MINING_CAP + 1n;
        const sig = tonSign(claimCellHash(1n, user.address, amount, reference, deadline), keyPair.secretKey);

        const result = await distributor.send(
            user.getSender(), { value: toNano('0.5') },
            {
                $$type: 'Claim', queryId: 1n,
                data: claimData(user.address, amount, reference, deadline),
                signature: beginCell().storeBuffer(sig).endCell().beginParse(),
            } as any
        );
        expect(result.transactions).toHaveTransaction({ success: false });
    });

    it('rejects an expired claim', async () => {
        const deadline = BigInt(blockchain.now! - 10); // already past
        const reference = refId('expired');
        const sig = tonSign(claimCellHash(1n, user.address, 1000n, reference, deadline), keyPair.secretKey);

        const result = await distributor.send(
            user.getSender(), { value: toNano('0.5') },
            {
                $$type: 'Claim', queryId: 1n,
                data: claimData(user.address, 1000n, reference, deadline),
                signature: beginCell().storeBuffer(sig).endCell().beginParse(),
            } as any
        );
        expect(result.transactions).toHaveTransaction({ success: false });
    });

    it('rejects a replayed referenceId', async () => {
        await minter.send(
            admin.getSender(), { value: toNano('1') },
            { $$type: 'Mint', queryId: 0n, receiver: distributor.address, amount: toNano('1000000') } as any
        );

        const deadline = BigInt(blockchain.now! + 3600);
        const reference = refId('replay-me');
        const amount = toNano('1000');
        const sig = tonSign(claimCellHash(1n, user.address, amount, reference, deadline), keyPair.secretKey);
        const msg = {
            $$type: 'Claim', queryId: 1n,
            data: claimData(user.address, amount, reference, deadline),
            signature: beginCell().storeBuffer(sig).endCell().beginParse(),
        } as any;

        await distributor.send(user.getSender(), { value: toNano('0.5') }, msg);
        const second = await distributor.send(user.getSender(), { value: toNano('0.5') }, msg);
        expect(second.transactions).toHaveTransaction({ success: false });
    });

    it('pause blocks claims and only admin can set it', async () => {
        const notAdmin = await distributor.send(
            user.getSender(), { value: toNano('0.1') }, { $$type: 'SetPaused', paused: true } as any
        );
        expect(notAdmin.transactions).toHaveTransaction({ success: false });

        await distributor.send(admin.getSender(), { value: toNano('0.1') }, { $$type: 'SetPaused', paused: true } as any);

        const deadline = BigInt(blockchain.now! + 3600);
        const reference = refId('while-paused');
        const sig = tonSign(claimCellHash(1n, user.address, 1000n, reference, deadline), keyPair.secretKey);
        const result = await distributor.send(
            user.getSender(), { value: toNano('0.5') },
            {
                $$type: 'Claim', queryId: 1n,
                data: claimData(user.address, 1000n, reference, deadline),
                signature: beginCell().storeBuffer(sig).endCell().beginParse(),
            } as any
        );
        expect(result.transactions).toHaveTransaction({ success: false });
    });

    it('only admin can rotate the claim signer, and rotation invalidates old-key signatures', async () => {
        const newKp = keyPairFromSeed(Buffer.alloc(32, 0x44));

        const notAdmin = await distributor.send(
            user.getSender(), { value: toNano('0.1') },
            { $$type: 'RotateSigner', newSigner: BigInt('0x' + newKp.publicKey.toString('hex')) } as any
        );
        expect(notAdmin.transactions).toHaveTransaction({ success: false });

        await distributor.send(
            admin.getSender(), { value: toNano('0.1') },
            { $$type: 'RotateSigner', newSigner: BigInt('0x' + newKp.publicKey.toString('hex')) } as any
        );

        const deadline = BigInt(blockchain.now! + 3600);
        const reference = refId('after-rotation');
        const oldSig = tonSign(claimCellHash(1n, user.address, 1000n, reference, deadline), keyPair.secretKey);
        const result = await distributor.send(
            user.getSender(), { value: toNano('0.5') },
            {
                $$type: 'Claim', queryId: 1n,
                data: claimData(user.address, 1000n, reference, deadline),
                signature: beginCell().storeBuffer(oldSig).endCell().beginParse(),
            } as any
        );
        expect(result.transactions).toHaveTransaction({ success: false });
    });

    it('settles a valid claim with an exact 25/75 split: 25% to the user wallet, 75% into a vesting tranche', async () => {
        await minter.send(
            admin.getSender(), { value: toNano('1') },
            { $$type: 'Mint', queryId: 0n, receiver: distributor.address, amount: toNano('1000000') } as any
        );

        const deadline = BigInt(blockchain.now! + 3600);
        const reference = refId('happy-path-split');
        const amount = toNano('1000');
        const expectedTransferable = amount * 2500n / 10000n;
        const expectedLocked = amount - expectedTransferable;

        const sig = tonSign(claimCellHash(1n, user.address, amount, reference, deadline), keyPair.secretKey);
        const result = await distributor.send(
            user.getSender(), { value: toNano(process.env.CLAIM_GAS || '0.5') },
            {
                $$type: 'Claim', queryId: 1n,
                data: claimData(user.address, amount, reference, deadline),
                signature: beginCell().storeBuffer(sig).endCell().beginParse(),
            } as any
        );

        // The claim itself must have executed successfully.
        expect(result.transactions).toHaveTransaction({
            to: distributor.address,
            success: true,
        });

        // Distributor accounting: reference consumed, cap usage incremented
        // by the FULL entitlement (not just the transferable leg).
        expect(await distributor.getIsConsumed(reference)).toBe(true);
        expect(await distributor.getTotalDistributed()).toBe(amount);

        // 25% must have landed in the user's own jetton wallet.
        const userWalletAddr = await minter.getGetWalletAddress(user.address);
        const userWallet = blockchain.openContract(
            XeraJettonWallet.fromAddress(userWalletAddr)
        );
        const userData = await userWallet.getGetWalletData();
        expect(userData.balance).toBe(expectedTransferable);

        // 75% must have become a vesting tranche for this exact referenceId,
        // owned by the user — not by the caller, not by the distributor.
        const tranche = await vesting.getTrancheOf(reference);
        expect(tranche).not.toBeNull();
        expect(tranche!.amount).toBe(expectedLocked);
        expect(tranche!.owner.toString()).toBe(user.address.toString());
        expect(tranche!.released).toBe(0n);

        // Nothing is releasable immediately after deposit.
        expect(await vesting.getReleasable(reference)).toBe(0n);
    });

    // ---- The Phase 10 concern: async settlement that partially fails ----
    it('DOCUMENTS async-failure behaviour: referenceId is consumed before the async transfers resolve', async () => {
        await minter.send(
            admin.getSender(), { value: toNano('1') },
            { $$type: 'Mint', queryId: 0n, receiver: distributor.address, amount: toNano('1000000') } as any
        );

        const deadline = BigInt(blockchain.now! + 3600);
        const reference = refId('gas-starved');
        const amount = toNano('1000');
        const sig = tonSign(claimCellHash(1n, user.address, amount, reference, deadline), keyPair.secretKey);

        // Deliberately under-fund: not enough TON to cover both outbound
        // jetton transfer legs plus recipient wallet deployment.
        const result = await distributor.send(
            user.getSender(), { value: toNano('0.03') },
            {
                $$type: 'Claim', queryId: 1n,
                data: claimData(user.address, amount, reference, deadline),
                signature: beginCell().storeBuffer(sig).endCell().beginParse(),
            } as any
        );

        const consumed = await distributor.getIsConsumed(reference).catch(() => null);
        // This test records ACTUAL observed behaviour rather than asserting
        // a desired one — see blockchain/ton/README.md "Async settlement
        // failure" for the analysis and the required fix.
        console.log('async-failure probe — referenceId consumed:', consumed);
        console.log('async-failure probe — tx count:', result.transactions.length);
        expect(result.transactions.length).toBeGreaterThan(0);
    });
});
