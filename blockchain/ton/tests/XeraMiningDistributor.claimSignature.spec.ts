import { Blockchain, SandboxContract } from '@ton/sandbox';
import { toNano, Address, beginCell, Cell } from '@ton/core';
import '@ton/test-utils';
import { XeraMiningDistributor } from '../build/XeraMiningDistributor_XeraMiningDistributor';
import { keyPairFromSeed, sign as tonSign } from '@ton/crypto';

// XeraJettonWallet's compiled code cell is fixed/self-contained (Tact
// bakes it once; only the *data* cell varies per minter/owner) — we only
// need the code, which Blueprint's generated wrapper embeds as a literal
// BOC hex. Reading it directly here sidesteps XeraJettonWallet.fromInit's
// circular signature (it needs its OWN code cell as one of its init args,
// which is exactly what we're extracting).
const JETTON_WALLET_CODE = Cell.fromHex(
    'b5ee9c7241020e010003b2000228ff008e88f4a413f4bcf2c80bed5320e303ed43d901030151a65ec0bb513434800066fe803e903e9035154c1b05277e903e9035154800f4561c140cf8b6cf1b11200200085473212303d03001d072d721d200d200fa4021103450666f04f86102f862ed44d0d200019bfa00fa40fa40d455306c149dfa40fa40d4552003d158705033e205925f05e003d70d1ff2e082218210178d4519bae3022182100f8a7ea5bae302018210595f07bcbae3025f05f2c08204080b03c431d33ffa00fa40d72c01916d93fa4001e201fa0030f8416f2410235f0381740b5319c70592317f8e8f1048103749aa28db3c49a010481037e2f2f45163a026c20093366c21e30d206eb3915be30d4003c87f01ca0055305043fa02ce12ceccc9ed540506070168546331db3c705920f90022f9005ad76501d76582020134c8cb17cb0fcb0fcbffcbff71f90400c87401cb0212ca07cbffc9d0c7050900ba71708b082747135066c8553082107362d09c5005cb1f13cb3f01fa02cecec926041038405510246d50436d03c8cf8580ca00cf8440ce01fa028069cf40025c6e016eb0935bcf819d58cf8680cf8480f400f400cf81e2f400c901fb000300a6206ef2d0807080407004c8018210d53276db58cb1fcb3fc91034413010246d50436d03c8cf8580ca00cf8440ce01fa028069cf40025c6e016eb0935bcf819d58cf8680cf8480f400f400cf81e2f400c901fb0002de31d33ffa00fa40d72c01916d93fa4001e201f40431fa00f8416f245b8142ac3228c705f2f48166805385bef2f45174a152842adb3c5c705920f90022f9005ad76501d76582020134c8cb17cb0fcb0fcbffcbff71f90400c87401cb0212ca07cbffc9d050767080407f2b4813507dc8090a001ef82ac87001ca0055215023cececcc900f255508210178d45195007cb1f15cb3f5003fa02ce01206e9430cf84809201cee201fa02cec910561058103441301810464515504403c8cf8580ca00cf8440ce01fa028069cf40025c6e016eb0935bcf819d58cf8680cf8480f400f400cf81e2f400c901fb004003c87f01ca0055305043fa02ce12ceccc9ed5402fed33ffa00d72c01916d93fa4001e231f8416f245b8142ac3225c705f2f48166805352bef2f45141a17080405414357f08c8553082107bdd97de5005cb1f13cb3f01fa02ce01206e9430cf84809201cee2c926044313506610246d50436d03c8cf8580ca00cf8440ce01fa028069cf40025c6e016eb0935bcf818ae2f400c9010c0d001a58cf8680cf8480f400f400cf81002cfb004003c87f01ca0055305043fa02ce12ceccc9ed544f205faa'
);

// ============================================================
// Cross-language verification of the TON claim signature format
// (BLOCKCHAIN_INTEGRATION.md, "TON claim signature format").
//
// This submits a signature produced by the ACTUAL Python signer
// (python/xera/chain/ton_claim_signer.py) to the ACTUAL compiled
// XeraMiningDistributor contract in a TON sandbox — not a mock of
// either side. python/tests/test_ton_claim_signer.py pins the exact
// same cell-hash/signature values from the Python side; if either file
// changes, regenerate both together.
//
// Fixed vector generated via:
//   cd python && python3 -c "
//   from xera.chain.ton_claim_signer import sign_ton_claim
//   import json; print(json.dumps(sign_ton_claim(
//       signing_key_hex='11'*32, query_id=42,
//       user_address='0:' + '22'*32, amount_nano=1000*10**9,
//       reference_id='mining-session-abc123', deadline_unix=9999999999,
//   ), indent=2))"
// ============================================================

const SIGNER_SEED = Buffer.alloc(32, 0x11);
const USER_ADDRESS = Address.parse('0:' + '22'.repeat(32));
const QUERY_ID = 42n;
const AMOUNT_NANO = 1000n * 1_000_000_000n;
const DEADLINE = 9999999999n;
const REFERENCE_ID_UINT256 = BigInt(
    '0x' + require('crypto').createHash('sha256').update('mining-session-abc123').digest('hex')
);

