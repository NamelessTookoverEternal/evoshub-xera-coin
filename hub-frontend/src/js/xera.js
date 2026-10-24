const API = window.XERA_API_BASE || (import.meta.env && import.meta.env.VITE_API_BASE_URL) || ((location.hostname === 'localhost' || location.hostname === '127.0.0.1') ? 'http://localhost:8000' : 'https://api.evoshub.xyz');
const $ = (id) => document.getElementById(id);
const RING_CIRCUMFERENCE = 339.29; // 2 * PI * 54

let mining = null;
let dailyData = null;
let tickHandle = null;

import { safeNext, isExpired, notifyAuthChange } from './evos-session.js';
import { mountGuestBanner, requireAuthFor } from './guest-access.js';
import { maybeShowWelcome, startMiningWithOnboarding, resetLaunchSession } from './xera-launch.js';
import { initReadiness, resetReadiness } from './xera-readiness.js';

const token = () => localStorage.getItem('xera_evos_token') || '';
const fmt = (n) => Number(n || 0).toLocaleString('en-US', { maximumFractionDigits: 2 });

async function req(path, opts = {}) {
    const r = await fetch(API + path, {
        ...opts,
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token()}`, ...(opts.headers || {}) }
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) {
        const err = new Error(typeof d.detail === 'string' && d.detail ? d.detail : 'Request failed');
        err.status = r.status;
        err.code = typeof d.code === 'string' ? d.code : '';
        throw err;
    }
    return d;
}

// ================= GUEST MODE =================
// Sign-in lives on the shared Hub page (/login). XERA is open to guests: they can browse the
// dashboard and the public hashrate plans. Anything personal (mining, wallet, activity,
// rewards, profile, buying) asks them to sign in and then returns them here. The backend
// enforces the same rules; this only decides what to show.
const isGuest = () => !token() || isExpired(token());
const askSignIn = (action) => requireAuthFor(action, { next: '/xera' });
const GATED_TABS = { wallet: 'view your wallet', activity: 'see your activity', rewards: 'see your rewards', profile: 'view your profile' };
let signedIn = false;

function clearSession() {
    resetLaunchSession();
    resetReadiness();
    ['xera_evos_token', 'xera_evos_user', 'user', 'email', 'username', 'user_id', 'userToken', 'agentToken']
        .forEach((k) => { try { localStorage.removeItem(k); } catch (e) { /* ignore */ } });
    try { sessionStorage.removeItem('agentToken'); } catch (e) { /* ignore */ }
    notifyAuthChange();
}

function enterGuestMode() {
    signedIn = false;
    $('walletView').hidden = false;
    $('walletView').style.display = 'flex';
    ['balance', 'balanceWallet'].forEach((id) => { if ($(id)) $(id).textContent = '—'; });
    ['dailyPanel', 'rewardsMiniDash'].forEach((id) => { if ($(id)) $(id).hidden = true; });
    mining = null;
    renderMining();
    mountGuestBanner();
    loadHashrate(); // plans are public; sessions and buying need an account
}

// ================= TABS =================

function switchTab(name) {
    if (isGuest() && GATED_TABS[name]) { askSignIn(GATED_TABS[name]); return; }
    document.querySelectorAll('.tab-panel').forEach((p) => p.classList.toggle('active', p.dataset.panel === name));
    document.querySelectorAll('.tab-nav-item').forEach((b) => b.classList.toggle('active', b.dataset.tab === name));
    document.querySelectorAll('.bottom-tab-item').forEach((b) => b.classList.toggle('active', b.dataset.tab === name));
    $('walletView').querySelector('.scroll').scrollTop = 0;
    if (name === 'wallet') loadWalletTotals();
    if (name === 'hashrate' && token()) loadHashrate();
    if (name === 'rewards' && token()) loadReferral();
}

document.querySelectorAll('[data-tab]').forEach((btn) => btn.addEventListener('click', () => switchTab(btn.dataset.tab)));
document.querySelectorAll('[data-goto]').forEach((btn) => btn.addEventListener('click', () => switchTab(btn.dataset.goto)));

// ================= ACTIVITY =================

const TX_ICONS = {
    MINING_REWARD: '<svg viewBox="0 0 24 24" fill="none"><path d="M13 2L4 14h6l-1 8 9-12h-6l1-8z" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/></svg>',
    ADMIN_CREDIT: '<svg viewBox="0 0 24 24" fill="none"><path d="M12 5v14M5 12h14" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>',
    ADMIN_DEBIT: '<svg viewBox="0 0 24 24" fill="none"><path d="M5 12h14" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>',
    DAILY_CLAIM: '<svg viewBox="0 0 24 24" fill="none"><path d="M12 3v4M12 17v4M5 12H3M21 12h-2M6.3 6.3 4.9 4.9M19.1 19.1l-1.4-1.4M6.3 17.7l-1.4 1.4M19.1 4.9l-1.4 1.4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><circle cx="12" cy="12" r="4" stroke="currentColor" stroke-width="1.8"/></svg>',
    DEFAULT: '<svg viewBox="0 0 24 24" fill="none"><path d="M13 2L4 14h6l-1 8 9-12h-6l1-8z" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/></svg>',
};
const TX_LABELS = {
    MINING_REWARD: '⛏ Mining reward',
    XERA_PURCHASE: 'XERA purchase',
    REFERRAL_REWARD: 'Referral reward',
    BONUS: 'Bonus',
    DAILY_CLAIM: '☀ Daily claim',
    ADMIN_CREDIT: 'Balance adjustment',
    ADMIN_DEBIT: 'Balance adjustment',
    REVERSAL: 'Reversal',
    MIGRATION: 'Migration',
};
const EMPTY_ICON = '<svg viewBox="0 0 24 24" fill="none"><path d="M3 12h4l3 8 4-16 3 8h4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>';

function renderTransactions(list, targetId = 'transactions') {
    const el = $(targetId);
    if (!el) return;
    if (!list.length) {
        el.innerHTML = `<div class="empty">${EMPTY_ICON}<p>No activity yet — start mining to see it here.</p></div>`;
        return;
    }
    el.innerHTML = list.map((x) => {
        const isCredit = x.direction === 'CREDIT';
        const label = TX_LABELS[x.type] || x.type.replaceAll('_', ' ').toLowerCase().replace(/^\w/, (c) => c.toUpperCase());
        const icon = TX_ICONS[x.type] || TX_ICONS.DEFAULT;
        const when = new Date(x.created_at).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
        return `<div class="activity-row">
            <div class="activity-icon ${isCredit ? '' : 'debit'}">${icon}</div>
            <div class="activity-mid"><div class="t">${label}</div><div class="d">${when}</div></div>
            <div class="activity-amt ${isCredit ? 'credit' : ''}">${isCredit ? '+' : '-'}${fmt(x.amount)}<span class="st">${x.status.toLowerCase()}</span></div>
        </div>`;
    }).join('');
}

// ================= STATS MODAL =================

async function openStats() {
    $('statsModal').hidden = false;
    $('statsError').textContent = '';
    ['statTotalSupply', 'statMinedSupply', 'statRemainingSupply', 'statTotalMiners', 'statYourMined', 'statYourBalance']
        .forEach((id) => { $(id).textContent = '…'; });

    try {
        const [pub, wallet, txs] = await Promise.all([
            fetch(API + '/api/xera/public/stats').then((r) => r.json()),
            req('/api/xera/wallet'),
            req('/api/xera/transactions?limit=100&offset=0'),
        ]);

        $('statTotalSupply').textContent = `${fmt(pub.initial_target)} XERA`;
        $('statMinedSupply').textContent = `${fmt(pub.mining_distributed)} XERA`;
        $('statRemainingSupply').textContent = `${fmt(pub.mining_allocation_remaining)} XERA`;
        $('statTotalMiners').textContent = fmt(pub.active_miners);

        const yourMined = (txs.transactions || [])
            .filter((t) => t.type === 'MINING_REWARD' && t.direction === 'CREDIT')
            .reduce((sum, t) => sum + Number(t.amount || 0), 0);
        $('statYourMined').textContent = `${fmt(yourMined)} XERA`;
        $('statYourBalance').textContent = `${fmt(wallet.balance)} XERA`;
    } catch (err) {
        $('statsError').textContent = 'Could not load statistics right now.';
    }
}

// ================= WALLET TAB =================

let walletTotalsLoaded = false;
async function loadWalletTotals() {
    if (walletTotalsLoaded) return;
    try {
        const [pub, txs] = await Promise.all([
            fetch(API + '/api/xera/public/stats').then((r) => r.json()),
            req('/api/xera/transactions?limit=100&offset=0'),
        ]);
        const earned = (txs.transactions || [])
            .filter((t) => t.direction === 'CREDIT')
            .reduce((sum, t) => sum + Number(t.amount || 0), 0);
        $('totalEarned').textContent = `${fmt(earned)} XERA`;
        $('walletRemainingSupply').textContent = `${fmt(pub.mining_allocation_remaining)} XERA`;
        walletTotalsLoaded = true;
    } catch (err) {
        $('totalEarned').textContent = '—';
        $('walletRemainingSupply').textContent = '—';
    }
}

// ================= PROFILE / APPEARANCE =================

function renderProfile() {
    let user = {};
    try { user = JSON.parse(localStorage.getItem('xera_evos_user') || '{}'); } catch (e) { /* ignore */ }
    $('profileName').textContent = user.full_name || '—';
    $('profileUsername').textContent = user.username || '—';
    $('profileEmail').textContent = user.email || '—';
}

$('logoutProfile').onclick = () => { doLogout(); };
$('profileOpenEcosystem').onclick = () => { $('ecosystemModal').hidden = false; loadEcosystem(); };
$('profileOpenStats').onclick = openStats;

// ================= WALLET / MINING =================

async function load() {
    try {
        const [w, m, t] = await Promise.all([
            req('/api/xera/wallet'),
            req('/api/xera/mining/status'),
            req('/api/xera/transactions?limit=20&offset=0')
        ]);
        signedIn = true;
        $('walletView').hidden = false;
        $('walletView').style.display = 'flex';

        $('balance').textContent = fmt(w.balance);
        $('balanceWallet').textContent = fmt(w.balance);
        $('walletStatus').innerHTML = `<span class="dot"></span>${w.wallet_status || 'ACTIVE'}`;
        $('walletStatusWallet').innerHTML = `<span class="dot"></span>${w.wallet_status || 'ACTIVE'}`;

        mining = m.mining;
        renderMining();
        const list = t.transactions || [];
        renderTransactions(list, 'transactions');
        renderTransactions(list.slice(0, 3), 'transactionsRecent');
        if (!tickHandle) tickHandle = setInterval(() => { if (mining) renderMining(); }, 1000);

        walletTotalsLoaded = false;
        renderProfile();
        loadDaily();
        if (!handlePaystackReturn()) loadHashrate();
        maybeShowWelcome(req);
        initReadiness({ req, getMining: () => mining, fmtDateTime });
    } catch (err) {
        clearSession();       // dead or rejected session: carry on as a guest
        enterGuestMode();
    }
}

// ================= DAILY CLAIM =================

async function loadDaily() {
    try {
        const d = await req('/api/xera/daily/status');
        dailyData = d.daily;
        renderDaily(dailyData);
    } catch (err) {
        dailyData = null;
        $('dailyPanel').hidden = true;
        $('rewardsMiniDash').hidden = true;
    }
}

function renderDaily(daily) {
    if (!daily || !daily.enabled) {
        $('dailyPanel').hidden = true;
        $('rewardsMiniDash').hidden = true;
        return;
    }

    // Mine tab card
    $('dailyPanel').hidden = false;
    $('dailyAmount').textContent = fmt(daily.reward_amount);
    $('dailyStreak').textContent = daily.streak > 0
        ? `${daily.streak}-day streak · ${daily.total_claims} total claims`
        : 'Claim daily to start a streak';

    // Dashboard mini card (same data, compact)
    $('rewardsMiniDash').hidden = false;
    $('dailyAmountDash').textContent = fmt(daily.reward_amount);
    $('dailyStreakDash').textContent = daily.streak > 0 ? `${daily.streak}-day streak` : 'Start a streak';

    // Rewards tab
    $('rewardsStreak').textContent = daily.streak || 0;
    $('rewardsTotalClaims').textContent = `${daily.total_claims || 0} total claims`;
    $('rewardsNextClaim').textContent = daily.can_claim
        ? 'Ready to claim now'
        : `Resets ${new Date(daily.next_reset_at).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}`;

    [$('dailyClaimBtn'), $('dailyClaimBtnDash')].forEach((btn) => {
        if (daily.can_claim) {
            btn.textContent = 'Claim';
            btn.classList.add('ready');
            btn.disabled = false;
        } else {
            btn.textContent = 'Claimed';
            btn.classList.remove('ready');
            btn.disabled = true;
        }
    });
    $('dailyNote').textContent = daily.can_claim ? '' : 'Come back tomorrow for your next claim.';
}

async function claimDaily(btn) {
    btn.disabled = true;
    $('dailyNote').textContent = '';
    try {
        await req('/api/xera/daily/claim', { method: 'POST', body: '{}' });
        const [w, t] = await Promise.all([
            req('/api/xera/wallet'),
            req('/api/xera/transactions?limit=20&offset=0'),
        ]);
        $('balance').textContent = fmt(w.balance);
        $('balanceWallet').textContent = fmt(w.balance);
        const list = t.transactions || [];
        renderTransactions(list, 'transactions');
        renderTransactions(list.slice(0, 3), 'transactionsRecent');
        walletTotalsLoaded = false;
        await loadDaily();
    } catch (err) {
        $('dailyNote').textContent = err.message;
        btn.disabled = false;
    }
}

$('dailyClaimBtn').onclick = () => claimDaily($('dailyClaimBtn'));
$('dailyClaimBtnDash').onclick = () => claimDaily($('dailyClaimBtnDash'));

// ================= ECOSYSTEM =================

async function loadEcosystem() {
    $('ecosystemError').textContent = '';
    $('ecosystemGrid').innerHTML = '<div class="empty"><p>Loading…</p></div>';
    try {
        const res = await fetch(API + '/api/xera/ecosystem');
        const d = await res.json();
        renderEcosystem(d.links || []);
    } catch (err) {
        $('ecosystemGrid').innerHTML = '';
        $('ecosystemError').textContent = 'Could not load the ecosystem directory right now.';
    }
}

function renderEcosystem(links) {
    if (!links.length) {
        $('ecosystemGrid').innerHTML = `<div class="empty">${EMPTY_ICON}<p>No ecosystem links yet.</p></div>`;
        return;
    }
    $('ecosystemGrid').innerHTML = '';
    links.forEach((link) => {
        const item = document.createElement('button');
        item.type = 'button';
        item.className = 'ecosystem-item';
        item.innerHTML = `<span class="ecosystem-logo"><img src="${link.image_url}" alt="" loading="lazy"></span><span class="ecosystem-name"></span>`;
        item.querySelector('.ecosystem-name').textContent = link.name; // textContent only — never innerHTML with admin-entered text
        item.addEventListener('click', () => window.open(link.url, '_blank', 'noopener'));
        $('ecosystemGrid').appendChild(item);
    });
}

// ================= MINING =================

function setRing(fraction, done) {
    const fg = $('ringFg');
    const offset = RING_CIRCUMFERENCE * (1 - Math.max(0, Math.min(1, fraction)));
    fg.style.strokeDashoffset = String(offset);
    fg.classList.toggle('done', !!done);
}

function setMiningSceneState(state) {
    const scene = $('miningScene');
    if (scene) scene.dataset.state = state;
}

function fmtDateTime(d) {
    return d.toLocaleString(undefined, { month: 'long', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit' });
}

function renderMining() {
    const btn = $('miningAction');
    const btnDash = $('miningActionDash');

    if (!mining) {
        setRing(0, false);
        setMiningSceneState('idle');
        $('countdown').textContent = '24:00:00';
        $('countdownDash').textContent = '24:00:00';
        $('ringCaption').textContent = 'Ready to start';
        $('ringCaptionDash').textContent = 'Ready to start';
        $('miningDotDash').className = 'mini-dot';
        $('rewardText').textContent = 'The server controls the mining timer.';
        $('rewardTextDash').textContent = '';
        $('miningMeta').hidden = true;
        [btn, btnDash].forEach((b) => { b.textContent = 'Start mining'; b.classList.remove('ready'); b.disabled = false; });
        return;
    }

    const start = new Date(mining.started_at).getTime();
    const end = new Date(mining.expires_at).getTime();
    const now = Date.now();
    const remain = end - now;
    const total = Math.max(end - start, 1);
    const fraction = 1 - Math.max(remain, 0) / total;
    const hours = Math.max(total / 3600000, 0.01);
    const ratePerHour = mining.estimated_reward / hours;

    $('miningMeta').hidden = false;
    $('miningRate').textContent = `${fmt(ratePerHour)} XERA/hour`;
    $('nextClaim').textContent = fmtDateTime(new Date(end));

    if (remain <= 0) {
        setRing(1, true);
        setMiningSceneState('ready');
        $('countdown').textContent = '00:00:00';
        $('countdownDash').textContent = '00:00:00';
        $('ringCaption').textContent = 'Session complete';
        $('ringCaptionDash').textContent = 'Session complete';
        $('miningDotDash').className = 'mini-dot ready';
        $('rewardText').innerHTML = `<b>Claimable: ${fmt(mining.estimated_reward)} XERA</b>`;
        $('rewardTextDash').innerHTML = `<b>Claimable: ${fmt(mining.estimated_reward)} XERA</b>`;
        [btn, btnDash].forEach((b) => { b.textContent = 'Claim XERA'; b.classList.add('ready'); b.disabled = false; });
    } else {
        setRing(fraction, false);
        setMiningSceneState('active');
        const s = Math.floor(remain / 1000);
        const h = String(Math.floor(s / 3600)).padStart(2, '0');
        const m = String(Math.floor((s % 3600) / 60)).padStart(2, '0');
        const sec = String(s % 60).padStart(2, '0');
        const clock = `${h}:${m}:${sec}`;
        $('countdown').textContent = clock;
        $('countdownDash').textContent = clock;
        $('ringCaption').textContent = 'Mining in progress';
        $('ringCaptionDash').textContent = 'Mining in progress';
        $('miningDotDash').className = 'mini-dot active';
        $('rewardText').textContent = `Estimated session reward: +${fmt(mining.estimated_reward)} XERA`;
        $('rewardTextDash').textContent = `Estimated session reward: +${fmt(mining.estimated_reward)} XERA`;
        [btn, btnDash].forEach((b) => { b.textContent = 'Mining active'; b.classList.remove('ready'); b.disabled = true; });
    }
}

async function refreshBalance() {
    try {
        const w = await req('/api/xera/wallet');
        $('balance').textContent = fmt(w.balance);
        $('balanceWallet').textContent = fmt(w.balance);
    } catch (e) { /* balance refreshes on the next load */ }
}

async function startOrClaim(btn, errEl) {
    if (!askSignIn('start mining')) return;
    errEl.textContent = '';
    btn.disabled = true;
    try {
        if (!mining) {
            // Agreement first (if the server requires it), then the real start call.
            const d = await startMiningWithOnboarding(req);
            if (!d) return; // user closed the agreement: nothing started
            mining = d.mining;
            refreshBalance(); // a bonus may have been credited
        } else {
            await req('/api/xera/mining/claim', { method: 'POST', body: JSON.stringify({ session_id: mining.id }) });
            mining = null;
            await load();
        }
        renderMining();
    } catch (e) {
        errEl.textContent = e.message;
    } finally {
        if (!(mining && new Date(mining.expires_at) > Date.now())) {
            $('miningAction').disabled = false;
            $('miningActionDash').disabled = false;
        }
    }
}


// ================= HASHRATE =================
const HASHRATE_ART = [
    {name:'Market Watcher', desc:'Tracks trends, finds opportunities, keeps XERA ahead.'},
    {name:'The Builder', desc:'More computing power. More block rewards.'},
    {name:'Global Strategist', desc:'Sees the bigger picture. Builds long-term value.'},
    {name:'The Accelerator', desc:'More speed. More power. More XERA.'},
    {name:'The Visionary', desc:'Leads today. Builds tomorrow.'},
];
const DAY_MS = 86400000;

let hashrateTiers = [];
let hashrateSessions = [];
let hashratePayments = { paystack: false, crypto: false };
let hashratePurchasing = false;
let hashrateLoading = null;
let hashratePollTimer = null;

// Escape anything that lands in innerHTML. Tier/session fields come from the
// API (admin-editable), so never interpolate them raw.
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

function hashCurrency(value, currency = 'GHS') {
    const n = Number(value || 0);
    return `${currency || 'GHS'} ${n.toLocaleString('en-US', { maximumFractionDigits: 2 })}`;
}

// ---- Visitor currency (display only) ----
// Prices are stored and billed in GHS (Paystack account currency). We show the visitor's
// local currency as a reference using the backend's rate; GHS is the fallback whenever the
// country/rate is unknown, so a made-up price is never shown.
const HASH_CUR_KEY = 'xera_hash_currency_v1';
const HASH_CUR_TTL = 60 * 60 * 1000;
let hashCur = { currency: 'GHS', rate: 1, converted: false, country: '' };
let hashCurPromise = null;

function loadHashCurrency() {
    if (hashCurPromise) return hashCurPromise;
    try {
        const c = JSON.parse(sessionStorage.getItem(HASH_CUR_KEY) || 'null');
        if (c && Date.now() - c.at < HASH_CUR_TTL) { hashCur = c.info; return (hashCurPromise = Promise.resolve(hashCur)); }
    } catch (e) { /* storage blocked */ }
    hashCurPromise = (async () => {
        try {
            let code = '';
            try {
                const ctrl = new AbortController();
                const t = setTimeout(() => ctrl.abort(), 2500);
                const r = await fetch('/api/country', { cache: 'no-store', signal: ctrl.signal });
                clearTimeout(t);
                if (r.ok) code = String((await r.json()).country || '').trim().toUpperCase();
            } catch (e) { /* edge unavailable: backend looks up the IP */ }
            const r = await fetch(`${API}/api/xera/hashrate/currency${/^[A-Z]{2}$/.test(code) ? `?country=${code}` : ''}`);
            const d = await r.json();
            if (r.ok && d && d.currency && Number(d.rate) > 0) {
                hashCur = { currency: d.currency, rate: Number(d.rate), converted: !!d.converted, country: d.country || code };
                try { sessionStorage.setItem(HASH_CUR_KEY, JSON.stringify({ at: Date.now(), info: hashCur })); } catch (e) { /* ignore */ }
            }
        } catch (e) { /* stay on GHS */ }
        return hashCur;
    })();
    return hashCurPromise;
}

/** {main, sub}: main is what the card shows; sub is the exact GHS charge when converted. */
function hashPriceParts(value, currency = 'GHS') {
    const ghs = hashCurrency(value, currency);
    if (!hashCur.converted || hashCur.currency === 'GHS' || (currency || 'GHS') !== 'GHS') return { main: ghs, sub: '' };
    const v = Number(value || 0) * hashCur.rate;
    try {
        const main = '≈ ' + new Intl.NumberFormat(undefined, {
            style: 'currency', currency: hashCur.currency, maximumFractionDigits: v >= 100 ? 0 : 2,
        }).format(v);
        return { main, sub: `Billed as ${ghs}` };
    } catch (e) {
        return { main: ghs, sub: '' };
    }
}

function setHashrateNotice(message) {
    const el = $('hashrateNotice');
    if (!el) return;
    el.textContent = message || '';
    el.hidden = !message;
}

function hashrateTierLabel(tierId) {
    const i = hashrateTiers.findIndex((t) => t.id === tierId);
    return (i >= 0 && HASHRATE_ART[i]) ? HASHRATE_ART[i].name : 'XERA Hashrate';
}

function renderHashrateState(state) {
    const cap = Number(state?.cap || 0);
    const reserved = Number(state?.reserved_amount || 0);
    const remaining = Number(state?.remaining ?? Math.max(cap - reserved, 0));
    const pct = cap ? Math.min(100, (reserved / cap) * 100) : 0;
    // Thresholds are admin-configurable in the DB — use the API's values and
    // only fall back to the documented defaults if an older backend omits them.
    const warnAt = Number(state?.warning_threshold || 65000000);
    const closeAt = Number(state?.closure_threshold || 70000000);

    $('hashrateAllocationText').textContent = `${fmt(reserved)} / ${fmt(cap)} XERA`;
    $('hashrateAllocationBar').style.width = `${pct}%`;
    $('hashrateRemaining').textContent = `${fmt(remaining)} XERA`;
    $('hashrateWarning').textContent = state?.warning_active ? 'ACTIVE' : `${fmt(Math.max(warnAt - reserved, 0))} left`;
    $('hashrateClosure').textContent = state?.free_mining_closed ? 'CLOSED' : `${fmt(Math.max(closeAt - reserved, 0))} left`;

    if (state?.free_mining_closed) {
        $('hashrateStatusNote').textContent = 'Free mining is closed. Hashrate purchases are still checked against the remaining allocation; a purchase is rejected if its full 30-day entitlement will not fit.';
    } else if (state?.warning_active) {
        $('hashrateStatusNote').textContent = `Final-phase warning: ${fmt(Math.max(closeAt - reserved, 0))} XERA remain before free mining closes.`;
    } else {
        $('hashrateStatusNote').textContent = 'The reservation engine checks the complete 30-day entitlement before accepting a hashrate purchase.';
    }
}

function renderHashrateCards(tiers, state) {
    const grid = $('hashrateGrid');
    const list = Array.isArray(tiers) ? tiers : [];
    grid.innerHTML = '';
    const remainingAlloc = Number(state?.remaining || 0);

    Array.from({ length: 5 }, (_, i) => i).forEach((i) => {
        const tier = list[i] || null;
        const art = HASHRATE_ART[i];
        const index = i + 1;
        const card = document.createElement('article');
        card.className = `hashrate-card${tier ? '' : ' unavailable'}`;

        const daily = tier ? Number(tier.daily_rate) : 0;
        const days = tier ? Number(tier.duration_days || 30) : 30;
        const maxReward = tier ? Number(tier.maximum_entitlement ?? daily * days) : 0;
        const fits = !!tier && !!tier.enabled && maxReward <= remainingAlloc;
        const canBuy = fits && (hashratePayments.paystack || hashratePayments.crypto);
        const pp = tier ? hashPriceParts(tier.price, tier.currency) : { main: 'Unavailable', sub: '' };

        let label = 'Buy Hashrate →';
        if (!tier) label = 'Coming soon';
        else if (!tier.enabled) label = 'Unavailable';
        else if (!fits) label = 'Allocation full';
        else if (!hashratePayments.paystack && !hashratePayments.crypto) label = 'Opening soon';

        card.innerHTML = `
          <div class="hashrate-card-art">
            <span class="hashrate-badge">0${index}</span>
            <img src="/assets/images/hashrate/hashrate-${index}.jpg" alt="XERA — ${esc(art.name)}" loading="lazy">
          </div>
          <div class="hashrate-card-body">
            <h3>${esc(art.name)}</h3>
            <p class="desc">${esc(art.desc)}</p>
            <div class="hashrate-stats">
              <div class="hashrate-stat"><span>Daily rate</span><b>${tier ? esc(fmt(daily)) + ' XERA' : '—'}</b></div>
              <div class="hashrate-stat"><span>Duration</span><b>${esc(days)} Days</b></div>
              <div class="hashrate-stat"><span>Max reward</span><b>${tier ? esc(fmt(maxReward)) + ' XERA' : '—'}</b></div>
            </div>
            <div class="hashrate-price">
              <div><small>Total price</small><strong>${esc(pp.main)}</strong>${pp.sub ? `<small class="hashrate-price-sub">${esc(pp.sub)}</small>` : ''}</div>
              <button class="hashrate-buy" type="button" ${canBuy ? '' : 'disabled'}>${esc(label)}</button>
            </div>
          </div>`;
        if (canBuy) {
            card.querySelector('.hashrate-buy').addEventListener('click', () => openHashratePurchase(tier, hashrateTierLabel(tier.id)));
        }
        grid.appendChild(card);
    });
}

function loadHashrate() {
    // Share one in-flight request so tab switches, load() and the post-payment
    // poll can't stack duplicate fetches (the endpoints are rate limited).
    if (!hashrateLoading) hashrateLoading = doLoadHashrate().finally(() => { hashrateLoading = null; });
    return hashrateLoading;
}

async function doLoadHashrate() {
    if (!$('hashrateGrid')) return;
    $('hashrateError').textContent = '';

    // allSettled: a failure loading the person's sessions must not hide the
    // plan cards (and vice versa).
    const [catalogRes, sessionsRes] = await Promise.allSettled([
        req('/api/xera/hashrate/tiers'),
        isGuest() ? Promise.resolve({ sessions: [], guest: true }) : req('/api/xera/hashrate/sessions'),
        loadHashCurrency(), // never rejects; resolves before the cards render so the price doesn't flip
    ]);

    if (catalogRes.status === 'fulfilled') {
        const catalog = catalogRes.value;
        hashrateTiers = catalog.tiers || [];
        hashratePayments = { paystack: !!catalog.payments?.paystack, crypto: !!catalog.payments?.crypto };
        renderHashrateState(catalog.entitlement || {});
        renderHashrateCards(hashrateTiers, catalog.entitlement || {});
    } else {
        $('hashrateGrid').innerHTML = '<div class="hashrate-loading">Hashrate plans are not available right now. The rest of XERA remains online.</div>';
        $('hashrateError').textContent = catalogRes.reason?.message || 'Could not load hashrate plans.';
    }

    if (sessionsRes.status === 'fulfilled') {
        hashrateSessions = sessionsRes.value.sessions || [];
        if (sessionsRes.value.guest) $('hashrateSessions').innerHTML = '<div class="empty"><p>Sign in to see your hashrate sessions.</p></div>';
        else renderHashrateSessions(hashrateSessions);
    } else if (catalogRes.status === 'fulfilled') {
        $('hashrateError').textContent = sessionsRes.reason?.message || 'Could not load your hashrate sessions.';
    }
}

// USDT (BNB Smart Chain) is the main rail; Paystack stays as the alternative.
// Resolves 'CRYPTO' | 'PAYSTACK' | null (cancelled). Only offers rails the server says are on.
function chooseHashratePayment(label, pp) {
    const { crypto, paystack } = hashratePayments;
    if (crypto && !paystack) return Promise.resolve(window.confirm(`Buy ${label} hashrate for ${pp.main}?\n\nYou'll pay in USDT on BNB Smart Chain (BEP-20). The exact USD amount is shown at checkout.`) ? 'CRYPTO' : null);
    if (!crypto) return Promise.resolve(window.confirm(`Buy ${label} hashrate for ${pp.main}?${pp.sub ? `\n(${pp.sub}; your bank converts at its own rate.)` : ''}\n\nYou'll be taken to Paystack to complete the payment.`) ? 'PAYSTACK' : null);
    return new Promise((resolve) => {
        const overlay = document.createElement('div');
        overlay.className = 'modal-overlay';
        overlay.innerHTML = `
          <div class="modal-card" role="dialog" aria-modal="true" aria-label="Choose payment method">
            <h2>Buy ${esc(label)} hashrate</h2>
            <p class="rd-fine">${esc(pp.main)}</p>
            <div class="modal-actions" style="display:flex;flex-direction:column;gap:10px;margin-top:14px">
              <button type="button" class="btn" data-m="CRYPTO">Pay with USDT (BNB Smart Chain)</button>
              <button type="button" class="btn btn-ghost" data-m="PAYSTACK">Pay with Paystack (card / mobile money)</button>
              <button type="button" class="btn btn-ghost" data-m="">Cancel</button>
            </div>
          </div>`;
        const done = (m) => { overlay.remove(); resolve(m || null); };
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) return done(null);
            const b = e.target.closest('button[data-m]');
            if (b) done(b.dataset.m);
        });
        document.body.appendChild(overlay);
    });
}

