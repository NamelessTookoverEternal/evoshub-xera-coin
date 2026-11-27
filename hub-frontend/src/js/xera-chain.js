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
import { appKitConfigured, connectWithAppKit, cancelAppKitConnect, reopenAppKitPicker, restoredAppKitProvider, disconnectAppKit, switchAppKitNetwork, nudgeAppKitConnection, appKitDiagnostics, openChosenWalletApp, liveWalletSession, waitForRelay } from './xera-appkit.js';

const API = window.XERA_API_BASE || (import.meta.env && import.meta.env.VITE_API_BASE_URL) || ((location.hostname === 'localhost' || location.hostname === '127.0.0.1') ? 'http://localhost:8000' : 'https://api.evoshub.xyz');
const $ = (id) => document.getElementById(id);
// Admin pilot mode. The admin page (admin-xera-wallet.html) must NOT depend on an inline
// script having run first: some in-app wallet browsers (e.g. SafePal) don't apply it, which
// left this module in user mode calling the user routes with no user token ("invalid token").
// So the mode is decided here, from the page URL, and window.XERA_CHAIN_CONFIG is only an
// optional override. Normal /xera behaviour is unchanged.
const ADMIN_PAGE = /\/admin-xera-wallet(\.html)?\/?$/.test(location.pathname);
const ADMIN_DEFAULTS = {
    prefix: '/api/admin/xera/pilot',
    noMigration: true,
    relay: true,                      // claims are sent by the server's relayer wallet
    getToken: () => { try { return sessionStorage.getItem('evoshub_admin_token') || ''; } catch (e) { return ''; } },
    onUnauthorized: () => { try { sessionStorage.removeItem('evoshub_admin_token'); } catch (e) { /* ignore */ } location.href = '/admin-login.html'; },
};
const CFG = { ...(ADMIN_PAGE ? ADMIN_DEFAULTS : {}), ...(window.XERA_CHAIN_CONFIG || {}) };
const PFX = CFG.prefix || '/api/xera';
const token = () => (CFG.getToken ? CFG.getToken() : localStorage.getItem('xera_evos_token')) || '';

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
        err.code = typeof d.code === 'string' ? d.code : '';
        err.missing = Array.isArray(d.missing) ? d.missing : [];
        // KYC / one-time fee not complete: the server refused. Show the "complete these steps" dialog.
        if (err.code === 'transfer_requirements_incomplete' && window.XeraReadiness) window.XeraReadiness.showRequirements(err.missing);
        if (r.status === 401 && CFG.onUnauthorized) CFG.onUnauthorized();
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

// The server only records a claim once the transaction has enough confirmations (more on mainnet
// than on testnet). Right after the wallet reports the first block it may say "waiting for more
// confirmations" or "not found yet" — both just mean "ask again shortly", so retry for ~1 minute.
async function confirmClaimOnServer(referenceId, txHash) {
    const body = JSON.stringify({ reference_id: referenceId, transaction_hash: txHash });
    let lastErr;
    for (let attempt = 0; attempt < 12; attempt++) {
        try {
            return await req(PFX + '/claim/confirm', { method: 'POST', body });
        } catch (err) {
            lastErr = err;
            const msg = String((err && err.message) || '');
            const pending = /more network confirmations|not found on-chain yet/i.test(msg);
            if (!pending) throw err;
            await sleep(5000);
        }
    }
    throw lastErr;
}

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

// ---------------------------------------------------------------- manual (typed) address helpers
// A typed address can receive withdrawals, but only after a safety wait and with the account password.
// The server enforces both; the checks here only explain things early and save a round trip.
const isManual = (w) => !!w && !w.verified && w.connection_method === 'manual';

function manualReadyMs(w) {
    const t = w && w.withdraw_ready_at ? Date.parse(w.withdraw_ready_at) : NaN;
    return Number.isNaN(t) ? null : t;
}

function waitText(ms) {
    const mins = Math.max(1, Math.ceil(ms / 60000));
    const hrs = Math.floor(mins / 60);
    return hrs ? `${hrs} h ${mins % 60} min` : `${mins} min`;
}

// The address with its first and last 6 characters set apart, so a typo or a swapped address is easy to spot.
function addressWithEnds(addr) {
    const box = h('div', { style: 'font-family:ui-monospace,Menlo,monospace;font-size:.9rem;line-height:1.5;word-break:break-all;padding:10px 12px;border-radius:12px;background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.14)' });
    const strong = 'color:#5ee0a0;font-weight:700';
    box.append(h('span', { style: strong, text: addr.slice(0, 6) }), addr.slice(6, -6), h('span', { style: strong, text: addr.slice(-6) }));
    return box;
}

// Confirmation + password popup shown before a withdrawal to a manual address. Resolves to the password,
// or null if the user cancels. Nothing is reserved or signed until this returns a password.
function confirmManualWithdraw(wallet, amountText) {
    return new Promise((resolve) => {
        const overlay = h('div', { role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Confirm withdrawal address',
            style: 'position:fixed;inset:0;z-index:10000;display:flex;align-items:center;justify-content:center;padding:16px;background:rgba(5,8,18,.78)' });
        const card = h('div', { style: 'width:100%;max-width:420px;max-height:92vh;overflow:auto;box-sizing:border-box;padding:18px;border-radius:18px;background:#0f1424;color:#e8ecf7;border:1px solid rgba(255,255,255,.14);display:grid;gap:12px' });
        const pw = h('input', { type: 'password', autocomplete: 'current-password', placeholder: 'Account password', 'aria-label': 'Account password',
            style: 'width:100%;box-sizing:border-box;padding:11px 12px;border-radius:12px;border:1px solid rgba(255,255,255,.2);background:rgba(255,255,255,.06);color:inherit;font-size:1rem' });
        const check = h('input', { type: 'checkbox', id: 'mwdCheck', style: 'margin-top:3px' });
        const err = h('p', { role: 'alert', style: 'margin:0;color:#ff7b8a;font-size:.85rem;min-height:1em' });
        const go = h('button', { type: 'button', class: 'btn', text: 'Withdraw', disabled: true });
        const cancel = h('button', { type: 'button', class: 'btn btn-ghost', text: 'Cancel' });
        const sync = () => { go.disabled = !(check.checked && pw.value.length > 0); };
        check.addEventListener('change', sync);
        pw.addEventListener('input', sync);
        const finish = (value) => { document.removeEventListener('keydown', onKey); overlay.remove(); resolve(value); };
        const onKey = (e) => { if (e.key === 'Escape') finish(null); };
        document.addEventListener('keydown', onKey);
        cancel.addEventListener('click', () => finish(null));
        go.addEventListener('click', () => { if (!go.disabled) finish(pw.value); });
        pw.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !go.disabled) finish(pw.value); });
        card.append(
            h('h3', { style: 'margin:0;font-size:1.05rem', text: 'Check the address before you withdraw' }),
            h('p', { style: 'margin:0;font-size:.85rem;line-height:1.45;color:#aeb8d0', text: `${amountText ? `${amountText} XERA will be` : 'XERA will be'} sent to this address. This address was typed in, not verified by your wallet. XERA sent to a wrong address cannot be recovered.` }),
            addressWithEnds(wallet.address),
            h('p', { style: 'margin:0;font-size:.85rem;line-height:1.45;color:#aeb8d0', text: 'Compare the first 6 and last 6 characters (green) with the address in your wallet app. You will then confirm in a wallet that has a little BNB for the network fee; it can be a different wallet, and the XERA still goes to the address above.' }),
            h('label', { for: 'mwdCheck', style: 'display:flex;gap:8px;align-items:flex-start;font-size:.85rem;line-height:1.4' }, check,
                h('span', { text: 'I checked this address. It is my own wallet.' })),
            pw, err,
            h('div', { style: 'display:flex;gap:8px;justify-content:flex-end;flex-wrap:wrap' }, cancel, go),
        );
        overlay.append(card);
        document.body.append(overlay);
        pw.focus();
    });
}

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
        const { bnb } = await req(PFX + '/chain/config');
        state.network = bnb;
        renderWalletCard('BNB');
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

