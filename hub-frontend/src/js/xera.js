const API = window.XERA_API_BASE || ((location.hostname === 'localhost' || location.hostname === '127.0.0.1') ? 'http://localhost:8000' : 'https://api.evoshub.xyz');
const $ = (id) => document.getElementById(id);
const RING_CIRCUMFERENCE = 339.29; // 2 * PI * 54

let mining = null;
let tickHandle = null;

const token = () => localStorage.getItem('xera_evos_token') || '';
const fmt = (n) => Number(n || 0).toLocaleString('en-US', { maximumFractionDigits: 2 });

async function req(path, opts = {}) {
    const r = await fetch(API + path, {
        ...opts,
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token()}`, ...(opts.headers || {}) }
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.detail || 'Request failed');
    return d;
}

// ================= AUTH VIEW (login / register tabs) =================

function showAuthTab(tab) {
    const isLogin = tab === 'login';
    $('tabLogin').classList.toggle('active', isLogin);
    $('tabRegister').classList.toggle('active', !isLogin);
    $('tabLogin').setAttribute('aria-selected', String(isLogin));
    $('tabRegister').setAttribute('aria-selected', String(!isLogin));
    $('loginForm').hidden = !isLogin;
    $('registerForm').hidden = isLogin;
    $('loginError').textContent = '';
    $('registerError').textContent = '';
}

function showLogin(message) {
    localStorage.removeItem('xera_evos_token');
    $('walletView').hidden = true;
    $('walletView').style.display = 'none';
    $('authView').hidden = false;
    showAuthTab('login');
    if (message) $('loginError').textContent = message;
}

async function login(e) {
    e.preventDefault();
    $('loginError').textContent = '';
    const btn = e.target.querySelector('button[type="submit"]');
    btn.disabled = true;
    try {
        const d = await req('/api/xera/auth/login', {
            method: 'POST',
            body: JSON.stringify({ identifier: $('identifier').value, password: $('password').value })
        });
        localStorage.setItem('xera_evos_token', d.token);
        localStorage.setItem('xera_evos_user', JSON.stringify(d.user));
        await load();
    } catch (err) {
        $('loginError').textContent = err.message;
    } finally {
        btn.disabled = false;
    }
}

async function register(e) {
    e.preventDefault();
    $('registerError').textContent = '';

    const password = $('regPassword').value;
    const password2 = $('regPassword2').value;
    if (password !== password2) {
        $('registerError').textContent = "Passwords don't match.";
        return;
    }

    const btn = e.target.querySelector('button[type="submit"]');
    btn.disabled = true;
    try {
        const d = await req('/api/xera/auth/register', {
            method: 'POST',
            body: JSON.stringify({
                full_name: $('regFullName').value,
                username: $('regUsername').value,
                email: $('regEmail').value,
                password,
            })
        });
        localStorage.setItem('xera_evos_token', d.token);
        localStorage.setItem('xera_evos_user', JSON.stringify(d.user));
        await load();
    } catch (err) {
        $('registerError').textContent = err.message;
    } finally {
        btn.disabled = false;
    }
}

// ================= ACTIVITY =================

const TX_ICONS = {
    MINING_REWARD: '<svg viewBox="0 0 24 24" fill="none"><path d="M13 2L4 14h6l-1 8 9-12h-6l1-8z" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/></svg>',
    ADMIN_CREDIT: '<svg viewBox="0 0 24 24" fill="none"><path d="M12 5v14M5 12h14" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>',
    ADMIN_DEBIT: '<svg viewBox="0 0 24 24" fill="none"><path d="M5 12h14" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>',
    DEFAULT: '<svg viewBox="0 0 24 24" fill="none"><path d="M13 2L4 14h6l-1 8 9-12h-6l1-8z" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/></svg>',
};
const TX_LABELS = {
    MINING_REWARD: '⛏ Mining reward',
    XERA_PURCHASE: 'XERA purchase',
    REFERRAL_REWARD: 'Referral reward',
    BONUS: 'Bonus',
    ADMIN_CREDIT: 'Balance adjustment',
    ADMIN_DEBIT: 'Balance adjustment',
    REVERSAL: 'Reversal',
    MIGRATION: 'Migration',
};
const EMPTY_ICON = '<svg viewBox="0 0 24 24" fill="none"><path d="M3 12h4l3 8 4-16 3 8h4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>';

function renderTransactions(list) {
    if (!list.length) {
        $('transactions').innerHTML = `<div class="empty">${EMPTY_ICON}<p>No activity yet — start mining to see it here.</p></div>`;
        return;
    }
    $('transactions').innerHTML = list.map((x) => {
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

// ================= WALLET / MINING =================

async function load() {
    try {
        const [w, m, t] = await Promise.all([
            req('/api/xera/wallet'),
            req('/api/xera/mining/status'),
            req('/api/xera/transactions?limit=20&offset=0')
        ]);
        $('authView').hidden = true;
        $('walletView').hidden = false;
        $('walletView').style.display = 'flex';
        $('balance').textContent = fmt(w.balance);
        $('walletStatus').innerHTML = `<span class="dot"></span>${w.wallet_status || 'ACTIVE'}`;
        mining = m.mining;
        renderMining();
        renderTransactions(t.transactions || []);
        if (!tickHandle) tickHandle = setInterval(() => { if (mining) renderMining(); }, 1000);
    } catch (err) {
        showLogin('Please sign in again.');
    }
}

function setRing(fraction, done) {
    const fg = $('ringFg');
    const offset = RING_CIRCUMFERENCE * (1 - Math.max(0, Math.min(1, fraction)));
    fg.style.strokeDashoffset = String(offset);
    fg.classList.toggle('done', !!done);
}

function fmtDateTime(d) {
    return d.toLocaleString(undefined, { month: 'long', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit' });
}

function renderMining() {
    const btn = $('miningAction');
    if (!mining) {
        setRing(0, false);
        $('countdown').textContent = '24:00:00';
        $('ringCaption').textContent = 'Ready to start';
        $('rewardText').textContent = 'The server controls the mining timer.';
        $('miningMeta').hidden = true;
        btn.textContent = 'Start mining';
        btn.classList.remove('ready');
        btn.disabled = false;
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
        $('countdown').textContent = '00:00:00';
        $('ringCaption').textContent = 'Session complete';
        $('rewardText').innerHTML = `<b>Claimable: ${fmt(mining.estimated_reward)} XERA</b>`;
        btn.textContent = 'Claim XERA';
        btn.classList.add('ready');
        btn.disabled = false;
    } else {
        setRing(fraction, false);
        const s = Math.floor(remain / 1000);
        const h = String(Math.floor(s / 3600)).padStart(2, '0');
        const m = String(Math.floor((s % 3600) / 60)).padStart(2, '0');
        const sec = String(s % 60).padStart(2, '0');
        $('countdown').textContent = `${h}:${m}:${sec}`;
        $('ringCaption').textContent = 'Mining in progress';
        $('rewardText').textContent = `Estimated session reward: +${fmt(mining.estimated_reward)} XERA`;
        btn.textContent = 'Mining active';
        btn.classList.remove('ready');
        btn.disabled = true;
    }
}

// ================= EVENTS =================

$('loginForm').addEventListener('submit', login);
$('registerForm').addEventListener('submit', register);

$('tabLogin').onclick = () => showAuthTab('login');
$('tabRegister').onclick = () => showAuthTab('register');
$('goRegister').onclick = () => showAuthTab('register');
$('goLogin').onclick = () => showAuthTab('login');

$('logout').onclick = () => {
    clearInterval(tickHandle);
    tickHandle = null;
    mining = null;
    showLogin();
};

$('openMiningInfo').onclick = () => { $('miningInfoModal').hidden = false; };
$('closeMiningInfo').onclick = () => { $('miningInfoModal').hidden = true; };
$('closeMiningInfoBtn').onclick = () => { $('miningInfoModal').hidden = true; };
$('miningInfoModal').addEventListener('click', (e) => { if (e.target.id === 'miningInfoModal') $('miningInfoModal').hidden = true; });

$('openStats').onclick = openStats;
$('closeStats').onclick = () => { $('statsModal').hidden = true; };
$('statsModal').addEventListener('click', (e) => { if (e.target.id === 'statsModal') $('statsModal').hidden = true; });

$('miningAction').onclick = async () => {
    const btn = $('miningAction');
    $('error').textContent = '';
    btn.disabled = true;
    try {
        if (!mining) {
            const d = await req('/api/xera/mining/start', { method: 'POST', body: '{}' });
            mining = d.mining;
        } else {
            await req('/api/xera/mining/claim', { method: 'POST', body: JSON.stringify({ session_id: mining.id }) });
            mining = null;
            await load();
        }
        renderMining();
    } catch (e) {
        $('error').textContent = e.message;
    } finally {
        if (!(mining && new Date(mining.expires_at) > Date.now())) btn.disabled = false;
    }
};

if (token()) load();
