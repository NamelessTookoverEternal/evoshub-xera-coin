// XERA blockchain UI — wallet connection, claim settlement, vesting status,
// legacy migration. Deliberately a separate module from xera.js: this never
// touches the mining/daily-claim code paths, it only drives the "chain"
// tab-panel in xera/index.html.
//
// Wallet model (mirrors the backend, python/xera/chain/wallet_link.py):
//   * CONNECTED  — the wallet signed a server-issued challenge, so ownership
//                  is cryptographically verified. Only this can settle claims.
//   * MANUAL     — a typed PUBLIC address. Saved to the account but marked
//                  unverified; it never proves ownership.
// This file never asks for, reads or sends a seed phrase, private key or
// wallet password. Manual input is rejected client-side if it looks like one.

import { TonConnectUI } from '@tonconnect/ui';

const API = window.XERA_API_BASE || (import.meta.env && import.meta.env.VITE_API_BASE_URL) || ((location.hostname === 'localhost' || location.hostname === '127.0.0.1') ? 'http://localhost:8000' : 'https://api.evoshub.xyz');
const $ = (id) => document.getElementById(id);
const token = () => localStorage.getItem('xera_evos_token') || '';

// ---------------------------------------------------------------- helpers

// Tiny DOM builder: every string goes in via textContent, never innerHTML, so
// nothing from the API (amounts, dates, addresses, error text) can inject markup.
function h(tag, attrs, ...children) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
        if (v === undefined || v === null || v === false) continue;
        if (k === 'class') el.className = v;
        else if (k === 'text') el.textContent = v;
        else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
        else el.setAttribute(k, v === true ? '' : v);
    }
    for (const c of children.flat()) {
        if (c === null || c === undefined || c === false) continue;
        el.append(c.nodeType ? c : document.createTextNode(String(c)));
    }
    return el;
}