async function openHashratePurchase(tier, label) {
    if (!askSignIn('buy hashrate')) return;
    if (hashratePurchasing) return;
    $('hashrateError').textContent = '';
    const pp = hashPriceParts(tier.price, tier.currency);
    const method = await chooseHashratePayment(label, pp);
    if (!method) return;

    // One purchase at a time: every request reserves the full 30-day
    // entitlement server-side, so a double-click would park allocation twice.
    hashratePurchasing = true;
    document.querySelectorAll('.hashrate-buy').forEach((b) => { b.disabled = true; });
    setHashrateNotice('Starting secure checkout…');

    try {
        const d = await req('/api/xera/hashrate/purchase', {
            method: 'POST',
            body: JSON.stringify({ tier_id: tier.id, payment_method: method })
        });
        const url = d?.payment?.invoice_url || d?.payment?.authorization_url;
        if (typeof url !== 'string' || !url.startsWith('https://')) throw new Error('Payment session was not created.');
        window.location.href = url; // leave the buttons disabled while the browser navigates away
    } catch (err) {
        hashratePurchasing = false;
        setHashrateNotice('');
        await loadHashrate(); // re-render cards (re-enables Buy, refreshes allocation)
        $('hashrateError').textContent = err.message || 'Could not start the purchase.';
    }
}

