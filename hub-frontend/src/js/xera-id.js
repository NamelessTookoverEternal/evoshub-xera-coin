// Shows the signed-in user's XERA ID (used to receive in-app transfers) on the Profile and Wallet tabs.
// Read-only: it calls GET /api/xera/transfer/me, which also creates the ID the first time.
// Guests, or any error, leave the rows hidden. Nothing here moves money.
const API = window.XERA_API_BASE || (import.meta.env && import.meta.env.VITE_API_BASE_URL) ||
  ((location.hostname === 'localhost' || location.hostname === '127.0.0.1') ? 'http://localhost:8000' : 'https://api.evoshub.xyz');

const token = () => { try { return localStorage.getItem('xera_evos_token') || ''; } catch (_e) { return ''; } };
function expired(t) {
  try {
    const p = JSON.parse(atob(t.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')));
    return !!(p.exp && p.exp * 1000 < Date.now());
  } catch (_e) { return false; }
}

async function init() {
  const rows = document.querySelectorAll('[data-xera-id-row]');
  const t = token();
  if (!rows.length || !t || expired(t)) return;
  let id = '';
  try {
    const r = await fetch(API + '/api/xera/transfer/me', { headers: { Authorization: `Bearer ${t}` } });
    if (!r.ok) return;
    id = (await r.json()).xera_id || '';
  } catch (_e) { return; }
  if (!id) return;
  document.querySelectorAll('[data-xera-id]').forEach((el) => { el.textContent = id; });
  rows.forEach((row) => { row.style.display = ''; });
}

document.addEventListener('click', async (ev) => {
  const btn = ev.target.closest('[data-xera-id-copy]');
  if (!btn) return;
  const id = (document.querySelector('[data-xera-id]') || {}).textContent || '';
  if (!/^XR-/.test(id)) return;
  const old = btn.textContent;
  try { await navigator.clipboard.writeText(id); btn.textContent = 'Copied'; }
  catch (_e) { btn.textContent = 'Select and copy'; }
  setTimeout(() => { btn.textContent = old; }, 1800);
});

init();
