// Account deletion with a 7-day grace period (Profile tab on /xera).
//
// Talks only to /api/xera/account-deletion/* (python/xera/account_deletion.py). The server decides
// everything: who the user is, whether deleting is allowed right now, the date, and the password check.
// This file only shows the state and collects the password. Nothing here touches on-chain code.

const API = window.XERA_API_BASE || (import.meta.env && import.meta.env.VITE_API_BASE_URL) ||
  ((location.hostname === 'localhost' || location.hostname === '127.0.0.1') ? 'http://localhost:8000' : 'https://api.evoshub.xyz');
const BASE = API + '/api/xera/account-deletion';
const $ = (id) => document.getElementById(id);
const token = () => { try { return localStorage.getItem('xera_evos_token') || ''; } catch (_e) { return ''; } };
const fmt = (n) => Number(n || 0).toLocaleString('en-US', { maximumFractionDigits: 4 });
const dateText = (iso) => { try { return new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'long', year: 'numeric' }); } catch (_e) { return ''; } };

async function req(path, opts = {}) {
  const r = await fetch(BASE + path, {
    ...opts,
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token()}`, ...(opts.headers || {}) },
  });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof d.detail === 'string' && d.detail ? d.detail : 'Please check the details and try again.');
  return d;
}

export function initAccountDeletion() {
  const card = $('deleteAccountCard'), modal = $('deleteAccountModal');
  if (!card || !modal) return;
  let busy = false, state = null;

  const setMsg = (t, ok) => { const e = $('daMsg'); e.textContent = t || ''; e.style.color = ok ? '#5ee0a0' : '#ff7b8a'; };
  const close = () => { modal.hidden = true; };

  function render(s) {
    state = s;
    const pending = !!s.pending;
    $('daPendingBox').hidden = !pending;
    $('daStartBox').hidden = pending;
    if (pending) $('daPendingText').textContent = `Your account is scheduled to be deleted on ${dateText(s.purge_after)}. You can keep using it until then, and you can cancel at any time before that date.`;
    $('daOpen').disabled = !s.enabled || !!s.blocked_reason;
    $('daBlocked').textContent = !s.enabled ? 'Account deletion is paused right now. Please contact support.' : (s.blocked_message || '');
    $('daBlocked').hidden = pending || !$('daBlocked').textContent;
    $('daBalance').textContent = fmt(s.balance);
    document.querySelectorAll('[data-da-days]').forEach((el) => { el.textContent = s.grace_days; });
  }

  async function load() {
    try { render(await req('/status')); } catch (_e) { card.hidden = true; return; }
    card.hidden = false;
  }

  $('daOpen').addEventListener('click', () => {
    if (!state) return;
    $('daPassword').value = ''; $('daConfirm').checked = false; setMsg('');
    $('daSubmit').disabled = false;
    modal.hidden = false;
    setTimeout(() => $('daPassword').focus(), 30);
  });
  $('daClose').addEventListener('click', close);
  $('daCancelBtn').addEventListener('click', close);
  modal.addEventListener('click', (e) => { if (e.target === modal) close(); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !modal.hidden) close(); });

  $('daForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    if (busy) return;
    if (!$('daPassword').value) { setMsg('Enter your password to continue.'); return; }
    if (!$('daConfirm').checked) { setMsg('Please tick the box to confirm.'); return; }
    busy = true; $('daSubmit').disabled = true; setMsg('');
    try {
      render(await req('/request', { method: 'POST', body: JSON.stringify({ password: $('daPassword').value }) }));
      close();
    } catch (err) {
      setMsg(err.message);
      $('daSubmit').disabled = false;
    } finally { busy = false; }
  });

  $('daUndo').addEventListener('click', async () => {
    if (busy) return;
    busy = true; $('daUndo').disabled = true;
    try { render(await req('/cancel', { method: 'POST' })); }
    catch (err) { $('daBlocked').textContent = err.message; $('daBlocked').hidden = false; }
    finally { busy = false; $('daUndo').disabled = false; }
  });

  load();
}