// Mirrors xera_claim_hashrate_reward: rewards accrue in whole 24h periods
// from started_at, and the full amount unlocks once the session has expired.
function hashrateAccrual(s, now = Date.now()) {
    const start = new Date(s.started_at).getTime();
    const end = new Date(s.expires_at).getTime();
    const days = Number(s.duration_days || 30);
    const daily = Number(s.daily_rate || 0);
    const maxE = Number(s.maximum_entitlement || 0);
    const rewarded = Number(s.rewarded_amount || 0);
    const total = Math.max(end - start, 1);
    const elapsed = Math.max(0, Math.min(total, now - start));
    const elapsedDays = now >= end ? days : Math.floor(elapsed / DAY_MS);
    const accrued = Math.min(maxE, elapsedDays * daily);
    return { end, daily, rewarded, pct: Math.round((elapsed / total) * 100), claimable: Math.max(accrued - rewarded, 0) };
}

function renderHashrateSessions(sessions) {
    const el = $('hashrateSessions');
    if (!el) return;

    // Only sessions the person can act on: paid & running, or awaiting payment.
    // Failed / expired / cancelled / fully-claimed ones have nothing to show
    // (and a never-started session has no dates to render).
    const visible = sessions.filter((s) => s.status === 'ACTIVE' || s.status === 'PENDING_PAYMENT');
    if (!visible.length) {
        el.innerHTML = '<div class="empty"><p>No active hashrate sessions yet.</p></div>';
        return;
    }

    el.innerHTML = visible.map((s) => {
        const name = esc(hashrateTierLabel(s.tier_id));
        if (s.status === 'PENDING_PAYMENT') {
            return `<div class="hashrate-session">
              <div class="hashrate-session-head"><b>${name}</b><span class="hashrate-session-status pending">Awaiting payment</span></div>
              <p class="hashrate-session-note">Paid already? Activation follows Paystack's confirmation and usually takes under a minute.</p>
            </div>`;
        }
        const a = hashrateAccrual(s);
        return `<div class="hashrate-session">
          <div class="hashrate-session-head"><b>${name}</b><span class="hashrate-session-status">Active</span></div>
          <div class="hashrate-session-bar"><span style="width:${a.pct}%"></span></div>
          <div class="hashrate-session-meta">
            <div><span>Daily</span><b>${esc(fmt(a.daily))} XERA</b></div>
            <div><span>Claimed</span><b>${esc(fmt(a.rewarded))} XERA</b></div>
            <div><span>Ready to claim</span><b>${esc(fmt(a.claimable))} XERA</b></div>
          </div>
          <div class="hashrate-session-actions">
            <span class="hashrate-session-ends">Ends ${esc(new Date(a.end).toLocaleDateString())}</span>
            ${a.claimable > 0 ? `<button type="button" data-claim-hashrate="${esc(s.id)}">Claim ${esc(fmt(a.claimable))} XERA</button>` : ''}
          </div>
        </div>`;
    }).join('');

    el.querySelectorAll('[data-claim-hashrate]').forEach((btn) => btn.addEventListener('click', async () => {
        btn.disabled = true;
        $('hashrateError').textContent = '';
        try {
            await req(`/api/xera/hashrate/sessions/${encodeURIComponent(btn.dataset.claimHashrate)}/claim`, { method: 'POST', body: '{}' });
            await load(); // refreshes balance, activity and hashrate together
        } catch (e) {
            $('hashrateError').textContent = e.message;
            btn.disabled = false;
        }
    }));
}