async function req(path, opts = {}) {
    const r = await fetch(API + path, {
        ...opts,
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token()}`, ...(opts.headers || {}) },
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) {
        // FastAPI validation errors come back as an array of objects — never show that raw.
        const detail = typeof d.detail === 'string' ? d.detail : 'Something went wrong. Please check the details and try again.';
        const err = new Error(detail);
        err.status = r.status;
        throw err;
    }
    return d;
}

function fmtXera(amountWei, decimals = 18) {
    if (amountWei === undefined || amountWei === null) return '—';
    const n = Number(BigInt(amountWei)) / 10 ** decimals;
    return n.toLocaleString('en-US', { maximumFractionDigits: 2 });
}

function shorten(addr) {
    return addr && addr.length > 14 ? `${addr.slice(0, 6)}…${addr.slice(-4)}` : addr || '';
}

// MetaMask-style `personal_sign` wants the message hex-encoded; the wallet then
// adds the standard "\x19Ethereum Signed Message" prefix itself, which is what
// eth_account's encode_defunct(text=...) expects on the verification side.
function utf8ToHex(str) {
    const bytes = new TextEncoder().encode(str);
    return '0x' + Array.from(bytes).map((b) => b.toString(16).padStart(2, '0')).join('');
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function userMessage(err, fallback) {
    // EIP-1193 user rejection
    if (err && (err.code === 4001 || err.code === 'ACTION_REJECTED')) return 'You declined the request in your wallet. Nothing was changed.';
    if (err && err.code === -32002) return 'Your wallet already has a pending request — open it to continue.';
    const msg = err && err.message ? String(err.message) : '';
    // Raw provider/JS errors are noisy — keep our own (short, plain-English) messages only.
    if (err && err.userFacing) return msg;
    if (err && err.status && msg) return msg;
    return fallback;
}
const userError = (message) => Object.assign(new Error(message), { userFacing: true });

function setError(msg) {
    $('chainWalletError').textContent = msg || '';
}
function setNotice(msg) {
    const el = $('chainWalletNotice');
    el.textContent = msg || '';
    el.hidden = !msg;
}
function clearMessages() { setError(''); setNotice(''); }

// ---------------------------------------------------------------- state

const state = {
    wallets: { BNB: null, TON: null },   // from GET /wallet/linked
    manualFormOpen: { BNB: false, TON: false },
    busy: { BNB: false, TON: false },
    network: null,                        // GET /chain/config -> .bnb
    provider: null,                       // selected EIP-1193 provider { info, provider }
    providerChainId: null,                // wallet's current chain id (number) or null
    pickerOpen: false,
    pendingTonNonce: null,
};

// Explorer links follow the CONFIGURED network, not a hard-coded testnet.
function explorerTx(chain, hash) {
    if (chain === 'BNB') return `${(state.network && state.network.explorer_url) || 'https://testnet.bscscan.com'}/tx/${hash}`;
    return `https://testnet.tonscan.org/tx/${hash}`;
}

async function loadNetworkConfig() {
    if (state.network) return state.network;
    try {
        const { bnb } = await req('/api/xera/chain/config');
        state.network = bnb;
    } catch (_e) {
        state.network = null;
    }
    return state.network;
}

// ---------------------------------------------------------------- EVM provider discovery
//
// Not tied to MetaMask. Modern wallets (MetaMask, Trust Wallet, Binance Wallet,
// Coinbase, Rabby, OKX, …) announce themselves via EIP-6963, which also lets
// several installed wallets coexist without fighting over `window.ethereum`.
// Wallets that predate EIP-6963 are still picked up from `window.ethereum`
// (and its `.providers` array when more than one injects).

const discovered = new Map(); // uuid/key -> { info, provider }
let listening = false;

function startProviderDiscovery() {
    if (listening) return;
    listening = true;
    window.addEventListener('eip6963:announceProvider', (event) => {
        const { info, provider } = event.detail || {};
        if (info && provider && info.uuid) discovered.set(info.uuid, { info, provider });
    });
}

async function discoverProviders() {
    startProviderDiscovery();
    window.dispatchEvent(new Event('eip6963:requestProvider'));
    await sleep(250); // wallets answer synchronously/next-tick; this is just slack

    const list = [...discovered.values()];
    const known = new Set(list.map((p) => p.provider));
    const legacy = [];
    const eth = window.ethereum;
    if (eth) {
        const injected = Array.isArray(eth.providers) && eth.providers.length ? eth.providers : [eth];
        for (const p of injected) {
            if (!known.has(p)) legacy.push(p);
        }
    }
    legacy.forEach((p, i) => {
        const name = p.isTrust || p.isTrustWallet ? 'Trust Wallet'
            : p.isMetaMask ? 'MetaMask'
            : (p.isBinance || p.isBinanceChain) ? 'Binance Wallet'
            : 'Browser wallet';
        list.push({ info: { uuid: `legacy-${i}`, name, icon: '' }, provider: p });
    });
    return list;
}

function hexToInt(hex) { return parseInt(hex, 16); }

async function readChainId(provider) {
    try { return hexToInt(await provider.request({ method: 'eth_chainId' })); } catch (_e) { return null; }
}

function attachProviderListeners(entry) {
    const p = entry.provider;
    if (!p.on || entry.__listening) return;
    entry.__listening = true;
    p.on('chainChanged', (hex) => { state.providerChainId = hexToInt(hex); renderNetworkBanner(); });
    // Switching accounts in the wallet means the connected address may no longer
    // be the linked one — just refresh the view; claims always go to the LINKED address.
    p.on('accountsChanged', () => { renderNetworkBanner(); });
}

// ---------------------------------------------------------------- network banner (BNB)

function networkLabel(chainId) {
    if (chainId === 56) return 'BNB Smart Chain Mainnet';
    if (chainId === 97) return 'BNB Smart Chain Testnet';
    return null;
}

function renderNetworkBanner() {
    const el = $('chainNetworkBanner');
    const expected = state.network;
    if (!expected) { el.hidden = true; return; }
    el.replaceChildren();
    el.hidden = false;

    const walletId = state.providerChainId;
    el.append(h('span', { class: 'chain-network-expected', text: `Network: ${expected.name}` }));

    if (state.provider && walletId !== null) {
        if (walletId === expected.chain_id) {
            el.className = 'chain-network ok';
            el.append(h('span', { class: 'chain-network-state', text: 'Your wallet is on the right network.' }));
        } else {
            el.className = 'chain-network warn';
            const current = networkLabel(walletId) || 'an unsupported network';
            el.append(
                h('b', { text: 'Wrong network' }),
                h('span', { class: 'chain-network-state', text: `Your wallet is on ${current}. Please switch to ${expected.name} before continuing.` }),
                h('button', { type: 'button', class: 'btn btn-sm', text: 'Switch network', onclick: () => switchNetwork().catch((e) => setError(userMessage(e, 'Could not switch network. Please switch it in your wallet.'))) }),
            );
        }
    } else {
        el.className = 'chain-network';
    }
}

// Only ever runs from an explicit click — we never switch the user's network silently.
async function switchNetwork() {
    const net = state.network;
    if (!state.provider || !net) return;
    const { provider } = state.provider;
    try {
        await provider.request({ method: 'wallet_switchEthereumChain', params: [{ chainId: net.chain_id_hex }] });
    } catch (err) {
        if (err && err.code === 4902 && net.public_rpc_url) {
            await provider.request({
                method: 'wallet_addEthereumChain',
                params: [{
                    chainId: net.chain_id_hex,
                    chainName: net.name,
                    nativeCurrency: { name: net.native_symbol, symbol: net.native_symbol, decimals: 18 },
                    rpcUrls: [net.public_rpc_url],
                    blockExplorerUrls: net.explorer_url ? [net.explorer_url] : [],
                }],
            });
        } else {
            throw err;
        }
    }
    state.providerChainId = await readChainId(provider);
    renderNetworkBanner();
}

// ---------------------------------------------------------------- wallet cards

function walletCardHeader(chain, subtitle, tone) {
    return h('div', { class: 'chain-wallet-head' },
        h('span', { class: 'chain-badge', text: chain }),
        h('span', { class: `chain-wallet-status ${tone || ''}`, text: subtitle }),
    );
}

function addressRow(w) {
    const full = w.display_address || w.address;
    const copyBtn = h('button', {
        type: 'button', class: 'chain-copy', 'aria-label': 'Copy wallet address', text: 'Copy',
        onclick: async () => {
            try { await navigator.clipboard.writeText(full); copyBtn.textContent = 'Copied'; }
            catch (_e) { copyBtn.textContent = 'Press Ctrl+C'; }
            setTimeout(() => { copyBtn.textContent = 'Copy'; }, 1500);
        },
    });
    return h('div', { class: 'chain-addr-row' }, h('span', { class: 'chain-wallet-addr', title: full, text: full }), copyBtn);
}

function manualForm(chain, w) {
    const isBnb = chain === 'BNB';
    const existing = w && w.connection_method === 'manual' ? (w.display_address || w.address) : '';
    // A textarea (not a one-line input) so the WHOLE pasted address is visible —
    // it wraps onto a second line instead of scrolling out of sight, on any screen.
    const input = h('textarea', {
        id: `chainManualInput${chain}`, class: 'chain-manual-input', rows: '2',
        placeholder: isBnb ? 'Paste your BNB address (0x…)' : 'Paste your TON address (UQ… or EQ…)',
        autocomplete: 'off', autocapitalize: 'off', autocorrect: 'off', spellcheck: 'false',
        enterkeyhint: 'done',
        'aria-label': `${chain} wallet address (public address only)`,
    });
    input.value = existing; // textarea content is a property, not an attribute
    const grow = () => { input.style.height = 'auto'; input.style.height = `${Math.min(input.scrollHeight + 2, 160)}px`; };
    input.addEventListener('input', grow);
    requestAnimationFrame(grow);
    const submit = () => addManualWallet(chain, input);
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit(); } });
    return h('div', { class: 'chain-manual' },
        h('div', { class: 'chain-or', text: 'or' }),
        h('label', { class: 'chain-manual-label', for: `chainManualInput${chain}`, text: `Add ${chain} wallet address manually` }),
        input,
        h('button', { type: 'button', class: 'btn btn-sm chain-manual-submit', text: w && w.connection_method === 'manual' ? 'Update address' : 'Add wallet', onclick: submit }),
        h('p', { class: 'chain-manual-hint', text: 'Public address only — never a seed phrase or private key. A typed address is saved as unverified.' }),
    );
}