// Providers usable for a transaction right now: the one chosen this visit, else a
// restored WalletConnect session, else browser-injected wallets.
async function activeProviders() {
    if (state.provider) return [state.provider];
    const restored = await restoredAppKitProvider(state.network && state.network.chain_id);
    if (restored) return [{ info: { uuid: 'appkit', name: 'WalletConnect', icon: '' }, provider: restored.provider, appkit: true, chainId: restored.chainId }];
    return discoverProviders();
}

// Wallets report the chain in different shapes: '0x38', 56, '56', 'eip155:56'. Reading '56' as hex gave 86, which is
// what made the page call a correct BNB wallet an "unsupported network".
function toChainNumber(v) {
    if (typeof v === 'number') return Number.isFinite(v) ? v : null;
    if (typeof v !== 'string') return null;
    const s = v.trim().toLowerCase().replace(/^eip155:/, '');
    if (/^0x[0-9a-f]+$/.test(s)) return parseInt(s, 16);
    if (/^\d+$/.test(s)) return parseInt(s, 10);
    return null;
}
// On a phone the wallet app is not in front when we send it a request (approve a claim, switch network, add token),
// so the user sees nothing happen. Run the request, and after a moment jump to the wallet app the user picked.
// Only for WalletConnect connections; wallets with an in-page provider show their own prompt.
const IS_PHONE = typeof navigator !== 'undefined' && /android|iphone|ipad|ipod/i.test(navigator.userAgent || '');
async function withWalletRedirect(entry, fn, delayMs = 1500) {
    if (!IS_PHONE || !entry || !entry.appkit) return fn();
    nudgeAppKitConnection();
    await waitForRelay(4000);
    const timer = setTimeout(() => { openChosenWalletApp(); }, delayMs);     // lets the request leave the page first
    try { return await fn(); } finally { clearTimeout(timer); }
}

function hexToInt(v) { return toChainNumber(v); }

// For a WalletConnect/AppKit connection, AppKit's own live chain id is the source of truth.
async function readChainId(provider, fallback = null) {
    const live = liveWalletSession();
    if (live && live.provider === provider && live.chainId != null) return live.chainId;
    try {
        const n = toChainNumber(await provider.request({ method: 'eth_chainId' }));
        return n != null ? n : fallback;
    } catch (_e) { return fallback; }
}

// The accounts a wallet connection is sharing with this page. A restored WalletConnect session can be alive but share
// nothing (expired, or the wallet app was closed), so an empty answer gets one explicit request before we give up.
async function readAccounts(provider) {
    let accts = [];
    try { accts = await provider.request({ method: 'eth_accounts' }); } catch (_e) { /* locked */ }
    if (Array.isArray(accts) && accts.length) return accts;
    try { accts = await provider.request({ method: 'eth_requestAccounts' }); } catch (_e) { accts = []; }
    return Array.isArray(accts) ? accts : [];
}

function attachProviderListeners(entry) {
    const p = entry.provider;
    if (!p.on || entry.__listening) return;
    entry.__listening = true;
    p.on('chainChanged', (v) => { const n = toChainNumber(v); if (n != null) state.providerChainId = n; renderNetworkBanner(); });
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
        if (Number(walletId) === Number(expected.chain_id)) {
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
    if (state.provider.appkit) {
        await withWalletRedirect(state.provider, () => switchAppKitNetwork(net.chain_id));
        state.providerChainId = net.chain_id;
        renderNetworkBanner();
        return;
    }
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

// ---------------------------------------------------------------- add XERA to wallet
// One tap asks the wallet to track the XERA token (EIP-747 wallet_watchAsset) so the balance
// and logo show up. Public token info only — nothing here reads or sends a key or seed.
const XERA_TOKEN_SYMBOL = 'XERA';
const XERA_TOKEN_DECIMALS = 18;
const XERA_TOKEN_LOGO = 'https://evoshub.xyz/assets/images/xera-token-logo-1024.png';

async function addXeraToWallet(btn, msgEl) {
    const net = state.network;
    const addr = net && net.xera_token_address;
    const say = (t) => { msgEl.textContent = t; };
    if (!addr) { say('The XERA token address is not published yet.'); return; }
    const provider = (state.provider && state.provider.provider) || (typeof window !== 'undefined' && window.ethereum) || null;
    const copyFallback = async (reason) => {
        try { await navigator.clipboard.writeText(addr); say(`${reason} Contract address copied — in your wallet choose “Add custom token”, paste it, symbol ${XERA_TOKEN_SYMBOL}, decimals ${XERA_TOKEN_DECIMALS}.`); }
        catch (_e) { say(`${reason} Add a custom token manually: ${addr} · symbol ${XERA_TOKEN_SYMBOL} · decimals ${XERA_TOKEN_DECIMALS}.`); }
    };
    if (!provider || typeof provider.request !== 'function') { await copyFallback('Your wallet can’t add tokens automatically.'); return; }
    if (state.providerChainId && net.chain_id && Number(state.providerChainId) !== Number(net.chain_id)) {
        say(`Switch your wallet to ${net.name} first, then tap again.`); return;
    }
    btn.disabled = true;
    try {
        const ok = await withWalletRedirect(state.provider, () => provider.request({
            method: 'wallet_watchAsset',
            params: { type: 'ERC20', options: { address: addr, symbol: XERA_TOKEN_SYMBOL, decimals: XERA_TOKEN_DECIMALS, image: XERA_TOKEN_LOGO } },
        }));
        say(ok ? 'XERA added to your wallet.' : 'Not added — you can tap again any time.');
    } catch (err) {
        if (err && err.code === 4001) say('Cancelled in your wallet.');
        else await copyFallback('Your wallet couldn’t add it automatically.');
    } finally {
        btn.disabled = false;
    }
}

// After a successful claim, ask the wallet to start tracking XERA so the balance shows up without a manual step.
// Best effort: wallets that can't do it (or a declined prompt) just leave the "Add XERA to my wallet" button to use.
async function autoAddXeraAfterClaim() {
    try {
        const net = state.network;
        const addr = net && net.xera_token_address;
        if (!addr) return;
        let provider = state.provider && state.provider.provider;
        if (!provider) {
            const restored = await restoredAppKitProvider(net.chain_id, 3000);
            provider = restored && restored.provider;
        }
        if (!provider || typeof provider.request !== 'function') return;
        const chainId = await readChainId(provider, state.providerChainId);
        if (chainId != null && Number(chainId) !== Number(net.chain_id)) return;
        const ok = await withWalletRedirect(state.provider, () => provider.request({
            method: 'wallet_watchAsset',
            params: { type: 'ERC20', options: { address: addr, symbol: XERA_TOKEN_SYMBOL, decimals: XERA_TOKEN_DECIMALS, image: XERA_TOKEN_LOGO } },
        }));
        if (ok) setNotice('Moved on-chain. XERA has been added to your wallet.');
    } catch (_e) { /* declined or unsupported: the manual button still works */ }
}

function xeraTokenRow() {
    const net = state.network;
    if (!net || !net.xera_token_address) return null;
    const msg = h('p', { class: 'chain-token-msg', role: 'status', 'aria-live': 'polite' });
    const btn = h('button', { type: 'button', class: 'btn btn-sm chain-addtoken', text: 'Add XERA to my wallet' });
    btn.addEventListener('click', () => addXeraToWallet(btn, msg));
    return h('div', { class: 'chain-token-row' }, btn, msg);
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
        h('p', { class: 'chain-manual-hint', text: 'Public address only. A new address waits 12 hours, each withdrawal needs your password, and a wrong address can’t be recovered.' }),
    );
}

function manualWaitNote(w) {
    const ms = manualReadyMs(w);
    if (ms === null) return null;
    const left = ms - Date.now();
    return h('p', { class: `chain-gas-note ${left > 0 ? 'warn' : 'ok'}`,
        text: left > 0
            ? `Safety wait: ready in ${waitText(left)}.`
            : 'Ready for withdrawals.' });
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
        if (chain === 'BNB') { card.append(h('div', { id: 'chainProviderPicker', class: 'chain-picker', hidden: !state.pickerOpen })); const tr = xeraTokenRow(); if (tr) card.append(tr); }
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
        if (chain === 'BNB') { card.append(h('div', { id: 'chainProviderPicker', class: 'chain-picker', hidden: !state.pickerOpen })); const tr = xeraTokenRow(); if (tr) card.append(tr); }
        return;
    }

    // ---- manual (unverified)
    card.append(
        walletCardHeader(chain, 'Manual address · not verified', 'warn'),
        addressRow(w),
        h('p', { class: 'chain-manual-hint', text: 'Saved. Withdrawals ask for your password. You confirm with any wallet that has a little BNB for the network fee; your XERA goes to this address.' }),
        manualWaitNote(w),
        h('div', { class: 'chain-actions' },
            connectBtn('Verify with wallet'),
            h('button', { type: 'button', class: 'btn btn-sm btn-ghost', disabled: busy, text: 'Change', onclick: () => { state.manualFormOpen[chain] = !state.manualFormOpen[chain]; renderWalletCard(chain); } }),
            h('button', { type: 'button', class: 'btn btn-sm btn-ghost', disabled: busy, text: 'Remove', onclick: () => removeWallet(chain, false) }),
        ),
    );
    if (state.manualFormOpen[chain]) card.append(manualForm(chain, w));
    if (chain === 'BNB') { card.append(h('div', { id: 'chainProviderPicker', class: 'chain-picker', hidden: !state.pickerOpen })); const tr = xeraTokenRow(); if (tr) card.append(tr); }
}