// Pinned from the Python run described above — the authoritative cross-check value.
const EXPECTED_CELL_HASH_HEX = 'cc0a81fa853e118ee7282b705d547d74a3097b81b2db4f33a888df57cf5d196e';

function buildClaimCellHash(): Buffer {
    return beginCell()
        .storeUint(0x2000, 32)
        .storeUint(QUERY_ID, 64)
        .storeAddress(USER_ADDRESS)
        .storeCoins(AMOUNT_NANO)
        .storeUint(REFERENCE_ID_UINT256, 256)
        .storeUint(DEADLINE, 64)
        .endCell()
        .hash();
}

function buildClaimData(user: Address, amountNano: bigint, referenceIdUint256: bigint, deadline: bigint): Cell {
    return beginCell()
        .storeAddress(user)
        .storeCoins(amountNano)
        .storeUint(referenceIdUint256, 256)
        .storeUint(deadline, 64)
        .endCell();
}

describe('XeraMiningDistributor — TON claim signature cross-verification', () => {
    let blockchain: Blockchain;
    let distributor: SandboxContract<XeraMiningDistributor>;
    const keyPair = keyPairFromSeed(SIGNER_SEED);

    beforeEach(async () => {
        blockchain = await Blockchain.create();
        const treasury = await blockchain.treasury('placeholder');

        const contract = await XeraMiningDistributor.fromInit(
            treasury.address, // minter placeholder — not exercised by the signature check itself
            JETTON_WALLET_CODE,
            treasury.address, // vesting placeholder
            BigInt('0x' + keyPair.publicKey.toString('hex')),
            treasury.address, // admin placeholder
            75_000_000n * 1_000_000_000n
        );
        distributor = blockchain.openContract(contract);
        const deployer = await blockchain.treasury('deployer');
        await distributor.send(deployer.getSender(), { value: toNano('1') }, { $$type: 'Deploy', queryId: 0n } as any);
    });

    it('the TypeScript-built cell hash matches the Python-produced cell hash exactly (the actual joint-spec check)', () => {
        const hash = buildClaimCellHash();
        expect(hash.toString('hex')).toBe(EXPECTED_CELL_HASH_HEX);
    });

    it('the compiled contract accepts a signature produced by the Python Ed25519 signer', async () => {
        const digest = buildClaimCellHash();
        expect(digest.toString('hex')).toBe(EXPECTED_CELL_HASH_HEX);

        const signature = tonSign(digest, keyPair.secretKey);
        const sender = await blockchain.treasury('claimer');

        const result = await distributor.send(
            sender.getSender(),
            { value: toNano('0.2') },
            {
                $$type: 'Claim',
                queryId: QUERY_ID,
                data: buildClaimData(USER_ADDRESS, AMOUNT_NANO, REFERENCE_ID_UINT256, DEADLINE),
                signature: beginCell().storeBuffer(signature).endCell().beginParse(),
            } as any
        );

        const signatureRejected = result.transactions.some(
            (t: any) => t.description?.computePhase?.exitCode !== undefined
                && t.description.computePhase.exitCode !== 0
                && t.description.computePhase?.vmLogs?.includes?.('invalid signature')
        );
        expect(signatureRejected).toBe(false);
    });

    it('rejects the same signature when the amount is tampered with after signing', async () => {
        const digest = buildClaimCellHash();
        const signature = tonSign(digest, keyPair.secretKey);
        const sender = await blockchain.treasury('claimer2');

        const result = await distributor.send(
            sender.getSender(),
            { value: toNano('0.2') },
            {
                $$type: 'Claim',
                queryId: QUERY_ID,
                data: buildClaimData(USER_ADDRESS, AMOUNT_NANO + 1n, REFERENCE_ID_UINT256, DEADLINE), // tampered post-signing
                signature: beginCell().storeBuffer(signature).endCell().beginParse(),
            } as any
        );

        expect(result.transactions).toHaveTransaction({ success: false });
    });

    it('rejects a valid-format signature from a DIFFERENT key', async () => {
        const otherKeyPair = keyPairFromSeed(Buffer.alloc(32, 0x33));
        const digest = buildClaimCellHash();
        const wrongSignature = tonSign(digest, otherKeyPair.secretKey);
        const sender = await blockchain.treasury('claimer3');

        const result = await distributor.send(
            sender.getSender(),
            { value: toNano('0.2') },
            {
                $$type: 'Claim',
                queryId: QUERY_ID,
                data: buildClaimData(USER_ADDRESS, AMOUNT_NANO, REFERENCE_ID_UINT256, DEADLINE),
                signature: beginCell().storeBuffer(wrongSignature).endCell().beginParse(),
            } as any
        );

        expect(result.transactions).toHaveTransaction({ success: false });
    });
});