function renderWalletCard(chain) {
    const card = $(`chainWalletCard${chain}`);
    if (!card) return;
    const w = state.wallets[chain];
    const busy = state.busy[chain];
    card.replaceChildren();
    card.classList.toggle('is-busy', busy);

    const connectLabel = chain === 'BNB' ? 'Connect with wallet' : 'Connect TON wallet';
    const connectFn = chain === 'BNB' ? () => connectBnbWallet() : () => connectTonWallet();
    const connectBtn = (label) => h('button', { type: 'button', class: 'btn btn-sm', id: `chainConnect${chain}`, disabled: busy, text: busy ? 'Working…' : label, onclick: connectFn });

    if (!w) {
        // ---- not connected: connect with wallet, or add a manual address
        card.append(
            walletCardHeader(chain, 'Not connected'),
            h('div', { class: 'chain-actions' }, connectBtn(connectLabel)),
            manualForm(chain, null),
        );
        if (chain === 'BNB') card.append(h('div', { id: 'chainProviderPicker', class: 'chain-picker', hidden: !state.pickerOpen }));
        return;
    }

    if (w.verified) {
        // ---- connected (signature-verified)
        card.append(
            walletCardHeader(chain, 'Connected wallet', 'ok'),
            addressRow(w),
            h('div', { class: 'chain-actions' },
                h('button', { type: 'button', class: 'btn btn-sm', disabled: busy, text: 'Change wallet', onclick: connectFn }),
                h('button', { type: 'button', class: 'btn btn-sm btn-ghost', disabled: busy, text: 'Disconnect', onclick: () => removeWallet(chain, true) }),
            ),
        );
        if (chain === 'BNB') card.append(h('div', { id: 'chainProviderPicker', class: 'chain-picker', hidden: !state.pickerOpen }));
        return;
    }

    // ---- manual (unverified)
    card.append(
        walletCardHeader(chain, 'Manual address · not verified', 'warn'),
        addressRow(w),
        h('p', { class: 'chain-manual-hint', text: 'Saved to your account, but ownership is not proven — this address can’t be used to settle a claim until you connect the wallet and sign the ownership request.' }),
        h('div', { class: 'chain-actions' },
            connectBtn('Verify with wallet'),
            h('button', { type: 'button', class: 'btn btn-sm btn-ghost', disabled: busy, text: 'Change', onclick: () => { state.manualFormOpen[chain] = !state.manualFormOpen[chain]; renderWalletCard(chain); } }),
            h('button', { type: 'button', class: 'btn btn-sm btn-ghost', disabled: busy, text: 'Remove', onclick: () => removeWallet(chain, false) }),
        ),
    );
    if (state.manualFormOpen[chain]) card.append(manualForm(chain, w));
    if (chain === 'BNB') card.append(h('div', { id: 'chainProviderPicker', class: 'chain-picker', hidden: !state.pickerOpen }));
}