function setBusy(chain, value) {
    state.busy[chain] = value;
    renderWalletCard(chain);
}

async function refreshWallets() {
    try {
        const { wallets } = await req(PFX + '/wallet/linked');
        state.wallets = { BNB: null, TON: null };
        for (const w of wallets) state.wallets[w.chain] = w;
        refreshGasNote();
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
        const res = await req(PFX + '/wallet/manual', { method: 'POST', body: JSON.stringify({ chain, address: value }) });
        state.manualFormOpen[chain] = false;
        setNotice(res.notice || 'Wallet address saved. You can withdraw to it after a safety waiting period, with your password.');
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
        await req(`${PFX}/wallet/${chain}`, { method: 'DELETE' });
        if (chain === 'TON' && tonUI && tonUI.connected) { try { await tonUI.disconnect(); } catch (_e) { /* wallet session already gone */ } }
        if (chain === 'BNB') { state.provider = null; state.providerChainId = null; renderNetworkBanner(); await disconnectAppKit(); }
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

        // Preferred: the wallet picker (lists wallets, deep links on mobile, QR on desktop).
        let pickerProblem = appKitConfigured() ? '' : 'not_configured';
        if (appKitConfigured()) {
            let picked = null;
            markLinkPending();
            trace('Tapped connect: opening the wallet picker');
            try {
                const linkedNow = state.wallets.BNB && state.wallets.BNB.verified ? state.wallets.BNB.address : '';
                // On a phone the picker closes while the wallet app opens. We keep waiting for the wallet and
                // only stop when the user taps Cancel (see showWaitingForWallet).
                picked = await connectWithAppKit(state.network && state.network.chain_id, linkedNow, { onPickerClosed: showWaitingForWallet });
            } catch (err) {
                clearWaitingForWallet();
                if (err && err.cancelled) { trace('Wallet connection cancelled'); clearLinkPending(); return; }
                if (err && err.userFacing) { trace('Stopped: ' + err.message); clearLinkPending(); throw err; }   // e.g. "that's the wallet already linked"
                pickerProblem = 'failed';
                console.warn('Wallet picker unavailable, falling back to browser wallet', err);
            }
            clearWaitingForWallet();
            if (picked) {
                trace(`Wallet connected: ${shorten(picked.address)}`);
                await linkWithProvider({ info: { uuid: 'appkit', name: 'WalletConnect', icon: '' }, provider: picked.provider, appkit: true, chainId: picked.chainId }, picked.address, picked.chainId);
                clearLinkPending();
                return;
            }
        }

        const providers = await discoverProviders();
        if (!providers.length) {
            if (pickerProblem) console.warn(pickerProblem === 'not_configured'
                ? 'XERA wallet picker is off: VITE_REOWN_PROJECT_ID was not set when this site was built.'
                : 'XERA wallet picker failed to open (check the Reown project domain allowlist and the console error above).');
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
        trace('Failed: ' + ((err && err.message) || err));
        clearLinkPending();
        setError(userMessage(err, 'Could not connect your BNB wallet. Please try again.'));
    } finally {
        if (!state.pickerOpen) { state.busy.BNB = false; await refreshWallets(); }
    }
}

// ---- waiting for the wallet app (phone) ----
// The picker closes as soon as a wallet is tapped and the wallet app can take a while to open and approve.
// We never treat that as a cancel: this notice stays until the wallet answers or the user taps Cancel.
let waitingShown = false;
function showWaitingForWallet() {
    const el = $('chainWalletNotice');
    if (!el) return;
    waitingShown = true;
    setNotice('Waiting for your wallet… approve the request in your wallet app, then come back to this page.');
    el.append(' ',
        h('button', { type: 'button', class: 'btn btn-sm btn-ghost', text: 'Pick another wallet', onclick: () => reopenAppKitPicker() }), ' ',
        h('button', { type: 'button', class: 'btn btn-sm btn-ghost', text: 'Cancel', onclick: () => { trace('You tapped Cancel'); cancelAppKitConnect(); } }));
}
function addWaitActions() {
    const el = $('chainWalletNotice');
    if (!el) return;
    el.append(' ',
        h('button', { type: 'button', class: 'btn btn-sm btn-ghost', text: 'Pick another wallet', onclick: () => reopenAppKitPicker() }), ' ',
        h('button', { type: 'button', class: 'btn btn-sm btn-ghost', text: 'Cancel', onclick: () => { trace('You tapped Cancel'); cancelAppKitConnect(); clearLinkPending(); setNotice(''); } }));
}
function clearWaitingForWallet() { if (waitingShown) { waitingShown = false; setNotice(''); } }

// Shown when the wallet is connected but the link was not completed: a button, so signing starts from a tap
// when it could not be started automatically.
function offerFinishLink(restored) {
    setNotice('Your wallet is connected but not saved to your account yet.');
    const el = $('chainWalletNotice');
    const b = h('button', { type: 'button', class: 'btn btn-sm', text: 'Finish connecting', onclick: async () => {
        b.disabled = true; clearMessages(); clearLinkPending(); setBusy('BNB', true);
        try {
            const now = (await restoredAppKitProvider(state.network && state.network.chain_id, 4000)) || restored;     // fresh, not the one saved earlier
            await linkWithProvider({ info: { uuid: 'appkit', name: 'WalletConnect', icon: '' }, provider: now.provider, appkit: true, chainId: now.chainId }, now.address, now.chainId);
        }
        catch (err) { setError(userMessage(err, 'Could not finish connecting your wallet. Tap “Change wallet” and try again.')); }
        finally { state.busy.BNB = false; await refreshWallets(); }
    } });
    el.append(' ', b);
}

// The wallet app sent the user back and the page was reloaded (or only came to the foreground) while a link
// was in progress: finish it. Order: (1) a signature we already collected is just sent; (2) a restored wallet
// session is asked to sign ONCE automatically; (3) if that does not work, a "Finish connecting" button.
let resumingLink = false;
let signInFlight = false;       // a sign-in request is already waiting in the wallet: never send a second one on top of it
const LINK_AUTO_KEY = 'xera_bnb_link_auto';
function pendingStamp() { try { return localStorage.getItem(LINK_PENDING_KEY) || ''; } catch (_e) { return ''; } }
function autoAlreadyTried() { try { return localStorage.getItem(LINK_AUTO_KEY) === pendingStamp(); } catch (_e) { return true; } }
function markAutoTried() { try { localStorage.setItem(LINK_AUTO_KEY, pendingStamp()); } catch (_e) { /* ignore */ } }

async function resumePendingBnbLink() {
    if (resumingLink || state.busy.BNB || !linkPendingFresh() || !appKitConfigured()) return;
    if (signInFlight) { trace('A sign-in request is already waiting in your wallet app. Open it and approve.'); return; }
    resumingLink = true;
    trace('Back on the page while a wallet link was in progress');
    try {
        const st = readStash();
        if (st) {
            setBusy('BNB', true);
            setNotice('Finishing connecting your wallet…');
            try {
                await req(PFX + '/wallet/link/verify', { method: 'POST', body: JSON.stringify({ chain: 'BNB', address: st.address, nonce: st.nonce, signature: st.signature }) });
                trace('Saved: wallet verified');
                setNotice('BNB wallet connected and verified.');
            } catch (err) {
                setError(userMessage(err, 'Could not finish connecting your wallet. Tap “Change wallet” and try again.'));
            } finally { clearStash(); clearLinkPending(); state.busy.BNB = false; await refreshWallets(); }
            return;
        }
        await loadNetworkConfig();
        nudgeAppKitConnection();
        setNotice('Reconnecting to your wallet… this can take up to a minute.');
        addWaitActions();                                   // never a dead end: the user can always switch wallet or cancel
        const t0 = Date.now();
        const ticker = setInterval(() => trace(`Still looking for your wallet (${Math.round((Date.now() - t0) / 1000)}s)`), 15000);
        let restored;
        try { restored = await restoredAppKitProvider(state.network && state.network.chain_id, 45000); }
        finally { clearInterval(ticker); }
        if (!restored || !restored.address) {
            // Keep the pending mark and KEEP LOOKING (every few seconds, while this page is open and the link is still
            // fresh): the wallet app may still be answering, and a phone can take a while to bring its connection back.
            trace('No connected wallet found yet, will keep checking (' + appKitDiagnostics() + ')');
            setNotice('Still waiting for your wallet. Approve the request in your wallet app. We keep checking, no need to start again. Use a wallet that supports BNB Smart Chain (Trust Wallet, MetaMask, Binance Wallet, SafePal). TON-only wallets such as Tonkeeper cannot link a BNB address.');
            addWaitActions();
            setTimeout(() => { if (linkPendingFresh() && document.visibilityState === 'visible') resumePendingBnbLink(); }, 4000);
            return;
        }
        trace(`Found connected wallet: ${shorten(restored.address)}`);
        const same = (w) => w && w.verified && w.address && w.address.toLowerCase() === restored.address.toLowerCase();
        if (same(state.wallets.BNB)) { clearLinkPending(); return; }                      // already saved
        // The wallet app may have reopened the site in a second tab that is still finishing the link: give it a moment.
        for (let i = 0; i < 3 && linkPendingFresh(); i++) {
            await sleep(2500);
            await refreshWallets();
            if (same(state.wallets.BNB)) { clearLinkPending(); return; }
        }
        if (!linkPendingFresh()) return;
        if (!autoAlreadyTried()) {
            markAutoTried();
            trace('Asking your wallet to sign to finish the link');
            clearMessages(); setBusy('BNB', true);
            try {
                await linkWithProvider({ info: { uuid: 'appkit', name: 'WalletConnect', icon: '' }, provider: restored.provider, appkit: true, chainId: restored.chainId }, restored.address, restored.chainId);
                clearLinkPending();
            } catch (err) {
                trace('Signing did not finish: ' + ((err && err.message) || err));
                clearLinkPending();
                setError(userMessage(err, 'Could not finish connecting your wallet.'));
                offerFinishLink(restored);
            } finally { state.busy.BNB = false; await refreshWallets(); }
            return;
        }
        offerFinishLink(restored);
    } finally {
        resumingLink = false;
    }
}

// The page came back on the home screen. If a wallet link is waiting, open the wallet screen for the user
// (the on-chain switch loads asynchronously, so wait for it) and let openChainTab finish the link.
function returnToWalletScreen() {
    if (!linkPendingFresh() || CFG.autoOpen) return;
    let tries = 0;
    const timer = setInterval(() => {
        tries += 1;
        if (!linkPendingFresh() || tries > 200) { clearInterval(timer); return; }      // ~60 s
        if (window.__xeraOnchainEnabled === true && token()) {
            clearInterval(timer);
            const btn = $('openChainClaim');
            if (btn) btn.click();
        }
    }, 300);
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

async function linkWithProvider(entry, knownAddress, knownChainId) {
    let { provider } = entry;
    let address = knownAddress;
    if (!address) {
        const accounts = await provider.request({ method: 'eth_requestAccounts' });
        address = accounts && accounts[0];
    }
    if (!address) throw userError('Your wallet didn’t share an account. Unlock it and try again.');

    state.provider = entry;
    state.providerChainId = knownChainId || await readChainId(provider);
    attachProviderListeners(entry);
    renderNetworkBanner();

    // Linking proves ownership of the ADDRESS by signing a message — it moves no
    // funds and doesn't depend on the network, so a wrong network doesn't block it.
    // (It does block settling a claim; see settleClaim.)
    trace(`Asking the server for a sign-in code for ${shorten(address)}`);
    const nonceRes = await req(PFX + '/wallet/link/nonce', { method: 'POST', body: JSON.stringify({ chain: 'BNB', address }) });
    if (signInFlight) throw userError('A sign-in request is already waiting in your wallet app. Open your wallet and approve it.');
    if (entry.appkit) {                                    // use the connection as it is NOW, and make sure it is up
        const live = liveWalletSession();
        if (live && live.provider) { provider = live.provider; entry.provider = provider; }
        const up = await waitForRelay(4000);
        if (!up) trace('Connection to your wallet is slow to come back (' + appKitDiagnostics() + ')');
    }
    if (!provider || typeof provider.request !== 'function') {
        throw userError('Your wallet connection was lost while you were in your wallet app. Tap “Change wallet” and connect again.');
    }
    trace('Waiting for you to sign in your wallet app');
    // The sign-in request goes to the wallet app, but on a phone the wallet is not in front: bring it there, and
    // leave a button in case the phone blocks the automatic jump.
    const isPhone = /android|iphone|ipad|ipod/i.test(navigator.userAgent || '');
    setNotice('Step 2: open your wallet app and approve the sign-in request (it only proves you own this address and costs nothing).');
    const noticeEl = $('chainWalletNotice');
    if (noticeEl && isPhone) {
        noticeEl.append(' ', h('button', { type: 'button', class: 'btn btn-sm', text: 'Open my wallet', onclick: () => {
            const name = openChosenWalletApp();
            trace(name ? `Opening ${name} for you` : 'No wallet app link saved: open your wallet app yourself and look for the pending request');
        } }));
    }
    let openTimer = null;
    if (isPhone) {
        openTimer = setTimeout(() => {
            const name = openChosenWalletApp();
            trace(name ? `Opened ${name} so you can approve the request` : 'No wallet app link saved: open your wallet app yourself and look for the pending request');
        }, 2500);                                          // give the request time to leave the page before the wallet takes the screen
    }
    const t1 = Date.now();
    const waitTick = setInterval(() => trace(`Still waiting for the sign-in approval (${Math.round((Date.now() - t1) / 1000)}s; ${appKitDiagnostics()})`), 20000);
    let signature;
    signInFlight = true;
    try {
        const send = (pv) => pv.request({ method: 'personal_sign', params: [utf8ToHex(nonceRes.message_to_sign), address] });
        try { signature = await send(provider); }
        catch (err) {
            if (!(err instanceof TypeError)) throw err;     // "reading 'request'": the connection object went stale. Rebuild it once.
            trace('Wallet connection object was stale, reconnecting and trying once more');
            nudgeAppKitConnection(); await waitForRelay(4000); await sleep(800);
            const live = liveWalletSession();
            if (!live || !live.provider) throw userError('Your wallet connection was lost. Tap “Change wallet” and connect again.');
            signature = await send(live.provider);
        }
    } finally { signInFlight = false; clearTimeout(openTimer); clearInterval(waitTick); }
    trace('Signed. Saving to your account');
    stashSignature({ address: nonceRes.address || address, nonce: nonceRes.nonce, signature });
    try {
        await req(PFX + '/wallet/link/verify', { method: 'POST', body: JSON.stringify({ chain: 'BNB', address: nonceRes.address || address, nonce: nonceRes.nonce, signature }) });
    } finally { clearStash(); }
    trace('Saved: wallet verified');
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
            await req(PFX + '/wallet/link/verify', {
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
        const nonceRes = await req(PFX + '/wallet/link/nonce', { method: 'POST', body: JSON.stringify({ chain: 'TON' }) });
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

// A BNB wallet link that was started but not finished. On a phone, approving in the wallet app can reload the
// XERA page (it comes back on the home screen), which killed the in-progress link: the wallet connected but
// was never verified/saved, so the old wallet kept showing. We remember the link and finish it on return.
const LINK_PENDING_KEY = 'xera_bnb_link_pending';
const LINK_PENDING_TTL_MS = 15 * 60 * 1000;
function markLinkPending() { try { localStorage.setItem(LINK_PENDING_KEY, String(Date.now())); } catch (_e) { /* storage blocked */ } }
function clearLinkPending() { try { localStorage.removeItem(LINK_PENDING_KEY); } catch (_e) { /* ignore */ } }
function linkPendingFresh() {
    try { const t = Number(localStorage.getItem(LINK_PENDING_KEY) || 0); return t > 0 && Date.now() - t < LINK_PENDING_TTL_MS; }
    catch (_e) { return false; }
}
// A signature already collected from the wallet but not yet sent to the server. If the page reloads between
// the two, we send it instead of asking the wallet to sign again (which is what made it "keep redirecting").
const LINK_SIG_KEY = 'xera_bnb_link_sig';
function stashSignature(o) { try { localStorage.setItem(LINK_SIG_KEY, JSON.stringify({ ...o, t: Date.now() })); } catch (_e) { /* ignore */ } }
function readStash() { try { const o = JSON.parse(localStorage.getItem(LINK_SIG_KEY) || 'null'); return o && Date.now() - o.t < 4 * 60 * 1000 ? o : null; } catch (_e) { return null; } }
function clearStash() { try { localStorage.removeItem(LINK_SIG_KEY); } catch (_e) { /* ignore */ } }
// Step log for the wallet link. Kept in localStorage so it survives the page reload that happens when the wallet
// app sends the user back, and shown under the wallet card so a failure shows exactly which step was the last.
const TRACE_KEY = 'xera_link_trace';
function renderTrace() {
    const host = $('chainWalletNotice');
    if (!host || !host.parentNode) return;
    let el = $('chainLinkTrace');
    let rows = [];
    try { rows = JSON.parse(localStorage.getItem(TRACE_KEY) || '[]').filter((x) => Date.now() - x.t < 20 * 60 * 1000); } catch (_e) { rows = []; }
    if (!rows.length) { if (el) el.remove(); return; }
    if (!el) { el = h('pre', { id: 'chainLinkTrace', style: 'font-size:.68rem;opacity:.75;white-space:pre-wrap;margin:8px 0;word-break:break-word' }); host.parentNode.insertBefore(el, host.nextSibling); }
    el.textContent = 'Wallet link steps (send me this if it fails):\n' + rows.map((x) => `${new Date(x.t).toLocaleTimeString()}  ${x.m}`).join('\n');
}
function trace(msg) {
    try {
        const a = JSON.parse(localStorage.getItem(TRACE_KEY) || '[]');
        a.push({ t: Date.now(), m: String(msg).slice(0, 160) });
        localStorage.setItem(TRACE_KEY, JSON.stringify(a.slice(-16)));
    } catch (_e) { /* storage blocked */ }
    renderTrace();
}
window.addEventListener('xera-link-trace', (e) => trace(e.detail));
const PENDING_KEY = 'xera_pending_claim_txs'; // { [reference_id]: txHash } — survives a failed confirm call
function pendingTxs() { try { return JSON.parse(localStorage.getItem(PENDING_KEY) || '{}'); } catch (_e) { return {}; } }
function rememberPendingTx(ref, hash) { const m = pendingTxs(); m[ref] = hash; try { localStorage.setItem(PENDING_KEY, JSON.stringify(m)); } catch (_e) { /* storage full/blocked */ } }
function forgetPendingTx(ref) { const m = pendingTxs(); delete m[ref]; try { localStorage.setItem(PENDING_KEY, JSON.stringify(m)); } catch (_e) { /* ignore */ } }

const inFlight = new Set(); // reference_ids with a settle running in THIS tab (UX only — the backend enforces the real guard)

// ---------------------------------------------------------------- BNB for the network fee
// Users send the claim from their OWN wallet, so they pay the BNB gas fee themselves. We check the
// balance first so a user with no BNB sees a clear message instead of a raw wallet error. This is
// only a guard: if the balance can't be read we never block, and the wallet stays the authority.
// (Admin pilot mode uses the server's relayer, which pays gas, so none of this applies there.)
const MIN_BNB_FOR_GAS = 0.0005;

function fmtBnb(n) {
    if (n === 0) return '0';
    return n < 0.00001 ? '<0.00001' : Number(n.toFixed(5)).toString();
}

// Wallet provider first (works on any network the wallet is on), else a read-only public RPC for
// the configured network, which needs no wallet connection at all. Returns BNB as a number, or null.
async function readBnbBalance(address, provider) {
    const parse = (hex) => Number(BigInt(hex)) / 1e18;
    if (provider) {
        try { return parse(await provider.request({ method: 'eth_getBalance', params: [address, 'latest'] })); } catch (_e) { /* fall through */ }
    }
    const rpc = state.network && state.network.public_rpc_url;
    if (!rpc) return null;
    try {
        const r = await fetch(rpc, { method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'eth_getBalance', params: [address, 'latest'] }) });
        const d = await r.json();
        return d && typeof d.result === 'string' ? parse(d.result) : null;
    } catch (_e) { return null; }
}

function lowBnbMessage(balance, manual) {
    return `You need a little BNB for the network fee. Your wallet has ${fmtBnb(balance)} BNB. Add a small amount of BNB to ${manual ? 'the wallet you use to confirm the withdrawal (it pays the network fee)' : 'your linked wallet'}, then try again.`;
}

// Shows the wallet's BNB balance on the claim card and (user mode only) holds the button back when
// it is clearly too low. Never blocks when the balance is unknown.
async function refreshGasNote() {
    const el = $('chainGasNote');
    if (!el) return;
    const w = state.wallets.BNB;
    state.gasLow = false;
    if (CFG.relay || !w || (!w.verified && !isManual(w))) { el.hidden = true; updateClaimPreview(); return; }
    await loadNetworkConfig();
    if (isManual(w)) {
        // The wallet that pays the fee is only known once it is connected at withdrawal time, so no balance gate here.
        el.hidden = false;
        el.className = 'chain-gas-note ok';
        el.textContent = 'Network fee: you pay a small BNB fee from the wallet you use to confirm the withdrawal. Your XERA goes to the address you saved.';
        updateClaimPreview();
        return;
    }
    const bal = await readBnbBalance(w.address, null);
    if (bal === null) { el.hidden = true; updateClaimPreview(); return; }
    state.gasLow = bal < MIN_BNB_FOR_GAS;
    el.hidden = false;
    el.className = `chain-gas-note ${state.gasLow ? 'warn' : 'ok'}`;
    el.textContent = state.gasLow
        ? lowBnbMessage(bal, isManual(w))
        : `Network fee: you pay a small BNB fee from your own wallet${isManual(w) ? ' (the address you saved)' : ''}. Your wallet has ${fmtBnb(bal)} BNB.`;
    updateClaimPreview();
}

// ================= MOVE XERA TO YOUR WALLET (amount-based claims) =================
// The user chooses an amount. The backend debits it from the in-app balance and
// signs ONE single-use claim; the contract sends 25% to the wallet and locks 75%
// in vesting. The numbers shown here are a preview only — the server is the
// authority on balance, rounding and the split.

const signedClaims = new Map();   // reference_id -> signed claim, kept in memory so a closed wallet popup can be resumed

function trimNum(n, max = 4) { return Number(n).toLocaleString(undefined, { maximumFractionDigits: max }); }

// A balance floored to 2 decimals, via the string (never Math.round) so it can't round UP past what's available.
function floor2(n) { const [i, f = ''] = Number(n).toFixed(4).split('.'); return `${i}.${f.slice(0, 2)}`; }

// "12.5" -> 1250 (hundredths of a XERA), or null if it isn't a plain amount with at most 2 decimals.
function amountToCents(text) {
    const m = /^(\d{1,9})(?:\.(\d{1,2}))?$/.exec(String(text).trim());
    return m ? Number(m[1]) * 100 + Number((m[2] || '').padEnd(2, '0')) : null;
}

function updateClaimPreview() {
    const input = $('chainClaimAmount');
    const msg = $('chainClaimMsg');
    const split = $('chainClaimSplit');
    const submit = $('chainClaimSubmit');
    if (!input || !submit) return;
    const ov = state.claimOverview;
    const raw = input.value.trim();
    split.replaceChildren();
    msg.textContent = '';
    let ok = false;

    if (raw) {
        const cents = amountToCents(raw);
        const maxCents = ov ? amountToCents(floor2(ov.claimable)) : 0;
        const minCents = ov ? Math.round(ov.min_amount * 100) : 100;
        if (cents === null) msg.textContent = 'Enter a number with at most 2 decimals.';
        else if (cents <= 0) msg.textContent = 'Enter an amount above zero.';
        else if (cents < minCents) msg.textContent = `The minimum is ${trimNum(ov.min_amount)} XERA.`;
        else if (cents > maxCents) msg.textContent = 'That is more than your available balance.';
        else {
            ok = true;
            const total = cents / 100;
            const now = cents * 25 / 10000;
            split.append(
                h('div', { class: 'chain-split-box' }, h('span', { text: 'To your wallet now (25%)' }), h('b', { text: `${trimNum(now)} XERA` })),
                h('div', { class: 'chain-split-box' }, h('span', { text: 'Locked in vesting (75%)' }), h('b', { text: `${trimNum(total - now)} XERA` })),
            );
        }
    }
    submit.disabled = !ok || inFlight.has('amount') || (!CFG.relay && !!state.gasLow);
}

async function loadClaimables({ keepError = false } = {}) {
    if (!keepError) $('chainClaimError').textContent = '';
    const list = $('chainClaimableList');
    try {
        const ov = await req(PFX + '/claim/overview');
        state.claimOverview = ov;
        $('chainClaimableAmount').textContent = `${trimNum(ov.claimable)} Pure XERA`;
        list.replaceChildren();
        if (!ov.claims.length) {
            list.append(h('p', { class: 'chain-empty', text: 'Nothing moved yet. Claims you start will appear here with their status.' }));
        } else {
            for (const c of ov.claims) list.append(renderClaimRow(c));
        }
        updateClaimPreview();
        refreshGasNote();
    } catch (err) {
        $('chainClaimError').textContent = userMessage(err, 'Could not load your claimable balance. Please try again.');
    }
}

function renderClaimRow(c) {
    const ref = c.reference_id;
    const status = c.status;
    const date = c.created_at ? new Date(c.created_at).toLocaleDateString() : '';
    const split = `${trimNum(c.transferable_amount)} to wallet · ${trimNum(c.locked_amount)} locked`;
    const label = h('span', { class: 'chain-claim-label' },
        h('b', { text: `${trimNum(c.claimed_amount)} XERA` }),
        h('small', { text: `${date ? date + ' — ' : ''}${split}` }));
    const row = h('div', { class: 'chain-claim-row' }, label);

    if (status === 'CONFIRMED') {
        row.append(h('span', { class: 'chain-pill ok', text: `Settled on ${c.chain || 'chain'}` }));
        return row;
    }
    if (status === 'CANCELLED') {
        row.append(h('span', { class: 'chain-pill', text: 'Cancelled — refunded to your balance' }));
        return row;
    }

    const savedHash = pendingTxs()[ref];
    // A transaction we already sent can still be confirmed even if the signature window has since closed.
    if ((status === 'SIGNED' || status === 'SUBMITTED' || status === 'EXPIRED' || status === 'FAILED') && savedHash) {
        row.append(h('button', { type: 'button', class: 'btn btn-sm', text: 'Confirm settlement', onclick: () => confirmSaved(ref, savedHash) }));
        return row;
    }

    const cached = signedClaims.get(ref);
    const stillValid = cached && cached.deadline * 1000 > Date.now() + 30000;
    if (status === 'SIGNED' && stillValid) {
        const btn = h('button', { type: 'button', class: 'btn btn-sm', text: 'Continue in wallet', onclick: () => continueSigned(ref, btn) });
        row.append(btn);
        return row;
    }
    if (status === 'SIGNED' || status === 'SUBMITTED') {
        row.append(h('span', { class: 'chain-pill warn', text: 'In progress' }));
        return row;
    }
    // FAILED / EXPIRED: the funds are still held for this claim — re-sign the SAME claim.
    const btn = h('button', { type: 'button', class: 'btn btn-sm', text: 'Try again', onclick: () => retryClaim(ref, btn) });
    const cancelBtn = h('button', { type: 'button', class: 'btn btn-sm btn-ghost', text: 'Cancel', onclick: () => cancelClaim(ref, cancelBtn) });
    row.append(btn, ' ', cancelBtn);
    return row;
}

// Give an unfinished claim back to the in-app Pure XERA balance. The server only allows it once the old signature
// has expired and the contract confirms nothing was paid out. (It also happens by itself 2 hours after signing.)
async function cancelClaim(ref, btn) {
    $('chainClaimError').textContent = '';
    if (!window.confirm('Cancel this claim and return the XERA to your Pure XERA balance?')) return;
    btn.disabled = true;
    try {
        const res = await req(PFX + '/claim/cancel', { method: 'POST', body: JSON.stringify({ reference_id: ref }) });
        forgetPendingTx(ref);
        signedClaims.delete(ref);
        setNotice(res && res.refunded ? `Claim cancelled. ${res.refunded} XERA is back in your Pure XERA balance.` : 'Claim cancelled.');
        await Promise.all([loadClaimables(), loadVestingStatus()]);
    } catch (err) {
        $('chainClaimError').textContent = userMessage(err, 'Could not cancel this claim. Please try again in a moment.');
        btn.disabled = false;
    }
}

async function confirmSaved(ref, hash) {
    $('chainClaimError').textContent = '';
    try {
        await confirmClaimOnServer(ref, hash);
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

// Plain-English text for each first-transfer requirement (codes come from the server, python/xera/readiness.py).
const REQ_TEXT = {
    kyc_not_verified: 'Identity verification (KYC) is not complete.',
    fee_not_paid: 'The one-time first-transfer processing fee has not been paid.',
};

// Asks the server what is still missing BEFORE any wallet is touched or any balance reserved, so a user who
// can't move XERA yet is told exactly why instead of hitting a wallet error. The server re-checks on signing.
// Returns true when the user may continue. If the check itself can't be read, don't block: the server decides.
async function checkTransferReady(errEl) {
    let d;
    try { d = await req('/api/xera/readiness'); } catch (_e) { return true; }
    const missing = Array.isArray(d.missing) ? d.missing : [];
    if (!missing.length) return true;
    errEl.textContent = 'Before you can move Pure XERA to your wallet: ' + missing.map((c) => REQ_TEXT[c] || c).join(' ');
    if (window.XeraReadiness) window.XeraReadiness.showRequirements(missing);
    return false;
}

// The linked wallet is verified, but this visit has no live connection to it (page reloaded, or the
// WalletConnect session expired, or this browser has no wallet extension). Open the wallet picker so the
// user can reconnect it, and make sure it is the SAME wallet that is linked to the account.
async function reconnectLinkedWallet(wallet, { any = false } = {}) {
    if (!appKitConfigured()) return null;
    let picked;
    try {
        picked = await connectWithAppKit(state.network && state.network.chain_id);
    } catch (err) {
        if (err && err.cancelled) throw userError('Wallet connection was cancelled. Nothing was changed, and no XERA was reserved.');
        throw err;
    }
    if (!picked || !picked.address) return null;
    // any: a withdrawal to a typed address may be confirmed from any wallet (it only pays the network fee).
    if (!any && picked.address.toLowerCase() !== wallet.address.toLowerCase()) {
        throw userError(`That wallet (${shorten(picked.address)}) is not the one linked to your account (${shorten(wallet.address)}). Connect the linked wallet, or use “Change wallet” above to link this one.`);
    }
    return { info: { uuid: 'appkit', name: 'WalletConnect', icon: '' }, provider: picked.provider, appkit: true, chainId: picked.chainId, address: picked.address };
}

// Settlement, in order:
//   1. cheap local checks (chain supported, wallet connected & verified)
//   2. wallet on the right network (checked BEFORE the backend reserves anything)
//   3. backend reserves the amount (balance debited atomically) and signs it
//   4. user confirms the transaction in their wallet
//   5. backend independently verifies the transaction on-chain and only THEN marks it settled
async function settleWithWallet({ busyKey, button, idleLabel, fetchClaim, knownRef, amountText }) {
    const chain = $('chainSelect').value;
    const errEl = $('chainClaimError');
    errEl.textContent = '';
    clearMessages();

    // TON settlement isn't wired up. Check BEFORE asking the backend to sign:
    // signing reserves the amount, and reserving something we then can't
    // submit would hold it as "in progress" until the signature expires.
    if (chain !== 'BNB') {
        errEl.textContent = 'TON settlement is not yet available — please use BNB Smart Chain for now.';
        return;
    }

    const wallet = state.wallets.BNB;
    if (!wallet) { errEl.textContent = 'Your BNB wallet must be connected before you can move Pure XERA to it.'; return; }
    const manual = isManual(wallet);
    if (!wallet.verified && !manual) { errEl.textContent = 'Your BNB address was added manually and hasn’t been verified. Connect the wallet and sign the ownership request first.'; return; }

    // A typed address: explain the safety wait up front, then confirm the address and ask for the password
    // BEFORE anything is reserved. (Resuming an already-signed claim needs neither: the password was checked when it was signed.)
    let password = null;
    if (manual && !(knownRef && signedClaims.has(knownRef))) {
        const readyMs = manualReadyMs(wallet);
        if (readyMs === null || readyMs > Date.now()) {
            errEl.textContent = readyMs === null
                ? 'Your saved address is still in its safety waiting period. Please try again later.'
                : `For your safety, a newly added or changed address can receive XERA after a waiting period. Yours unlocks in ${waitText(readyMs - Date.now())}.`;
            return;
        }
        password = await confirmManualWithdraw(wallet, amountText);
        if (password === null) return;   // cancelled: nothing was changed
    }

    if (inFlight.has(busyKey)) return;
    inFlight.add(busyKey);
    if (button) { button.disabled = true; button.textContent = 'Preparing…'; }
    let referenceId = knownRef;

    try {
        // 0. Requirements first (KYC / one-time fee): explain what is missing before anything else happens.
        if (!CFG.relay && !(await checkTransferReady(errEl))) return;

        await loadNetworkConfig();
        let providers = await activeProviders();
        if (!providers.length) {
            // No live wallet connection: reconnect the linked wallet through the picker instead of dead-ending.
            if (button) button.textContent = 'Connect your wallet…';
            const again = await reconnectLinkedWallet(wallet, { any: manual });
            if (again) providers = [again];
        }
        if (!providers.length) throw userError('Your wallet is linked, but this browser can’t reach it right now. Tap “Change wallet” above to reconnect it, or open this page inside your wallet app’s browser (Trust Wallet, MetaMask, Binance…), then try again. Nothing was reserved.');
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
        if (!entry && manual) entry = providers[0];     // a typed address: any wallet can confirm and pay the fee
        if (!entry) throw userError('Several wallets are installed. Use “Change wallet” above to pick the one linked to this account, then try again.');

        // A withdrawal to a typed address is confirmed from WHICHEVER wallet the user connects: that wallet only
        // pays the network fee, the XERA always goes to the saved address (the contract sends it to the address in
        // the server-signed claim, whoever submits it). We only need a connected account that can pay.
        let payerAccount = null;
        if (manual) {
            let accts = await readAccounts(entry.provider);
            if (!accts.length && appKitConfigured()) {
                // The connection exists but shares no account (expired session): reconnect through the picker.
                if (button) button.textContent = 'Connect your wallet…';
                const again = await reconnectLinkedWallet(wallet, { any: true });
                if (again) { entry = again; accts = await readAccounts(entry.provider); if (!accts.length && again.address) accts = [again.address]; }
            }
            if (!accts.length) {
                throw userError('Your wallet is not sharing an account with this page yet. Open your wallet app, connect it to this site, then try again. Nothing was reserved.');
            }
            payerAccount = accts.find((a) => a.toLowerCase() === wallet.address.toLowerCase()) || accts[0];
        }
        state.provider = entry;
        attachProviderListeners(entry);
        state.providerChainId = await readChainId(entry.provider, entry.chainId);
        renderNetworkBanner();

        if (state.network && Number(state.providerChainId) !== Number(state.network.chain_id)) {
            throw userError(`Wrong network. Please switch your wallet to ${state.network.name} before continuing.`);
        }

        // Check BEFORE the server signs: signing reserves the amount, and a claim that can't be
        // sent for lack of gas would just sit as "in progress". Uses the account that will pay.
        if (!CFG.relay) {
            let payer = payerAccount || wallet.address;
            if (!payerAccount) {
                try {
                    const accts = await entry.provider.request({ method: 'eth_accounts' });
                    payer = accts.find((a) => a.toLowerCase() === wallet.address.toLowerCase()) || accts[0] || payer;
                } catch (_e) { /* keep the linked address */ }
            }
            const bal = await readBnbBalance(payer, entry.provider);
            if (bal !== null && bal < MIN_BNB_FOR_GAS) throw userError(lowBnbMessage(bal, manual));
        }

        if (button) button.textContent = 'Signing…';
        const claim = await fetchClaim(chain, password);
        referenceId = claim.reference_id || knownRef;
        signedClaims.set(referenceId, { ...claim, reference_id: referenceId });

        if (button) button.textContent = 'Confirm in wallet…';
        const { BrowserProvider, Contract } = await getEthers();
        const browserProvider = new BrowserProvider(entry.provider);
        const signer = await browserProvider.getSigner();
        const contract = new Contract(claim.contract_address, [DISTRIBUTOR_CLAIM_ABI], signer);
        const tx = await withWalletRedirect(entry, () => contract.claim(claim.user, claim.amount_wei, claim.reference_id_hash, claim.deadline, claim.signature));
        rememberPendingTx(referenceId, tx.hash);   // so a failed confirm call can be retried without re-sending

        if (button) button.textContent = 'Waiting for network…';
        await tx.wait();
        await confirmClaimOnServer(referenceId, tx.hash);
        forgetPendingTx(referenceId);
        signedClaims.delete(referenceId);
        setNotice(`Moved on-chain. Transaction ${shorten(tx.hash)}`);
        await autoAddXeraAfterClaim();
        window.open(explorerTx('BNB', tx.hash), '_blank', 'noopener');
        const amt = $('chainClaimAmount'); if (amt) amt.value = '';
    } catch (err) {
        errEl.textContent = userMessage(err, 'Could not complete this claim. Your XERA has not been lost — if it was reserved it appears under “Your on-chain claims” and you can continue or try again.');
    } finally {
        inFlight.delete(busyKey);
        if (button && idleLabel) { button.textContent = idleLabel; }
        // keepError: the refresh must not wipe the failure message we just showed.
        await Promise.all([loadClaimables({ keepError: true }), loadVestingStatus()]);
    }
}

// Admin pilot: the server's relayer wallet sends the transaction, so no wallet browser is needed.
// The backend reserves + signs the claim for THIS admin's verified wallet, simulates it, sends it,
// waits for it to mine and confirms it. Nothing is debited if the send is refused.
async function settleViaRelayer({ busyKey, button, idleLabel, body }) {
    const errEl = $('chainClaimError');
    errEl.textContent = '';
    clearMessages();
    if ($('chainSelect').value !== 'BNB') { errEl.textContent = 'Automatic sending supports BNB Smart Chain only for now. Please choose BNB.'; return; }
    const wallet = state.wallets.BNB;
    if (!wallet) { errEl.textContent = 'Your BNB wallet must be connected (or added) before you can move Pure XERA to it.'; return; }
    if (!wallet.verified) { errEl.textContent = 'Your BNB address was added manually and has not been verified. Connect the wallet and sign the ownership request first.'; return; }
    if (inFlight.has(busyKey)) return;
    inFlight.add(busyKey);
    if (button) { button.disabled = true; button.textContent = 'Sending…'; }
    try {
        const res = await req(PFX + '/claim/relay', { method: 'POST', body: JSON.stringify({ chain: 'BNB', ...body }) });
        if (res.confirmed) {
            setNotice(`Moved on-chain. Transaction ${shorten(res.transaction_hash)}`);
            await autoAddXeraAfterClaim();
            window.open(explorerTx('BNB', res.transaction_hash), '_blank', 'noopener');
            const amt = $('chainClaimAmount'); if (amt) amt.value = '';
        } else {
            rememberPendingTx(res.reference_id, res.transaction_hash);
            setNotice(`Sent (${shorten(res.transaction_hash)}). Waiting for the network; use “Confirm settlement” under your claims in a minute.`);
        }
    } catch (err) {
        errEl.textContent = userMessage(err, 'Could not send this claim. Your XERA has not been lost; see “Your on-chain claims”.');
    } finally {
        inFlight.delete(busyKey);
        if (button && idleLabel) { button.textContent = idleLabel; }
        await Promise.all([loadClaimables({ keepError: true }), loadVestingStatus()]);
    }
}

function settleAmount() {
    const input = $('chainClaimAmount');
    const text = input.value.trim();
    if (amountToCents(text) === null) { updateClaimPreview(); return; }
    if (CFG.relay) return settleViaRelayer({ busyKey: 'amount', button: $('chainClaimSubmit'), idleLabel: 'Move to wallet', body: { amount: text } });
    return settleWithWallet({
        busyKey: 'amount', button: $('chainClaimSubmit'), idleLabel: 'Move to wallet', amountText: text,
        fetchClaim: async (chain, password) => (await req(PFX + '/claim/sign-amount', { method: 'POST', body: JSON.stringify({ chain, amount: text, ...(password ? { password } : {}) }) })).claim,
    });
}

function retryClaim(referenceId, button) {
    if (CFG.relay) return settleViaRelayer({ busyKey: referenceId, button, idleLabel: 'Try again', body: { reference_id: referenceId } });
    return settleWithWallet({
        busyKey: referenceId, button, idleLabel: 'Try again', knownRef: referenceId,
        fetchClaim: async (chain, password) => (await req(PFX + '/claim/retry', { method: 'POST', body: JSON.stringify({ reference_id: referenceId, chain, ...(password ? { password } : {}) }) })).claim,
    });
}

// The wallet popup was closed before sending, but the signature is still valid: reuse it, no new reservation.
function continueSigned(referenceId, button) {
    return settleWithWallet({
        busyKey: referenceId, button, idleLabel: 'Continue in wallet', knownRef: referenceId,
        fetchClaim: async () => signedClaims.get(referenceId),
    });
}

// Minimal ABI fragment — just the one function the frontend calls directly.
const DISTRIBUTOR_CLAIM_ABI = 'function claim(address user,uint256 amount,bytes32 referenceId,uint256 deadline,bytes signature)';

// ================= VESTING STATUS =================

async function loadVestingStatus() {
    const chain = $('chainSelect').value;
    try {
        const { vesting } = await req(`${PFX}/onchain/status?chain=${chain}`);
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
    if (!block || CFG.noMigration) return;   // admin pilot has no legacy-migration step
    block.replaceChildren();
    try {
        const { migration } = await req(PFX + '/migration/status');
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
        const providers = await activeProviders();
        const entry = providers[0];
        if (!entry) throw userError('No browser wallet detected. Open this page in a wallet-enabled browser to confirm the transaction.');
        state.providerChainId = await readChainId(entry.provider, entry.chainId);
        if (state.network && Number(state.providerChainId) !== Number(state.network.chain_id)) {
            throw userError(`Wrong network. Please switch your wallet to ${state.network.name} before continuing.`);
        }
        const { claim } = await req(PFX + '/migration/claim/prepare', { method: 'POST', body: JSON.stringify({ chain: 'BNB' }) });
        const { BrowserProvider, Contract } = await getEthers();
        const signer = await new BrowserProvider(entry.provider).getSigner();
        const abi = 'function claim(uint256 leafIndex,address account,uint256 amount,bytes32[] proof)';
        const contract = new Contract(claim.contract_address, [abi], signer);
        const account = await signer.getAddress();
        const tx = await withWalletRedirect(entry, () => contract.claim(claim.leaf_index, account, claim.amount_wei, claim.merkle_proof));
        await tx.wait();
        await req(PFX + '/migration/claim/confirm', { method: 'POST', body: JSON.stringify({ chain: 'BNB', transaction_hash: tx.hash }) });
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
    if (window.__xeraOnchainEnabled !== true) return; // on-chain claims switched off (onchain_enabled)
    clearMessages();
    await loadNetworkConfig();
    renderNetworkBanner();
    await refreshWallets();
    renderTrace();
    resumePendingBnbLink();
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

    const amountInput = $('chainClaimAmount');
    if (amountInput) {
        // Keep the field to digits and ONE dot, at most 2 decimals, so what the user sees is what is sent.
        amountInput.addEventListener('input', () => {
            let v = amountInput.value.replace(/[^0-9.]/g, '');
            const dot = v.indexOf('.');
            if (dot !== -1) v = v.slice(0, dot + 1) + v.slice(dot + 1).replace(/\./g, '').slice(0, 2);
            if (v !== amountInput.value) amountInput.value = v;
            updateClaimPreview();
        });
        amountInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); if (!$('chainClaimSubmit').disabled) settleAmount(); } });
    }
    $('chainClaimMax')?.addEventListener('click', () => {
        const ov = state.claimOverview;
        if (!ov) return;
        amountInput.value = Number(floor2(ov.claimable)) > 0 ? floor2(ov.claimable) : '';
        updateClaimPreview();
    });
    $('chainClaimSubmit')?.addEventListener('click', settleAmount);

    document.querySelectorAll('[data-tab="chain"], [data-goto="chain"]').forEach((btn) => {
        btn.addEventListener('click', () => { openChainTab(); });
    });
    if (CFG.autoOpen) openChainTab();
    returnToWalletScreen();
    // Back from the wallet app without a reload (tab was only in the background): finish the link too.
    document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') nudgeAppKitConnection(); if (document.visibilityState === 'visible' && linkPendingFresh()) { nudgeAppKitConnection(); resumePendingBnbLink(); } });
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initChainPanel);
} else {
    initChainPanel();
}