// Paystack sends the customer back with ?reference=xera-hr-… (see
// XERA_HASHRATE_CALLBACK_URL on the backend). Activation happens via the
// webhook, so wait for it here instead of showing a stale "nothing yet" tab.
function handlePaystackReturn() {
    const params = new URLSearchParams(location.search);
    const ref = params.get('reference') || params.get('trxref') || '';
    // Paystack returns with ?reference=xera-hr-…; the USDT checkout returns with ?pay=crypto.
    if (!ref.startsWith('xera-hr-') && params.get('pay') !== 'crypto') return false;

    history.replaceState({}, '', location.pathname + location.hash);
    switchTab('hashrate');
    setHashrateNotice('Confirming your payment…');
    pollHashrateActivation(0);
    return true;
}

async function pollHashrateActivation(attempt) {
    clearTimeout(hashratePollTimer);
    await loadHashrate();
    if (!hashrateSessions.some((s) => s.status === 'PENDING_PAYMENT')) {
        setHashrateNotice(hashrateSessions.some((s) => s.status === 'ACTIVE') ? 'Payment confirmed — your hashrate is active.' : '');
        return;
    }
    if (attempt >= 12) {
        setHashrateNotice("Still waiting for the payment to confirm. Your hashrate activates automatically once it does — check back in a minute.");
        return;
    }
    hashratePollTimer = setTimeout(() => pollHashrateActivation(attempt + 1), 5000);
}