function setBusy(chain, value) {
    state.busy[chain] = value;
    renderWalletCard(chain);
}

async function refreshWallets() {
    try {
        const { wallets } = await req('/api/xera/wallet/linked');
        state.wallets = { BNB: null, TON: null };
        for (const w of wallets) state.wallets[w.chain] = w;
    } catch (_err) {
        // Non-fatal — the cards still render in their last known state.
    }
    renderWalletCard('BNB');
    renderWalletCard('TON');
}

// ---------------------------------------------------------------- manual address

// A seed phrase is 12–24 space-separated words; a private key is 64 hex chars.
// Neither can be a legitimate address here, so refuse before it goes anywhere —
// and clear the field so it isn't left sitting in the page.
function looksLikeSecret(value) {
    const v = value.trim();
    if (/\s/.test(v) && v.split(/\s+/).length >= 6) return true;
    if (/^(0x)?[0-9a-fA-F]{64}$/.test(v)) return true;
    return false;
}

async function addManualWallet(chain, input) {
    clearMessages();
    const value = input.value.trim();
    if (!value) { setError('Please enter a wallet address.'); return; }
    if (looksLikeSecret(value)) {
        input.value = '';
        setError('That looks like a seed phrase or private key. Never enter those anywhere — XERA only needs your public wallet address.');
        return;
    }
    if (chain === 'BNB' && !/^0x[0-9a-fA-F]{40}$/.test(value)) {
        setError('That doesn’t look like a valid BNB wallet address. It should start with 0x followed by 40 characters.');
        return;
    }
    setBusy(chain, true);
    try {
        const res = await req('/api/xera/wallet/manual', { method: 'POST', body: JSON.stringify({ chain, address: value }) });
        state.manualFormOpen[chain] = false;
        setNotice(res.notice || 'Wallet address added. This address has not been cryptographically verified as wallet ownership.');
    } catch (err) {
        setError(userMessage(err, 'Could not save this wallet address. Please try again.'));
    } finally {
        state.busy[chain] = false;
        await refreshWallets();
    }
}

async function removeWallet(chain, connected) {
    clearMessages();
    const what = connected ? 'Disconnect this wallet? You can reconnect it later, but changing wallets has a short cooldown.' : 'Remove this address from your account?';
    if (!window.confirm(what)) return;
    setBusy(chain, true);
    try {
        await req(`/api/xera/wallet/${chain}`, { method: 'DELETE' });
        if (chain === 'TON' && tonUI && tonUI.connected) { try { await tonUI.disconnect(); } catch (_e) { /* wallet session already gone */ } }
        if (chain === 'BNB') { state.provider = null; state.providerChainId = null; renderNetworkBanner(); }
        setNotice(connected ? 'Wallet disconnected.' : 'Address removed.');
    } catch (err) {
        setError(userMessage(err, 'Could not remove this wallet. Please try again.'));
    } finally {
        state.busy[chain] = false;
        await refreshWallets();
    }
}

// ---------------------------------------------------------------- BNB: connect with a browser wallet

