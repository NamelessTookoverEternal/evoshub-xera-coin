// EVOS HUB — the one sign-in / create-account page for every EVOS product
// (XERA, EVOS Data, …). Credentials are only ever checked here; products read
// the session token this page stores (see evos-session.js).
//   /login?next=/evosdata/dashboard   return there after sign-in (same-origin only)
//   /login?mode=register&ref=CODE     open on "Create account", invite code pre-filled
import { safeNext, isLoggedIn, notifyAuthChange, TOKEN_KEY, USER_KEY } from './evos-session.js';

const API = window.XERA_API_BASE || (import.meta.env && import.meta.env.VITE_API_BASE_URL) || ((location.hostname === 'localhost' || location.hostname === '127.0.0.1') ? 'http://localhost:8000' : 'https://api.evoshub.xyz');
const $ = (id) => document.getElementById(id);
const DEFAULT_NEXT = '/xera';

const REF_KEY = 'xera_ref';
const REF_RE = /^[A-Za-z0-9_-]{3,64}$/;
const lsGet = (k) => { try { return localStorage.getItem(k) || ''; } catch (e) { return ''; } };
const lsSet = (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* storage blocked */ } };
const lsDel = (k) => { try { localStorage.removeItem(k); } catch (e) { /* storage blocked */ } };

const params = new URLSearchParams(location.search);
const next = safeNext(params.get('next') || '', '');
const destination = next || DEFAULT_NEXT;

async function post(path, body) {
    const r = await fetch(API + path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(typeof d.detail === 'string' && d.detail ? d.detail : 'Request failed');
    return d;
}

function finish(d) {
    lsDel(REF_KEY);
    try {
        localStorage.setItem(TOKEN_KEY, d.token);
        localStorage.setItem(USER_KEY, JSON.stringify(d.user));
    } catch (e) { /* storage blocked */ }
    notifyAuthChange();
    location.replace(destination);
}

function showTab(tab) {
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

// ---- invite code ----
function captureRef() {
    const fromUrl = (params.get('ref') || '').trim();
    if (REF_RE.test(fromUrl)) lsSet(REF_KEY, fromUrl);
    if (params.has('ref')) {
        params.delete('ref');
        const qs = params.toString();
        history.replaceState({}, '', location.pathname + (qs ? '?' + qs : '') + location.hash);
    }
    const saved = lsGet(REF_KEY);
    return REF_RE.test(saved) ? saved : '';
}

let refTimer = null;
async function checkRef() {
    const code = $('regRef').value.trim();
    const hint = $('regRefHint');
    hint.textContent = '';
    if (!code) return;
    if (!REF_RE.test(code)) { hint.textContent = 'Codes use letters, numbers, dashes and underscores.'; return; }
    try {
        const d = await fetch(API + '/api/xera/referral/validate?code=' + encodeURIComponent(code)).then((r) => r.json());
        if ($('regRef').value.trim() !== code) return;
        hint.textContent = d.valid ? `Invited by ${d.inviter} ✓` : "We don't recognise that code — you can still sign up without it.";
    } catch (e) { /* offline: stay quiet */ }
}

// ---- forms ----
$('loginForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    $('loginError').textContent = '';
    const btn = e.target.querySelector('button[type="submit"]');
    btn.disabled = true;
    try {
        finish(await post('/api/xera/auth/login', { identifier: $('identifier').value, password: $('password').value }));
    } catch (err) {
        $('loginError').textContent = err.message;
        btn.disabled = false;
    }
});

// Real-name popup: shown before the account is created. Resolves with the
// name the person confirmed, or null if they go back.
let regName = '';
function askRealName(prefill, errorText) {
    return new Promise((resolve) => {
        const modal = $('nameModal'), input = $('nmInput'), box = $('nmConfirm'), err = $('nmErr');
        input.value = prefill || '';
        box.checked = false;
        err.textContent = errorText || '';
        modal.hidden = false;
        setTimeout(() => input.focus(), 30);
        const done = (val) => {
            modal.hidden = true;
            $('nameForm').onsubmit = null; $('nmCancel').onclick = null; modal.onkeydown = null;
            resolve(val);
        };
        $('nameForm').onsubmit = (ev) => {
            ev.preventDefault();
            const v = input.value.replace(/\s+/g, ' ').trim();
            if (v.split(' ').filter(Boolean).length < 2) { err.textContent = 'Enter your first and last name, as on your ID.'; return; }
            if (!box.checked) { err.textContent = 'Please confirm this is your real name.'; return; }
            done(v);
        };
        $('nmCancel').onclick = () => done(null);
        modal.onkeydown = (ev) => { if (ev.key === 'Escape') done(null); };
    });
}

$('registerForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    $('registerError').textContent = '';
    const password = $('regPassword').value;
    if (password !== $('regPassword2').value) { $('registerError').textContent = "Passwords don't match."; return; }
    const btn = e.target.querySelector('button[type="submit"]');
    let nameErr = '';
    for (;;) {
        const name = await askRealName(regName, nameErr);
        if (name === null) return;
        regName = name;
        btn.disabled = true;
        try {
            finish(await post('/api/xera/auth/register', {
            full_name: name,
            username: $('regUsername').value,
            email: $('regEmail').value,
            phone: $('regPhone').value.trim() || undefined,
            password,
            ref: $('regRef').value.trim() || undefined,
            }));
            return;
        } catch (err) {
            btn.disabled = false;
            // A name problem reopens the popup so it can be fixed in place.
            if (/real name|first and last|name is too long|can't be used|letters only/i.test(err.message)) { nameErr = err.message; continue; }
            $('registerError').textContent = err.message;
            return;
        }
    }
});

$('regRef').addEventListener('input', () => { clearTimeout(refTimer); refTimer = setTimeout(checkRef, 400); });
$('tabLogin').onclick = () => showTab('login');
$('tabRegister').onclick = () => showTab('register');
$('goRegister').onclick = () => showTab('register');
$('goLogin').onclick = () => showTab('login');

// ---- boot ----
if (isLoggedIn()) {
    location.replace(destination);               // already signed in
} else {
    const ref = captureRef();
    if (next) {
        const name = next.startsWith('/evosdata') ? 'EVOS Data' : next.startsWith('/xera') ? 'XERA' : 'that page';
        $('authContext').textContent = `Sign in or create an account to continue to ${name}.`;
        $('authContext').hidden = false;
    }
    if (params.get('mode') === 'register' || ref) showTab('register');
    if (ref) { $('regRef').value = ref; checkRef(); }
}
