/* EVOS HUB — shared session helper.
 *
 * There is one EVOS account system today: it lives behind the XERA
 * login/register screens at /xera, backed by the shared `public.users`
 * table ("the same one EVOSGPT/EVOSDATA/admin use" — see routes_auth.py).
 * The token it issues is a general EVOS session token, not a XERA-only
 * one, so the Hub shell reads the exact same localStorage keys XERA
 * already writes rather than inventing a second, competing session.
 *
 * Deliberately NOT renamed to something hub-specific: xera.js already
 * reads/writes these two keys, and having two names for one session
 * would be the actual bug. If a real /api/auth/* namespace is ever
 * split out from /api/xera/auth/*, update TOKEN_KEY/USER_KEY here and
 * in xera.js together.
 */

export const TOKEN_KEY = 'xera_evos_token';
export const USER_KEY = 'xera_evos_user';

export function getToken() {
    try { return localStorage.getItem(TOKEN_KEY) || ''; } catch (e) { return ''; }
}

export function getUser() {
    try {
        return JSON.parse(localStorage.getItem(USER_KEY) || 'null');
    } catch (e) {
        return null;
    }
}

/** Expiry (ms since epoch) read from the token payload, or 0 if unreadable.
 *  Client-side only to avoid sending a dead token; the server is the authority. */
export function tokenExpiry(token = getToken()) {
    try {
        const b64 = token.split('.')[0].replace(/-/g, '+').replace(/_/g, '/');
        const payload = JSON.parse(atob(b64 + '='.repeat((4 - (b64.length % 4)) % 4)));
        return payload && payload.exp ? Number(payload.exp) * 1000 : 0;
    } catch (e) {
        return 0;
    }
}

export function isExpired(token = getToken()) {
    const exp = tokenExpiry(token);
    return !!exp && exp <= Date.now();
}

/** True only for a present, unexpired token. An expired one is cleared so the
 *  UI and protected pages see a signed-out state instead of failing later. */
export function isLoggedIn() {
    const t = getToken();
    if (!t) return false;
    if (isExpired(t)) { logout(); return false; }
    return true;
}

// ---- change notification -------------------------------------------------
// One event for "the session changed" so the header and protected links update
// without a refresh. Same-tab changes fire EVOS_AUTH_EVENT; other tabs are
// picked up through the native `storage` event.
export const EVOS_AUTH_EVENT = 'evos:auth';

export function notifyAuthChange() {
    try { window.dispatchEvent(new CustomEvent(EVOS_AUTH_EVENT)); } catch (e) { /* ignore */ }
}

export function onAuthChange(cb) {
    window.addEventListener(EVOS_AUTH_EVENT, cb);
    window.addEventListener('storage', (e) => { if (!e.key || e.key === TOKEN_KEY || e.key === USER_KEY) cb(); });
    // Catch a token expiring while the page is open.
    setInterval(() => { if (getToken() && isExpired()) { logout(); } }, 30000);
}

// ---- return destination --------------------------------------------------
/** Validates a post-login destination. Only same-origin absolute paths are
 *  accepted ("/evosdata/shop?x=1"); anything else (other hosts, "//host",
 *  "/\\host", javascript:, control characters) falls back. Prevents open redirects. */
export function safeNext(raw, fallback = '') {
    if (typeof raw !== 'string' || !raw) return fallback;
    let v = raw.trim();
    if (!v.startsWith('/') || v.startsWith('//') || /[\\\u0000-\u001f]/.test(v)) return fallback;
    try {
        const u = new URL(v, location.origin);
        if (u.origin !== location.origin) return fallback;
        return u.pathname + u.search + u.hash;
    } catch (e) {
        return fallback;
    }
}

/** URL of the central sign-in screen, remembering where to come back to. */
export function signInUrl(next, mode = 'login') {
    const dest = safeNext(next, '');
    const q = new URLSearchParams();
    if (dest) q.set('next', dest);
    if (mode === 'register') q.set('mode', 'register');
    const qs = q.toString();
    return '/xera' + (qs ? '?' + qs : '');
}

// EVOS Data keeps its own session on this same origin (/evosdata). Signing out
// of the Hub must end that one too. (Server-side tokens are stateless and
// simply expire; see EVOSDATA_INTEGRATION.md.)
const EVOSDATA_KEYS = ['user', 'email', 'username', 'user_id', 'userToken', 'agentToken'];

export function logout() {
    try {
        localStorage.removeItem(TOKEN_KEY);
        localStorage.removeItem(USER_KEY);
        EVOSDATA_KEYS.forEach((k) => localStorage.removeItem(k));
        sessionStorage.removeItem('agentToken');
    } catch (e) { /* storage unavailable */ }
    notifyAuthChange();
}

/** Redirects to the central sign-in screen if there's no valid session, and
 *  returns false so the caller can bail out of rendering the page. */
export function requireSession() {
    if (isLoggedIn()) return true;
    location.replace(signInUrl(location.pathname + location.search + location.hash));
    return false;
}

/** Authenticated fetch against the FastAPI backend. Throws on network
 *  failure; returns the parsed JSON body on any response (including
 *  non-2xx, so callers can read `.detail`) except 401, which clears the
 *  session and redirects to sign-in since the token is dead either way. */
export async function api(path, opts = {}) {
    const res = await fetch(path, {
        ...opts,
        headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${getToken()}`,
            ...(opts.headers || {}),
        },
    });
    if (res.status === 401) {
        logout();
        location.replace(signInUrl(location.pathname + location.search));
        throw new Error('Session expired');
    }
    return res.json();
}