async function connectBnbWallet() {
    clearMessages();
    state.pickerOpen = false;
    setBusy('BNB', true);
    try {
        await loadNetworkConfig();
        const providers = await discoverProviders();
        if (!providers.length) {
            setError('No browser wallet detected. You can connect a supported wallet (MetaMask, Trust Wallet, Binance Wallet…) or add your BNB wallet address manually. On mobile, open this page inside your wallet app’s browser.');
            return;
        }
        if (providers.length === 1) {
            await linkWithProvider(providers[0]);
        } else {
            state.pickerOpen = true;
            state.busy.BNB = false;
            renderWalletCard('BNB');
            renderProviderPicker(providers);
            return;
        }
    } catch (err) {
        setError(userMessage(err, 'Could not connect your BNB wallet. Please try again.'));
    } finally {
        if (!state.pickerOpen) { state.busy.BNB = false; await refreshWallets(); }
    }
}

function renderProviderPicker(providers) {
    const picker = $('chainProviderPicker');
    if (!picker) return;
    picker.hidden = false;
    picker.replaceChildren(
        h('div', { class: 'chain-picker-title', text: 'Choose a wallet' }),
        ...providers.map((entry) => h('button', {
            type: 'button', class: 'chain-picker-item',
            onclick: async () => {
                state.pickerOpen = false;
                setBusy('BNB', true);
                try { await linkWithProvider(entry); }
                catch (err) { setError(userMessage(err, 'Could not connect your BNB wallet. Please try again.')); }
                finally { state.busy.BNB = false; await refreshWallets(); }
            },
        },
        entry.info.icon && /^data:image\//.test(entry.info.icon) ? h('img', { src: entry.info.icon, alt: '', width: 20, height: 20 }) : null,
        h('span', { text: String(entry.info.name || 'Browser wallet').slice(0, 40) }))),
        h('button', { type: 'button', class: 'btn btn-sm btn-ghost', text: 'Cancel', onclick: () => { state.pickerOpen = false; renderWalletCard('BNB'); } }),
    );
}

async function linkWithProvider(entry) {
    const { provider } = entry;
    const accounts = await provider.request({ method: 'eth_requestAccounts' });
    const address = accounts && accounts[0];
    if (!address) throw userError('Your wallet didn’t share an account. Unlock it and try again.');

    state.provider = entry;
    state.providerChainId = await readChainId(provider);
    attachProviderListeners(entry);
    renderNetworkBanner();

    // Linking proves ownership of the ADDRESS by signing a message — it moves no
    // funds and doesn't depend on the network, so a wrong network doesn't block it.
    // (It does block settling a claim; see settleClaim.)
    const nonceRes = await req('/api/xera/wallet/link/nonce', { method: 'POST', body: JSON.stringify({ chain: 'BNB', address }) });
    const signature = await provider.request({ method: 'personal_sign', params: [utf8ToHex(nonceRes.message_to_sign), address] });
    await req('/api/xera/wallet/link/verify', { method: 'POST', body: JSON.stringify({ chain: 'BNB', address: nonceRes.address || address, nonce: nonceRes.nonce, signature }) });
    setNotice('BNB wallet connected and verified.');
}

// ---------------------------------------------------------------- TON: TonConnect

let tonUI = null;

function getTonUI() {
    if (tonUI) return tonUI;
    tonUI = new TonConnectUI({ manifestUrl: `${location.origin}/tonconnect-manifest.json` });
    tonUI.onStatusChange(async (wallet) => {
        // A restored session from an earlier visit also fires this, with NO proof —
        // only act when WE started a connect and are waiting for a proof.
        if (!wallet || !state.pendingTonNonce) return;
        const proof = wallet.connectItems && wallet.connectItems.tonProof;
        if (!proof) return;
        const nonce = state.pendingTonNonce;
        state.pendingTonNonce = null;
        if (proof.name !== 'ton_proof' || !proof.proof) {
            setError('Your wallet didn’t provide an ownership proof, so it can’t be verified. Try another TON wallet, or add the address manually.');
            setBusy('TON', false);
            return;
        }
        try {
            await req('/api/xera/wallet/link/verify', {
                method: 'POST',
                body: JSON.stringify({
                    chain: 'TON',
                    address: wallet.account.address,
                    nonce,
                    signature: proof.proof.signature,
                    domain: proof.proof.domain.value,
                    timestamp: proof.proof.timestamp,
                    public_key: wallet.account.publicKey,
                    state_init: wallet.account.walletStateInit,
                }),
            });
            setNotice('TON wallet connected and verified.');
        } catch (err) {
            setError(userMessage(err, 'Could not verify your TON wallet. Please try again.'));
            try { await tonUI.disconnect(); } catch (_e) { /* nothing to disconnect */ }
        } finally {
            state.busy.TON = false;
            await refreshWallets();
        }
    });
    tonUI.onModalStateChange((s) => {
        // Modal closed without connecting -> stop showing "Working…".
        if (s.status === 'closed' && state.pendingTonNonce && !(tonUI.wallet)) {
            state.pendingTonNonce = null;
            state.busy.TON = false;
            renderWalletCard('TON');
        }
    });
    return tonUI;
}

