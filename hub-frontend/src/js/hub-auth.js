/* EVOS HUB — header authentication controls.
 *
 * One module, imported by every public Hub page (via nav.js / appevoxera.js).
 * It reads the single EVOS session (evos-session.js), renders Log in / Sign up
 * or an account menu with Sign out into the existing header, and keeps it in
 * sync on login, logout, expiry and cross-tab changes — no refresh needed.
 *
 * Sign-in itself is the one central screen at /xera (the only login the
 * ecosystem has). Links to protected products are pointed at it with a
 * validated ?next= so the user lands back on the product they chose.
 */

import { isLoggedIn, getUser, logout, onAuthChange, signInUrl, safeNext } from './evos-session.js';

// Products that need an account. Public pages/docs stay open.
// (/xera is itself the sign-in surface, so it is not rewritten.)
const PROTECTED_PREFIXES = ['/evosdata', '/hub'];
const isProtectedPath = (p) => PROTECTED_PREFIXES.some((x) => p === x || p.startsWith(x + '/') || p.startsWith(x + '.'));

const CSS = `
.evos-auth{display:inline-flex;align-items:center;gap:8px;position:relative;font:inherit}
.evos-auth__link{color:inherit;text-decoration:none;font-size:14px;font-weight:500;padding:8px 10px;border-radius:8px;opacity:.9}
.evos-auth__link:hover{opacity:1}
.evos-auth__cta{background:var(--green,#16a34a);color:#fff!important;padding:8px 16px;border-radius:999px;font-size:14px;font-weight:600;text-decoration:none;opacity:1}
.evos-auth__btn{display:inline-flex;align-items:center;gap:8px;background:transparent;color:inherit;border:1px solid rgba(128,128,128,.35);border-radius:999px;padding:4px 12px 4px 4px;cursor:pointer;font:inherit;font-size:14px}
.evos-auth__avatar{width:28px;height:28px;border-radius:50%;background:var(--green,#16a34a);color:#fff;display:inline-flex;align-items:center;justify-content:center;font-weight:700;font-size:13px}
.evos-auth__name{max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.evos-auth__menu{position:absolute;right:0;top:calc(100% + 8px);min-width:190px;background:var(--bg-card,var(--bg,#0e1116));color:var(--text,inherit);border:1px solid rgba(128,128,128,.3);border-radius:12px;padding:6px;box-shadow:0 12px 32px rgba(0,0,0,.35);z-index:1000}
.evos-auth__menu[hidden]{display:none}
.evos-auth__menu a,.evos-auth__menu button{display:block;width:100%;text-align:left;background:none;border:0;color:inherit;font:inherit;font-size:14px;padding:9px 12px;border-radius:8px;cursor:pointer;text-decoration:none}
.evos-auth__menu a:hover,.evos-auth__menu button:hover{background:rgba(128,128,128,.15)}
.evos-auth__who{padding:8px 12px 6px;font-size:12px;opacity:.7;border-bottom:1px solid rgba(128,128,128,.2);margin-bottom:4px}
li.evos-auth-li{display:flex;align-items:center}
@media (max-width:640px){.evos-auth__name{display:none}.evos-auth__btn{padding-right:4px}}
`;

function esc(s) {
    const d = document.createElement('div');
    d.textContent = String(s ?? '');
    return d.innerHTML;
}

function currentNext() {
    // Return to the page the visitor is on. Don't loop back to the sign-in screen.
    const here = location.pathname + location.search + location.hash;
    return location.pathname.startsWith('/xera') ? '' : safeNext(here, '');
}

function render(host) {
    if (!isLoggedIn()) {
        const next = currentNext();
        host.innerHTML = `
            <a class="evos-auth__link" data-evos-login href="${esc(signInUrl(next, 'login'))}">Log in</a>
            <a class="evos-auth__cta" data-evos-signup href="${esc(signInUrl(next, 'register'))}">Sign up</a>`;
        return;
    }
    const u = getUser() || {};
    const name = u.full_name || u.username || 'Account';
    const initial = String(name).trim().charAt(0).toUpperCase() || 'E';
    host.innerHTML = `
        <button type="button" class="evos-auth__btn" aria-haspopup="true" aria-expanded="false" data-evos-menu-btn>
            <span class="evos-auth__avatar">${esc(initial)}</span>
            <span class="evos-auth__name">${esc(u.username || name)}</span>
        </button>
        <div class="evos-auth__menu" role="menu" hidden>
            <div class="evos-auth__who">Signed in as<br><strong>${esc(u.email || u.username || name)}</strong></div>
            <a role="menuitem" href="/xera">XERA</a>
            <a role="menuitem" href="/evosdata">EVOS Data</a>
            <button type="button" role="menuitem" data-evos-signout>Sign out</button>
        </div>`;
    const btn = host.querySelector('[data-evos-menu-btn]');
    const menu = host.querySelector('.evos-auth__menu');
    btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const open = menu.hidden;
        menu.hidden = !open;
        btn.setAttribute('aria-expanded', String(open));
    });
    host.querySelector('[data-evos-signout]').addEventListener('click', () => {
        logout();                                   // fires the auth event -> everything re-renders
        if (isProtectedPath(location.pathname)) location.replace('/');
    });
}

/** Protected product links go through sign-in when signed out; plain links when signed in. */
function syncProtectedLinks(root = document) {
    const out = !isLoggedIn();
    root.querySelectorAll('a[href]').forEach((a) => {
        const orig = a.dataset.evosHref || a.getAttribute('href');
        if (!orig || !orig.startsWith('/') || orig.startsWith('//')) return;
        let path;
        try { path = new URL(orig, location.origin).pathname; } catch (e) { return; }
        if (!isProtectedPath(path)) return;
        a.dataset.evosHref = orig;
        a.setAttribute('href', out ? signInUrl(orig) : orig);
    });
}

function mount() {
    if (document.querySelector('.evos-auth')) return;
    const style = document.createElement('style');
    style.textContent = CSS;
    document.head.appendChild(style);

    const host = document.createElement('div');
    host.className = 'evos-auth';

    const navLinks = document.querySelector('.nav-links');
    const ehub = document.querySelector('.ehub__actions');
    if (navLinks) {
        const li = document.createElement('li');
        li.className = 'evos-auth-li';
        li.appendChild(host);
        navLinks.appendChild(li);
    } else if (ehub) {
        ehub.insertBefore(host, ehub.firstChild);
    } else {
        return; // page has no public header (hub shell pages have their own)
    }

    const refresh = () => { render(host); syncProtectedLinks(); };
    refresh();
    onAuthChange(refresh);
    document.addEventListener('click', () => {
        const m = host.querySelector('.evos-auth__menu');
        if (m && !m.hidden) { m.hidden = true; host.querySelector('[data-evos-menu-btn]')?.setAttribute('aria-expanded', 'false'); }
    });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') host.querySelector('.evos-auth__menu')?.setAttribute('hidden', '');
    });

    // Links added after load (e.g. admin-curated ecosystem links) are handled on click.
    document.addEventListener('click', (e) => {
        const a = e.target.closest && e.target.closest('a[href]');
        if (!a || isLoggedIn() || e.defaultPrevented || e.button !== 0) return;
        const href = a.dataset.evosHref || a.getAttribute('href');
        if (!href || !href.startsWith('/') || href.startsWith('//')) return;
        let path;
        try { path = new URL(href, location.origin).pathname; } catch (err) { return; }
        if (isProtectedPath(path) && !a.getAttribute('href').startsWith('/xera')) {
            e.preventDefault();
            location.href = signInUrl(href);
        }
    }, true);
}

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount);
else mount();
