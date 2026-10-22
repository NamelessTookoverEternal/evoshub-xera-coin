// Admin on-chain pilot page. The wallet + claim UI itself is xera-chain.js (shared with
// the user page); this file only gates the page behind a real admin session, shows the
// pilot status and opens the panel. Authority is always the server: every API call
// re-checks the admin token and the live admin_agents row.
import './xera-chain.js';

const API_BASE = import.meta.env.VITE_API_BASE_URL ||
  ((location.hostname === 'localhost' || location.hostname === '127.0.0.1') ? 'http://localhost:8000' : 'https://api.evoshub.xyz');
const TOKEN_KEY = 'evoshub_admin_token';
const $ = (id) => document.getElementById(id);

const token = () => { try { return sessionStorage.getItem(TOKEN_KEY) || ''; } catch (e) { return ''; } };
const toLogin = () => { try { sessionStorage.removeItem(TOKEN_KEY); } catch (e) { /* ignore */ } location.href = '/admin-login.html'; };
const get = (path) => fetch(API_BASE + path, { headers: { Authorization: `Bearer ${token()}` } });

$('pilotSignout').addEventListener('click', toLogin);

function chainBox(name, c) {
  const box = document.createElement('div');
  const t = document.createElement('b'); t.textContent = name; box.append(t);
  const a = document.createElement('div');
  a.className = c.distributor_configured ? 'pilot-ok' : 'pilot-off';
  a.textContent = c.distributor_configured ? 'Contract address set' : 'Contract address missing';
  const u = document.createElement('div'); u.style.opacity = '.75';
  u.textContent = c.user_claims_open ? 'Open to users' : 'Closed to users';
  box.append(a, u);
  return box;
}

async function init() {
  if (!token()) { toLogin(); return; }
  try {
    const me = await get('/api/admin/me');
    if (!me.ok) { toLogin(); return; }
    const u = (await me.json()).user || {};
    $('pilotWho').textContent = u.display_name || u.username || u.email || 'Admin';
  } catch (e) {
    $('pilotError').textContent = 'Could not reach the server. Check your connection and reload.';
    return;
  }

  try {
    const r = await get('/api/admin/xera/pilot/status');
    if (r.status === 401 || r.status === 403) { toLogin(); return; }
    const s = await r.json();
    const on = !!s.pilot_enabled;
    $('pilotBadge').textContent = on ? 'PILOT ON' : 'PILOT OFF';
    $('pilotBadge').className = 'pilot-badge ' + (on ? 'pilot-ok' : 'pilot-off');
    $('pilotFlag').textContent = on
      ? 'Claim signing is enabled for admins. You can link wallets and try a claim.'
      : 'You can link wallets, but claim signing is off. Set XERA_ADMIN_ONCHAIN_PILOT=true on the backend to try a claim.';
    $('pilotChains').replaceChildren(chainBox('BNB', s.chains.BNB), chainBox('TON', s.chains.TON));
    $('pilotStatus').hidden = false;
  } catch (e) { /* the panel below still works and reports its own errors */ }

  $('openChain').click();   // loads wallets, claimable balance, vesting, history
}
init();