async function connectTonWallet() {
    clearMessages();
    setBusy('TON', true);
    try {
        const ui = getTonUI();
        // An existing TonConnect session carries no proof — drop it so the wallet
        // is asked again and this time returns one.
        if (ui.connected) await ui.disconnect();

        // The SERVER issues the proof payload before the wallet connects, so the
        // ton_proof the wallet signs embeds our single-use nonce (never a
        // client-chosen one).
        const nonceRes = await req('/api/xera/wallet/link/nonce', { method: 'POST', body: JSON.stringify({ chain: 'TON' }) });
        state.pendingTonNonce = nonceRes.ton_proof_payload;
        ui.setConnectRequestParameters({ state: 'ready', value: { tonProof: nonceRes.ton_proof_payload } });
        await ui.openModal();
    } catch (err) {
        state.pendingTonNonce = null;
        state.busy.TON = false;
        setError(userMessage(err, 'Could not open the TON wallet connector. Please try again, or add your address manually.'));
        renderWalletCard('TON');
    }
}

// ---------------------------------------------------------------- claimable entitlements
//
// "Claimable" = a CONFIRMED MINING_REWARD row in the user's off-chain ledger
// that hasn't been settled on-chain. The on-chain layer keys entitlements by
// `reference_id` (for mining rewards, the mining session id) — NOT by the
// ledger row's own `id`. Always send reference_id.

const PENDING_KEY = 'xera_pending_claim_txs'; // { [reference_id]: txHash } — survives a failed confirm call
function pendingTxs() { try { return JSON.parse(localStorage.getItem(PENDING_KEY) || '{}'); } catch (_e) { return {}; } }
function rememberPendingTx(ref, hash) { const m = pendingTxs(); m[ref] = hash; try { localStorage.setItem(PENDING_KEY, JSON.stringify(m)); } catch (_e) { /* storage full/blocked */ } }
function forgetPendingTx(ref) { const m = pendingTxs(); delete m[ref]; try { localStorage.setItem(PENDING_KEY, JSON.stringify(m)); } catch (_e) { /* ignore */ } }

const inFlight = new Set(); // reference_ids with a settle running in THIS tab (UX only — the backend enforces the real guard)

async function loadClaimables({ keepError = false } = {}) {
    if (!keepError) $('chainClaimError').textContent = '';
    const list = $('chainClaimableList');
    try {
        const { transactions } = await req('/api/xera/transactions?limit=50');
        const rewards = transactions.filter((t) => t.type === 'MINING_REWARD' && t.status === 'CONFIRMED');
        list.replaceChildren();
        if (!rewards.length) {
            list.append(h('p', { class: 'chain-empty', text: 'No eligible mining entitlement was found yet. Rewards appear here once a mining session is claimed.' }));
            return;
        }
        for (const tx of rewards) list.append(renderClaimRow(tx));
    } catch (err) {
        $('chainClaimError').textContent = userMessage(err, 'Could not load your mining entitlements. Please try again.');
    }
}

function renderClaimRow(tx) {
    const ref = tx.reference_id;           // <-- NOT tx.id
    const status = tx.onchain_claim_status;
    const date = tx.created_at ? new Date(tx.created_at).toLocaleDateString() : '';
    const label = h('span', { text: `${Number(tx.amount).toLocaleString()} XERA${date ? ' — ' + date : ''}` });
    const row = h('div', { class: 'chain-claim-row' }, label);

    if (status === 'CONFIRMED') {
        row.append(h('span', { class: 'chain-pill ok', text: `Settled on ${tx.onchain_claim_chain || 'chain'}` }));
        return row;
    }
    if (!ref) {
        row.append(h('span', { class: 'chain-pill warn', text: 'Unavailable' }));
        return row;
    }

    const savedHash = pendingTxs()[ref];
    if ((status === 'SIGNED' || status === 'SUBMITTED') && savedHash) {
        row.append(h('button', { type: 'button', class: 'btn btn-sm', text: 'Confirm settlement', onclick: () => confirmSaved(ref, savedHash) }));
        return row;
    }
    if (status === 'SIGNED' || status === 'SUBMITTED') {
        row.append(h('span', { class: 'chain-pill warn', text: 'In progress' }));
    }
    const btn = h('button', { type: 'button', class: 'btn btn-sm', 'data-ref': ref, text: status === 'FAILED' || status === 'EXPIRED' ? 'Try again' : 'Settle on-chain', onclick: () => settleClaim(ref, btn) });
    row.append(btn);
    return row;
}

