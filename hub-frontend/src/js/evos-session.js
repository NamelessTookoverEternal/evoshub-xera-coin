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
    return localStorage.getItem(TOKEN_KEY) || '';
}

export function getUser() {
    try {
        return JSON.parse(localStorage.getItem(USER_KEY) || 'null');
    } catch (e) {
        return null;
    }
}

export function isLoggedIn() {
    return !!getToken();
}

export function logout() {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
}

/** Redirects to the XERA sign-in screen (the only login screen the
 *  ecosystem has today) if there's no session, and returns false so the
 *  caller can bail out of rendering the page. */
export function requireSession() {
    if (isLoggedIn()) return true;
    const next = encodeURIComponent(location.pathname + location.search);
    location.replace(`/xera?next=${next}`);
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
        location.replace('/xera');
        throw new Error('Session expired');
    }
    return res.json();
}