// ================= REFERRAL CARD (Rewards tab) =================

let referral = null;

function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) return navigator.clipboard.writeText(text);
    return new Promise((resolve, reject) => {
        const ta = document.createElement('textarea');
        ta.value = text; ta.setAttribute('readonly', ''); ta.style.position = 'fixed'; ta.style.opacity = '0';
        document.body.appendChild(ta); ta.select();
        try { document.execCommand('copy') ? resolve() : reject(new Error('copy failed')); }
        catch (e) { reject(e); } finally { document.body.removeChild(ta); }
    });
}

function inviteMessage(link) {
    return `Join me on XERA — free 24-hour mining and a wallet, by EVOXERA. Install the app and sign up with my invite: ${link}`;
}

function renderReferral() {
    if (!referral) return;
    $('refCode').textContent = referral.code;
    $('refShare').disabled = false;
    $('refWhatsApp').hidden = false;
    $('refWhatsApp').href = 'https://wa.me/?text=' + encodeURIComponent(inviteMessage(referral.link));

    $('refTotal').textContent = fmt(referral.stats.total);
    $('refQualified').textContent = fmt(referral.stats.qualified);
    $('refEarned').textContent = fmt(referral.stats.earned);

    const r = referral.rewards || {};
    $('refBlurb').textContent = (r.enabled && r.referrer_reward > 0)
        ? `Earn ${fmt(r.referrer_reward)} XERA when a friend you invite completes their first mining session` +
          (r.referee_reward > 0 ? ` — they get ${fmt(r.referee_reward)} XERA too.` : '.')
        : "Referral rewards aren't active yet. Friends who join through your link are still linked to you across the EVOS ecosystem.";

    const by = $('refInvitedBy');
    by.hidden = !referral.invited_by;
    if (referral.invited_by) by.textContent = `You joined through ${referral.invited_by}'s invite.`;

    const list = $('refRecent');
    list.replaceChildren();
    (referral.recent || []).forEach((p) => {
        const row = document.createElement('div');
        row.className = 'ref-row';
        const name = document.createElement('span');
        name.textContent = p.name;
        const st = document.createElement('small');
        st.textContent = (p.status === 'rewarded' || p.status === 'qualified') ? 'Active' : 'Joined';
        row.append(name, st);
        list.appendChild(row);
    });
}