async function confirmSaved(ref, hash) {
    $('chainClaimError').textContent = '';
    try {
        await req('/api/xera/claim/confirm', { method: 'POST', body: JSON.stringify({ reference_id: ref, transaction_hash: hash }) });
        forgetPendingTx(ref);
        setNotice('Settlement confirmed on-chain.');
        await Promise.all([loadClaimables(), loadVestingStatus()]);
    } catch (err) {
        $('chainClaimError').textContent = userMessage(err, 'Could not confirm this settlement yet. If the transaction is still pending, try again in a minute.');
    }
}

async function getEthers() {
    // Loaded on demand so the (large) library isn't part of the initial page weight.
    return import('ethers');
}

// Settlement, in order:
//   1. cheap local checks (chain supported, wallet connected & verified)
//   2. backend reserves the entitlement (single-use, DB-enforced) and signs it
//   3. wallet on the right network -> user confirms the transaction
//   4. backend independently verifies the transaction on-chain and only THEN marks settled
async function settleClaim(referenceId, button) {
    const chain = $('chainSelect').value;
    const errEl = $('chainClaimError');
    errEl.textContent = '';
    clearMessages();

    // TON settlement isn't wired up. Check BEFORE asking the backend to sign:
    // signing reserves the entitlement, and reserving something we then can't
    // submit would leave it stuck "in progress" until the signature expires.
    if (chain !== 'BNB') {
        errEl.textContent = 'TON settlement is not yet available — please settle on BNB Smart Chain for now.';
        return;
    }

    const wallet = state.wallets.BNB;
    if (!wallet) { errEl.textContent = 'Your BNB wallet must be connected before this entitlement can be settled.'; return; }
    if (!wallet.verified) { errEl.textContent = 'Your BNB address was added manually and hasn’t been verified. Connect the wallet and sign the ownership request before settling.'; return; }

    if (inFlight.has(referenceId)) return;
    inFlight.add(referenceId);
    if (button) { button.disabled = true; button.textContent = 'Preparing…'; }

    try {
        await loadNetworkConfig();
        const providers = state.provider ? [state.provider] : await discoverProviders();
        if (!providers.length) throw userError('No browser wallet detected. Open this page in a wallet-enabled browser to confirm the transaction.');
        let entry = providers.length === 1 ? providers[0] : null;
        if (!entry) {
            // Several wallets installed: prefer the one that already exposes the linked address.
            for (const p of providers) {
                try {
                    const accts = await p.provider.request({ method: 'eth_accounts' });
                    if (accts.some((a) => a.toLowerCase() === wallet.address.toLowerCase())) { entry = p; break; }
                } catch (_e) { /* wallet locked */ }
            }
        }
        if (!entry) throw userError('Several wallets are installed. Use “Change wallet” above to pick the one linked to this account, then try again.');
        state.provider = entry;
        attachProviderListeners(entry);
        state.providerChainId = await readChainId(entry.provider);
        renderNetworkBanner();

        // Wrong network is checked BEFORE the backend reserves anything.
        if (state.network && state.providerChainId !== state.network.chain_id) {
            throw userError(`Wrong network. Please switch your wallet to ${state.network.name} before continuing.`);
        }

        if (button) button.textContent = 'Signing…';
        const { claim } = await req('/api/xera/claim/sign', {
            method: 'POST',
            body: JSON.stringify({ reference_id: referenceId, chain }),
        });

        if (button) button.textContent = 'Confirm in wallet…';
        const { BrowserProvider, Contract } = await getEthers();
        const browserProvider = new BrowserProvider(entry.provider);
        const signer = await browserProvider.getSigner();
        const contract = new Contract(claim.contract_address, [DISTRIBUTOR_CLAIM_ABI], signer);
        const tx = await contract.claim(claim.user, claim.amount_wei, claim.reference_id_hash, claim.deadline, claim.signature);
        rememberPendingTx(referenceId, tx.hash);   // so a failed confirm call can be retried without re-sending

        if (button) button.textContent = 'Waiting for network…';
        await tx.wait();
        await req('/api/xera/claim/confirm', { method: 'POST', body: JSON.stringify({ reference_id: referenceId, transaction_hash: tx.hash }) });
        forgetPendingTx(referenceId);
        setNotice(`Settled on-chain. Transaction ${shorten(tx.hash)}`);
        window.open(explorerTx('BNB', tx.hash), '_blank', 'noopener');
    } catch (err) {
        errEl.textContent = userMessage(err, 'Could not settle this claim. Your entitlement has not been lost — please try again.');
    } finally {
        inFlight.delete(referenceId);
        // keepError: the refresh must not wipe the failure message we just showed.
        await Promise.all([loadClaimables({ keepError: true }), loadVestingStatus()]);
    }
}

