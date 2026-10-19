/* EVOS HUB — guest-first access helpers.
 *
 * Browsing is open to everyone. Only an action that needs a verified, persistent
 * or private identity asks for sign-in, with a prompt that names the action and
 * lets the visitor cancel and keep browsing. Backend endpoints enforce the same
 * rules themselves; nothing here is a security boundary.
 */
import { isLoggedIn, signInUrl, safeNext } from './evos-session.js';

const BANNER_KEY = 'evos_guest_banner_dismissed';
const STYLE_ID = 'evos-guest-style';

const CSS = `
.evos-guest-banner{position:relative;z-index:900;display:flex;align-items:center;gap:12px;flex-wrap:wrap;padding:10px 16px;font-size:13px;line-height:1.45;background:rgba(22,163,74,.12);border-bottom:1px solid rgba(22,163,74,.35);color:inherit}
.evos-guest-banner__msg{flex:1;min-width:220px}
.evos-guest-banner a{color:var(--green,#16a34a);font-weight:700;text-decoration:none}
.evos-guest-banner button{background:none;border:0;color:inherit;font-size:18px;line-height:1;cursor:pointer;opacity:.7}
.evos-guest-chip{font-size:12px;font-weight:600;padding:3px 10px;border-radius:999px;border:1px solid rgba(128,128,128,.4);opacity:.85}
.evos-prompt{max-width:440px;margin:48px auto;padding:24px;border-radius:16px;text-align:center;background:var(--bg-card,rgba(128,128,128,.08));border:1px solid rgba(128,128,128,.3)}
.evos-prompt h2{margin:0 0 8px;font-size:20px}
.evos-prompt p{margin:0 0 18px;opacity:.75;line-height:1.5}
.evos-prompt__row{display:flex;gap:10px;justify-content:center;flex-wrap:wrap}
.evos-prompt__row a,.evos-prompt__row button{padding:10px 18px;border-radius:10px;font:inherit;font-weight:600;text-decoration:none;cursor:pointer;color:inherit;background:none;border:1px solid rgba(128,128,128,.4)}
.evos-prompt__row a.primary{background:var(--green,#16a34a);color:#fff;border-color:transparent}
.evos-prompt-overlay{position:fixed;inset:0;z-index:2000;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,.55);padding:16px}
.evos-prompt-overlay .evos-prompt{margin:0;background:var(--bg,#0e1116);color:var(--text,inherit)}
`;

function ensureStyle() {
    if (document.getElementById(STYLE_ID)) return;
    const s = document.createElement('style');
    s.id = STYLE_ID;
    s.textContent = CSS;
    document.head.appendChild(s);
}

const esc = (s) => { const d = document.createElement('div'); d.textContent = String(s ?? ''); return d.innerHTML; };

function here() {
    return safeNext(location.pathname + location.search + location.hash, '');
}

function promptHtml(action, next) {
    const dest = next || here();
    return `
    <div class="evos-prompt" role="dialog" aria-labelledby="evosPromptTitle">
        <h2 id="evosPromptTitle">Sign in to ${esc(action)}</h2>
        <p>This needs your EVOS account so it stays private and tied to you. You can keep browsing as a guest.</p>
        <div class="evos-prompt__row">
            <a class="primary" href="${esc(signInUrl(dest, 'login'))}">Log in</a>
            <a href="${esc(signInUrl(dest, 'register'))}">Sign up</a>
            <button type="button" data-evos-cancel>Continue as guest</button>
        </div>
    </div>`;
}

/** Modal prompt for a protected action started from a public page.
 *  Resolves true if the visitor is already signed in (action may proceed),
 *  false otherwise (the protected operation must not run). */
export function requireAuthFor(action, { next } = {}) {
    if (isLoggedIn()) return true;
    ensureStyle();
    const ov = document.createElement('div');
    ov.className = 'evos-prompt-overlay';
    ov.innerHTML = promptHtml(action, next);
    const close = () => ov.remove();
    ov.addEventListener('click', (e) => { if (e.target === ov || e.target.closest('[data-evos-cancel]')) close(); });
    document.addEventListener('keydown', function esc_(e) { if (e.key === 'Escape') { close(); document.removeEventListener('keydown', esc_); } });
    document.body.appendChild(ov);
    return false;
}

/** Guest view for a page that is entirely account-only (Hub dashboard, settings).
 *  Returns true when the page should render normally; otherwise renders the
 *  sign-in prompt in place of the page content and returns false. */
export function guestGate(action, { container = '.hub-main', homeHref = '/' } = {}) {
    if (isLoggedIn()) return true;
    ensureStyle();
    const host = document.querySelector(container) || document.body;
    host.innerHTML = promptHtml(action);
    const cancel = host.querySelector('[data-evos-cancel]');
    if (cancel) cancel.addEventListener('click', () => location.assign(homeHref));
    return false;
}

/** Non-blocking guest notice: dismissible for the session, never repeated per page. */
export function mountGuestBanner() {
    if (isLoggedIn()) return unmountGuestBanner();
    try { if (sessionStorage.getItem(BANNER_KEY) === '1') return; } catch (e) { /* ignore */ }
    if (document.querySelector('.evos-guest-banner')) return;
    ensureStyle();
    const el = document.createElement('div');
    el.className = 'evos-guest-banner';
    el.setAttribute('role', 'status');
    el.innerHTML = `
        <span class="evos-guest-banner__msg">You're browsing as a guest. Some progress, preferences, or activity may be lost if you leave or refresh this session. Sign in to help save and sync your progress across EVOS products.</span>
        <a href="${esc(signInUrl(location.pathname.startsWith('/xera') ? '' : here(), 'login'))}">Sign in</a>
        <button type="button" aria-label="Dismiss">&times;</button>`;
    el.querySelector('button').addEventListener('click', () => {
        try { sessionStorage.setItem(BANNER_KEY, '1'); } catch (e) { /* ignore */ }
        el.remove();
    });
    document.body.insertBefore(el, document.body.firstChild);
}

export function unmountGuestBanner() {
    document.querySelectorAll('.evos-guest-banner').forEach((n) => n.remove());
}
