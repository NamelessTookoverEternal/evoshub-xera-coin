// Paid name change (Profile tab on /xera).
//
// Talks only to /api/xera/name-change/* (python/xera/name_change.py). The server decides everything:
// the fee, the one-change limit, the KYC lock and the balance move. This file only shows the state
// and collects the new name. One request id is made per time the popup is opened, so a double tap
// or a retry can never charge twice.

const API = window.XERA_API_BASE || (import.meta.env && import.meta.env.VITE_API_BASE_URL) ||
  ((location.hostname === 'localhost' || location.hostname === '127.0.0.1') ? 'http://localhost:8000' : 'https://api.evoshub.xyz');
const BASE = API + '/api/xera/name-change';
const $ = (id) => document.getElementById(id);
const token = () => { try { return localStorage.getItem('xera_evos_token') || ''; } catch (_e) { return ''; } };
const fmt = (n) => Number(n || 0).toLocaleString('en-US', { maximumFractionDigits: 4 });

async function req(path, opts = {}) {
  const r = await fetch(BASE + path, {
    ...opts,
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token()}`, ...(opts.headers || {}) },
  });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof d.detail === 'string' && d.detail ? d.detail : 'Please check the details and try again.');
  return d;
}

const WHY = {
  paused: 'Name changes are paused right now. Please try again later.',
  kyc_locked: 'Your name is locked because your identity check has started or is complete. Contact support if it is wrong.',
  no_change_left: 'You have already used your name change. Contact support if you need help.',
  money_locked: 'Your account is under review, so the name cannot be changed right now. Contact support.',
};

function newRequestId() {
  try { return crypto.randomUUID().replace(/-/g, ''); } catch (_e) { return 'r' + Date.now() + Math.random().toString(36).slice(2, 10); }
}

export function initNameChange(onChanged) {
  const btn = $('nameChangeBtn'), modal = $('nameChangeModal');
  if (!btn || !modal) return;
  let requestId = '', busy = false;

  const set = (id, v) => { const el = $(id); if (el) el.textContent = v; };
  const close = () => { modal.hidden = true; };
  const showMsg = (t, ok) => { const e = $('ncMsg'); e.textContent = t || ''; e.style.color = ok ? '#5ee0a0' : '#ff7b8a'; };

  async function open() {
    requestId = newRequestId();
    modal.hidden = false;
    $('ncForm').hidden = true; $('ncBlocked').hidden = true; showMsg('');
    set('ncLoading', 'Loading…'); $('ncLoading').hidden = false;
    try {
      const s = await req('/status');
      $('ncLoading').hidden = true;
      set('ncCurrent', s.name || '—');
      set('ncFee', fmt(s.fee));
      set('ncBalance', fmt(s.spendable));
      if (!s.can_change && s.reason !== 'insufficient_balance') {
        set('ncBlocked', WHY[s.reason] || 'You cannot change your name right now.');
        $('ncBlocked').hidden = false;
        return;
      }
      $('ncForm').hidden = false;
      $('ncInput').value = '';
      $('ncConfirm').checked = false;
      $('ncSubmit').disabled = false;
      if (s.reason === 'insufficient_balance') showMsg(`You need ${fmt(s.fee)} Pure XERA to change your name. You have ${fmt(s.spendable)}.`);
    } catch (e) {
      $('ncLoading').hidden = true;
      set('ncBlocked', e.message || 'Could not load. Please try again.');
      $('ncBlocked').hidden = false;
    }
  }

  btn.addEventListener('click', open);
  $('ncClose').addEventListener('click', close);
  $('ncCancel').addEventListener('click', close);
  modal.addEventListener('click', (e) => { if (e.target === modal) close(); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !modal.hidden) close(); });

  $('ncForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    if (busy) return;
    const name = $('ncInput').value.replace(/\s+/g, ' ').trim();
    if (name.split(' ').filter(Boolean).length < 2) { showMsg('Enter your first and last name, as on your ID.'); return; }
    if (!$('ncConfirm').checked) { showMsg('Please confirm this is your real name and that you accept the fee.'); return; }
    busy = true; $('ncSubmit').disabled = true; showMsg('');
    try {
      const s = await req('/change', { method: 'POST', body: JSON.stringify({ new_name: name, request_id: requestId }) });
      try {
        const u = JSON.parse(localStorage.getItem('xera_evos_user') || '{}');
        u.full_name = s.name;
        localStorage.setItem('xera_evos_user', JSON.stringify(u));
      } catch (_e) { /* cosmetic */ }
      if (typeof onChanged === 'function') onChanged(s);
      showMsg('Name updated.', true);
      setTimeout(close, 900);
    } catch (err) {
      showMsg(err.message);
      $('ncSubmit').disabled = false;
    } finally {
      busy = false;
    }
  });
}