// Minimal ABI fragment — just the one function the frontend calls directly.
const DISTRIBUTOR_CLAIM_ABI = 'function claim(address user,uint256 amount,bytes32 referenceId,uint256 deadline,bytes signature)';

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
    block.replaceChildren();
    try {
        const { migration } = await req('/api/xera/migration/status');
        if (!migration.has_legacy_balance) {
            block.append(h('p', { class: 'chain-empty', text: 'No pre-blockchain legacy balance found for this account.' }));
            return;
        }
        if (migration.claimed) {
            block.append(h('p', { style: 'font-size:.8rem' }, 'Legacy balance of ', h('b', { text: `${migration.legacy_balance} XERA` }), ` already claimed on ${migration.claimed_chain}.`));
            return;
        }
        block.append(
            h('p', { style: 'font-size:.8rem' }, 'You have an unclaimed legacy balance of ', h('b', { text: `${migration.legacy_balance} XERA` }), '.'),
            h('button', { type: 'button', class: 'btn btn-sm', id: 'chainMigrationClaimBtn', text: 'Claim legacy balance (BNB)', onclick: claimLegacyMigration }),
        );
    } catch (_err) {
        block.append(h('p', { class: 'chain-empty', text: 'Could not load legacy migration status.' }));
    }
}

async function claimLegacyMigration() {
    const block = $('chainMigrationBlock');
    block.querySelectorAll('.banner-error').forEach((n) => n.remove());
    try {
        const wallet = state.wallets.BNB;
        if (!wallet || !wallet.verified) throw userError('Connect and verify your BNB wallet before claiming your legacy balance.');
        await loadNetworkConfig();
        const providers = state.provider ? [state.provider] : await discoverProviders();
        const entry = providers[0];
        if (!entry) throw userError('No browser wallet detected. Open this page in a wallet-enabled browser to confirm the transaction.');
        state.providerChainId = await readChainId(entry.provider);
        if (state.network && state.providerChainId !== state.network.chain_id) {
            throw userError(`Wrong network. Please switch your wallet to ${state.network.name} before continuing.`);
        }
        const { claim } = await req('/api/xera/migration/claim/prepare', { method: 'POST', body: JSON.stringify({ chain: 'BNB' }) });
        const { BrowserProvider, Contract } = await getEthers();
        const signer = await new BrowserProvider(entry.provider).getSigner();
        const abi = 'function claim(uint256 leafIndex,address account,uint256 amount,bytes32[] proof)';
        const contract = new Contract(claim.contract_address, [abi], signer);
        const account = await signer.getAddress();
        const tx = await contract.claim(claim.leaf_index, account, claim.amount_wei, claim.merkle_proof);
        await tx.wait();
        await req('/api/xera/migration/claim/confirm', { method: 'POST', body: JSON.stringify({ chain: 'BNB', transaction_hash: tx.hash }) });
        await loadMigrationStatus();
    } catch (err) {
        block.append(h('p', { class: 'banner-error', text: userMessage(err, 'Legacy claim failed. Please try again.') }));
    }
}

// ================= CLAIM HISTORY =================

async function loadClaimHistory() {
    // Settled claims already show as "Settled on <chain>" in the list above; a
    // dedicated paginated listing endpoint is a natural follow-up once
    // xera_onchain_claims has enough volume to warrant one.
    const el = $('chainClaimHistory');
    el.replaceChildren(h('p', { class: 'chain-empty', text: 'Settlement history will appear here once you’ve confirmed a claim on-chain.' }));
}

// ================= INIT =================

async function openChainTab() {
    clearMessages();
    await loadNetworkConfig();
    renderNetworkBanner();
    await refreshWallets();
    loadClaimables();
    loadVestingStatus();
    loadMigrationStatus();
    loadClaimHistory();
}

function initChainPanel() {
    renderWalletCard('BNB');
    renderWalletCard('TON');
    startProviderDiscovery();
    $('chainSelect')?.addEventListener('change', () => { loadVestingStatus(); });

    document.querySelectorAll('[data-tab="chain"], [data-goto="chain"]').forEach((btn) => {
        btn.addEventListener('click', () => { openChainTab(); });
    });
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initChainPanel);
} else {
    initChainPanel();
}