async function loadReferral() {
    $('refError').textContent = '';
    try {
        referral = await req('/api/xera/referral/me');
        renderReferral();
    } catch (e) {
        $('refError').textContent = e.message;
    }
}

$('refCopyCode').onclick = async () => {
    if (!referral) return;
    try { await copyText(referral.code); $('refCopyCode').textContent = 'Copied'; }
    catch (e) { $('refCopyCode').textContent = 'Copy failed'; }
    setTimeout(() => { $('refCopyCode').textContent = 'Copy'; }, 1800);
};

$('refShare').onclick = async () => {
    if (!referral) return;
    const text = inviteMessage(referral.link);
    try {
        if (navigator.share) await navigator.share({ title: 'Join me on XERA', text });
        else { await copyText(text); $('refError').textContent = ''; $('refShare').textContent = 'Link copied'; setTimeout(() => { $('refShare').textContent = 'Share invite link'; }, 1800); }
    } catch (e) { /* share sheet dismissed */ }
};

// ================= EVENTS =================

function doLogout() {
    clearInterval(tickHandle);
    tickHandle = null;
    clearTimeout(hashratePollTimer);
    hashrateSessions = [];
    mining = null;
    dailyData = null;
    walletTotalsLoaded = false;
    clearSession();
    location.replace('/xera');
}

