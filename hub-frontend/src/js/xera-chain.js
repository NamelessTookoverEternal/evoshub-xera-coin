// XERA blockchain UI — wallet linking, claim settlement, vesting status,
// legacy migration. Deliberately a separate module from xera.js (section
// 18: "update the existing frontend only where required" — this never
// touches the mining/daily-claim code paths, it only adds the new panel
// wired up in xera/index.html's "chain" tab-panel).

const API = window.XERA_API_BASE || (import.meta.env && import.meta.env.VITE_API_BASE_URL) || ((location.hostname === 'localhost' || location.hostname === '127.0.0.1') ? 'http://localhost:8000' : 'https://api.evoshub.xyz');
const $ = (id) => document.getElementById(id);
const token = () => localStorage.getItem('xera_evos_token') || '';

const EXPLORERS = {
    BNB: { tx: (h) => `https://testnet.bscscan.com/tx/${h}`, address: (a) => `https://testnet.bscscan.com/address/${a}` },
    TON: { tx: (h) => `https://testnet.tonscan.org/tx/${h}`, address: (a) => `https://testnet.tonscan.org/address/${a}` },
};

async function req(path, opts = {}) {
    const r = await fetch(API + path, {
        ...opts,
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token()}`, ...(opts.headers || {}) },
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.detail || 'Request failed');
    return d;
}

function fmtXera(amountWei, decimals = 18) {
    if (amountWei === undefined || amountWei === null) return '—';
    const n = Number(BigInt(amountWei)) / 10 ** decimals;
    return n.toLocaleString('en-US', { maximumFractionDigits: 2 });
}

// MetaMask's `personal_sign` RPC expects the message as a hex-encoded
// string, not raw UTF-8 — it then applies the standard
// "\x19Ethereum Signed Message:\n<len>" prefix itself before signing,
// which is exactly what eth_account's `encode_defunct(text=...)` expects
// on the verification side (see xera.chain.bnb_verify.verify_bnb_signature).
function utf8ToHex(str) {
    const bytes = new TextEncoder().encode(str);
    return '0x' + Array.from(bytes).map((b) => b.toString(16).padStart(2, '0')).join('');
}

// ================= BNB WALLET CONNECT (EIP-1193 / MetaMask-style) =================

async function connectBnbWallet() {
    $('chainWalletError').textContent = '';
    if (!window.ethereum) {
        $('chainWalletError').textContent = 'No BNB-compatible wallet found. Install MetaMask or Trust Wallet.';
        return;
    }
    try {
        const [address] = await window.ethereum.request({ method: 'eth_requestAccounts' });
        const nonceRes = await req('/api/xera/wallet/link/nonce', {
            method: 'POST',
            body: JSON.stringify({ chain: 'BNB', address }),
        });
        const signature = await window.ethereum.request({
            method: 'personal_sign',
            params: [utf8ToHex(nonceRes.message_to_sign), address],
        });
        await req('/api/xera/wallet/link/verify', {
            method: 'POST',
            body: JSON.stringify({ chain: 'BNB', address, nonce: nonceRes.nonce, signature }),
        });
        await refreshWallets();
    } catch (err) {
        $('chainWalletError').textContent = err.message || 'Could not connect BNB wallet.';
    }
}

// ================= TON WALLET CONNECT (TonConnect UI) =================
//
// Expects the TonConnect UI SDK to already be loaded on the page (a
// `<script src="https://unpkg.com/@tonconnect/ui@.../tonconnect-ui.min.js">`
// tag + `window.TON_CONNECT_MANIFEST_URL`) — this module only drives it,
// it does not bundle it, so the page stays lean when TON isn't in use.
async function connectTonWallet() {
    $('chainWalletError').textContent = '';
    if (!window.TonConnectUI) {
        $('chainWalletError').textContent = 'TON Connect isn\u2019t loaded on this page yet.';
        return;
    }
    try {
        const tonConnectUI = window.__xeraTonConnectUI || (window.__xeraTonConnectUI = new window.TonConnectUI.TonConnectUI({
            manifestUrl: window.TON_CONNECT_MANIFEST_URL,
        }));

        // Server issues the payload BEFORE we ask the wallet to connect, so
        // the ton_proof the wallet signs embeds our nonce, not a client-
        // generated one (never trust a client-picked payload for a proof).
        const nonceRes = await req('/api/xera/wallet/link/nonce', {
            method: 'POST',
            body: JSON.stringify({ chain: 'TON', address: 'pending' }),
        });

        tonConnectUI.setConnectRequestParameters({
            state: 'ready',
            value: { tonProof: nonceRes.ton_proof_payload },
        });

        const unsubscribe = tonConnectUI.onStatusChange(async (wallet) => {
            if (!wallet) return;
            unsubscribe();
            const proof = wallet.connectItems && wallet.connectItems.tonProof;
            if (!proof || proof.type !== 'ton_proof') {
                $('chainWalletError').textContent = 'Wallet did not return a proof — cannot verify ownership.';
                return;
            }
            try {
                await req('/api/xera/wallet/link/verify', {
                    method: 'POST',
                    body: JSON.stringify({
                        chain: 'TON',
                        address: wallet.account.address,
                        nonce: nonceRes.nonce,
                        signature: proof.proof.signature,
                        domain: proof.proof.domain.value,
                        timestamp: proof.proof.timestamp,
                        public_key: wallet.account.publicKey,
                    }),
                });
                await refreshWallets();
            } catch (err) {
                $('chainWalletError').textContent = err.message || 'Could not verify TON wallet.';
            }
        });

        await tonConnectUI.openModal();
    } catch (err) {
        $('chainWalletError').textContent = err.message || 'Could not connect TON wallet.';
    }
}

// ================= WALLET DISPLAY =================

function shorten(addr) {
    return addr && addr.length > 12 ? `${addr.slice(0, 6)}…${addr.slice(-4)}` : addr;
}

async function refreshWallets() {
    try {
        const { wallets } = await req('/api/xera/wallet/linked');
        for (const chain of ['BNB', 'TON']) {
            const w = wallets.find((x) => x.chain === chain);
            $(`chainWalletAddr${chain}`).textContent = w ? shorten(w.address) : 'Not connected';
        }
    } catch (_err) {
        // Non-fatal — the connect buttons remain usable even if this read fails.
    }
}

// ================= CLAIMABLE ENTITLEMENTS =================
//
// "Claimable" here means: a MINING_REWARD transaction the user already has
// in their off-chain ledger (xera.js's transaction list) that hasn't been
// settled on-chain yet. We reuse /api/xera/transactions rather than adding
// a duplicate endpoint — the chain layer treats that ledger as the source
// of truth for "what am I entitled to" (section 4/5 of the integration).

async function loadClaimables() {
    $('chainClaimError').textContent = '';
    try {
        const { transactions } = await req('/api/xera/transactions?limit=20');
        const rewards = transactions.filter((t) => t.type === 'MINING_REWARD');
        const list = $('chainClaimableList');
        list.innerHTML = '';
        if (!rewards.length) {
            list.innerHTML = '<p style="font-size:.8rem;color:var(--text-secondary)">No mining rewards to settle yet.</p>';
            return;
        }
        for (const tx of rewards) {
            const row = document.createElement('div');
            row.className = 'chain-claim-row';
            row.innerHTML = `
                <span>${Number(tx.amount).toLocaleString()} XERA — ${new Date(tx.created_at).toLocaleDateString()}</span>
                <button type="button" class="btn btn-sm" data-ref="${tx.id}">Settle on-chain</button>
            `;
            row.querySelector('button').addEventListener('click', () => settleClaim(String(tx.id)));
            list.appendChild(row);
        }
    } catch (err) {
        $('chainClaimError').textContent = err.message || 'Could not load claimable entitlements.';
    }
}

async function settleClaim(referenceId) {
    const chain = $('chainSelect').value;
    $('chainClaimError').textContent = '';
    try {
        const { claim } = await req('/api/xera/claim/sign', {
            method: 'POST',
            body: JSON.stringify({ reference_id: referenceId, chain }),
        });

        if (chain === 'BNB') {
            if (!window.ethereum) throw new Error('No BNB wallet available to submit the transaction.');
            const txHash = await submitBnbClaim(claim);
            await req('/api/xera/claim/confirm', {
                method: 'POST',
                body: JSON.stringify({ reference_id: referenceId, transaction_hash: txHash }),
            });
            window.open(EXPLORERS.BNB.tx(txHash), '_blank', 'noopener');
        } else {
            $('chainClaimError').textContent = 'TON settlement is not yet available — BNB only for now.';
            return;
        }

        await Promise.all([loadClaimables(), loadVestingStatus(), loadClaimHistory()]);
    } catch (err) {
        $('chainClaimError').textContent = err.message || 'Could not settle this claim.';
    }
}

// Minimal ABI fragment — just the one function the frontend calls directly.
const DISTRIBUTOR_CLAIM_ABI = 'function claim(address user,uint256 amount,bytes32 referenceId,uint256 deadline,bytes signature)';

async function submitBnbClaim(claim) {
    // Uses ethers if the page already loads it (xera.js's page does, for
    // other features); falls back to a raw eth_sendTransaction with
    // manually-encoded calldata if not, so this never hard-requires a new
    // bundle dependency just for this one call.
    if (window.ethers) {
        const provider = new window.ethers.BrowserProvider(window.ethereum);
        const signer = await provider.getSigner();
        const contract = new window.ethers.Contract(claim.contract_address, [DISTRIBUTOR_CLAIM_ABI], signer);
        const tx = await contract.claim(claim.user, claim.amount_wei, claim.reference_id_hash, claim.deadline, claim.signature);
        await tx.wait();
        return tx.hash;
    }

    throw new Error('ethers.js is required on this page to submit a BNB claim transaction.');
}

// ================= VESTING STATUS =================

async function loadVestingStatus() {
    const chain = $('chainSelect').value;
    try {
        const { vesting } = await req(`/api/xera/onchain/status?chain=${chain}`);
        $('chainReleasable').textContent = vesting ? `${fmtXera(vesting.releasable_wei)} XERA` : '—';
        $('chainLocked').textContent = vesting ? `${fmtXera(vesting.locked_remaining_wei)} XERA` : '—';
    } catch (_err) {
        $('chainReleasable').textContent = '—';
        $('chainLocked').textContent = '—';
    }
}

// ================= LEGACY MIGRATION =================

async function loadMigrationStatus() {
    const block = $('chainMigrationBlock');
    try {
        const { migration } = await req('/api/xera/migration/status');
        if (!migration.has_legacy_balance) {
            block.innerHTML = '<p style="font-size:.78rem;color:var(--text-secondary)">No pre-blockchain legacy balance found for this account.</p>';
            return;
        }
        if (migration.claimed) {
            block.innerHTML = `<p style="font-size:.8rem">Legacy balance of <b>${migration.legacy_balance} XERA</b> already claimed on ${migration.claimed_chain}.</p>`;
            return;
        }
        block.innerHTML = `
            <p style="font-size:.8rem">You have an unclaimed legacy balance of <b>${migration.legacy_balance} XERA</b>.</p>
            <button type="button" class="btn btn-sm" id="chainMigrationClaimBtn">Claim legacy balance (BNB)</button>
        `;
        $('chainMigrationClaimBtn').addEventListener('click', claimLegacyMigration);
    } catch (_err) {
        block.innerHTML = '<p style="font-size:.78rem;color:var(--text-secondary)">Could not load legacy migration status.</p>';
    }
}

async function claimLegacyMigration() {
    try {
        const { claim } = await req('/api/xera/migration/claim/prepare', {
            method: 'POST',
            body: JSON.stringify({ chain: 'BNB' }),
        });
        if (!window.ethers) throw new Error('ethers.js is required to submit this claim.');
        const provider = new window.ethers.BrowserProvider(window.ethereum);
        const signer = await provider.getSigner();
        const abi = 'function claim(uint256 leafIndex,address account,uint256 amount,bytes32[] proof)';
        const contract = new window.ethers.Contract(claim.contract_address, [abi], signer);
        const account = await signer.getAddress();
        const tx = await contract.claim(claim.leaf_index, account, claim.amount_wei, claim.merkle_proof);
        await tx.wait();

        await req('/api/xera/migration/claim/confirm', {
            method: 'POST',
            body: JSON.stringify({ chain: 'BNB', transaction_hash: tx.hash }),
        });
        await loadMigrationStatus();
    } catch (err) {
        $('chainMigrationBlock').insertAdjacentHTML('beforeend', `<p class="banner-error">${err.message || 'Legacy claim failed.'}</p>`);
    }
}

// ================= CLAIM HISTORY =================

async function loadClaimHistory() {
    // Deliberately reuses the same transactions endpoint for now — a
    // dedicated /api/xera/onchain/claims listing endpoint is a natural
    // follow-up once xera_onchain_claims has enough volume to warrant its
    // own paginated view.
    const el = $('chainClaimHistory');
    el.innerHTML = '<p style="font-size:.78rem;color:var(--text-secondary)">Settlement history will appear here once you\u2019ve confirmed a claim on-chain.</p>';
}

// ================= INIT =================

function initChainPanel() {
    $('chainConnectBNB')?.addEventListener('click', connectBnbWallet);
    $('chainConnectTON')?.addEventListener('click', connectTonWallet);
    $('chainSelect')?.addEventListener('change', () => { loadVestingStatus(); });

    document.querySelectorAll('[data-tab="chain"], [data-goto="chain"]').forEach((btn) => {
        btn.addEventListener('click', () => {
            refreshWallets();
            loadClaimables();
            loadVestingStatus();
            loadMigrationStatus();
            loadClaimHistory();
        });
    });
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initChainPanel);
} else {
    initChainPanel();
}