$('openMiningInfo').onclick = () => { $('miningInfoModal').hidden = false; };
$('closeMiningInfo').onclick = () => { $('miningInfoModal').hidden = true; };
$('closeMiningInfoBtn').onclick = () => { $('miningInfoModal').hidden = true; };
$('miningInfoModal').addEventListener('click', (e) => { if (e.target.id === 'miningInfoModal') $('miningInfoModal').hidden = true; });

$('closeStats').onclick = () => { $('statsModal').hidden = true; };
$('statsModal').addEventListener('click', (e) => { if (e.target.id === 'statsModal') $('statsModal').hidden = true; });

$('closeEcosystem').onclick = () => { $('ecosystemModal').hidden = true; };
$('ecosystemModal').addEventListener('click', (e) => { if (e.target.id === 'ecosystemModal') $('ecosystemModal').hidden = true; });

$('miningAction').onclick = () => startOrClaim($('miningAction'), $('error'));
$('miningActionDash').onclick = () => startOrClaim($('miningActionDash'), $('errorDash'));

// ================= BOOT =================
const bootParams = new URLSearchParams(location.search);

// Signed in on another tab (or out): reflect it here.
window.addEventListener('storage', (e) => {
    if (e.key !== 'xera_evos_token' && e.key !== null) return;
    if (signedIn && !token()) location.replace('/xera');
    else if (!signedIn && token()) location.reload();
});

if (!token() && (bootParams.has('next') || bootParams.has('mode') || bootParams.has('ref'))) {
    location.replace('/login' + location.search);        // old sign-in / invite links
} else if (token() && !isExpired(token())) {
    const back = safeNext(bootParams.get('next') || '', '');
    if (back && new URL(back, location.origin).pathname.replace(/\/+$/, '') !== '/xera') location.replace(back);
    else load();
} else {
    if (token()) clearSession();                          // expired
    enterGuestMode();
}

