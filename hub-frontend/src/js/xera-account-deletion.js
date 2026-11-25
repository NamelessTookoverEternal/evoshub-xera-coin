// Account deletion with a 7-day grace period (Profile tab on /xera).
//
// Talks only to /api/xera/account-deletion/* (python/xera/account_deletion.py). The server decides
// everything: who the user is, whether deleting is allowed right now, the date, and the password check.
// This file only shows the state and collects the password. Nothing here touches on-chain code.
//
// Flow: popup 1 (warnings + password) -> POST /preview (password and blockers checked, nothing scheduled)
//       -> popup 2 (every product's wallet and balance; Cancel or Proceed to delete)
//       -> if any balance would be lost, a last warning -> POST /request schedules the deletion.
// A stuck EVOS Data order/withdrawal blocks only the first Delete press (notice shown); pressing Delete again goes on to popup 2.

const API = window.XERA_API_BASE || (import.meta.env && import.meta.env.VITE_API_BASE_URL) ||
  ((location.hostname === 'localhost' || location.hostname === '127.0.0.1') ? 'http://localhost:8000' : 'https://api.evoshub.xyz');
const BASE = API + '/api/xera/account-deletion';
const $ = (id) => document.getElementById(id);
const token = () => { try { return localStorage.getItem('xera_evos_token') || ''; } catch (_e) { return ''; } };
const fmt = (n) => Number(n || 0).toLocaleString('en-US', { maximumFractionDigits: 4 });
const money = (amount, unit) => (unit === 'GHS' ? 'GH\u20B5 ' + Number(amount || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  : fmt(amount) + ' Pure XERA');
const el = (tag, css, text) => { const n = document.createElement(tag); if (css) n.style.cssText = css; if (text != null) n.textContent = text; return n; };
const dateText = (iso) => { try { return new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'long', year: 'numeric' }); } catch (_e) { return ''; } };

async function req(path, opts = {}) {
  const r = await fetch(BASE + path, {
    ...opts,
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token()}`, ...(opts.headers || {}) },
  });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) {
    const e = new Error(typeof d.detail === 'string' && d.detail ? d.detail : 'Please check the details and try again.');
    e.status = r.status;
    e.canContinue = !!d.can_continue;      // a stuck EVOS Data order: pressing Delete again continues
    throw e;
  }
  return d;
}

export function initAccountDeletion() {
  const card = $('deleteAccountCard'), modal = $('deleteAccountModal');
  if (!card || !modal) return;
  const review = $('deleteReviewModal');
  let busy = false, state = null, pw = '', pv = null, stuckSeen = false;

  const setMsg = (t, ok) => { const e = $('daMsg'); e.textContent = t || ''; e.style.color = ok ? '#5ee0a0' : '#ff7b8a'; };
  const close = () => { modal.hidden = true; };
  const closeReview = () => { review.hidden = true; pw = ''; pv = null; };
  const closeAll = () => { close(); closeReview(); $('daPassword').value = ''; stuckSeen = false; };

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
    $('daPassword').value = ''; $('daConfirm').checked = false; setMsg(''); stuckSeen = false;
    $('daSubmit').disabled = false;
    modal.hidden = false;
    setTimeout(() => $('daPassword').focus(), 30);
  });
  $('daClose').addEventListener('click', close);
  $('daCancelBtn').addEventListener('click', close);
  modal.addEventListener('click', (e) => { if (e.target === modal) close(); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !modal.hidden) close(); });

  // Step 1: check the password and blockers, then show popup 2. Nothing is scheduled yet.
  $('daForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    if (busy) return;
    if (!$('daPassword').value) { setMsg('Enter your password to continue.'); return; }
    if (!$('daConfirm').checked) { setMsg('Please tick the box to confirm.'); return; }
    busy = true; $('daSubmit').disabled = true; setMsg('');
    try {
      const p = $('daPassword').value;
      const data = await req('/preview', { method: 'POST', body: JSON.stringify({ password: p, continue_busy: stuckSeen }) });
      pw = p; pv = data;
      close();
      showReview();
    } catch (err) {
      if (err.canContinue) {        // an order/withdrawal is "in progress" (it can be stuck): tell them once, the next press goes on
        stuckSeen = true;
        setMsg(err.message + ' If it looks stuck, press Delete again to continue anyway.');
      } else { stuckSeen = false; setMsg(err.message); }
    } finally { busy = false; $('daSubmit').disabled = false; }
  });

  function showReview() {
    const box = $('drProducts');
    box.textContent = '';
    for (const w of (pv.warnings || [])) {
      box.appendChild(el('div', 'border:1px solid rgba(255,90,110,.55);background:rgba(255,90,110,.08);border-radius:12px;padding:9px 12px;margin-bottom:8px;font-size:.84rem;line-height:1.45;color:#ff9aa7', w));
    }
    for (const prod of pv.products) {
      const card = el('div', 'border:1px solid rgba(255,255,255,.12);border-radius:12px;padding:10px 12px;margin-bottom:8px');
      card.appendChild(el('div', 'font-weight:700;margin-bottom:4px', prod.name));
      for (const w of prod.wallets) {
        const row = el('div', 'display:flex;justify-content:space-between;gap:10px;align-items:baseline;padding:2px 0');
        row.appendChild(el('span', 'font-size:.88rem', w.label));
        row.appendChild(el('b', w.lost ? 'color:#ff5a6e' : 'color:inherit', money(w.amount, w.unit)));
        card.appendChild(row);
      }
      for (const n of prod.notes) card.appendChild(el('div', 'font-size:.8rem;opacity:.75;margin-top:3px;line-height:1.4', n));
      box.appendChild(card);
    }
    $('drLossNote').hidden = !pv.has_balance;
    document.querySelectorAll('#deleteReviewModal [data-da-days]').forEach((n) => { n.textContent = pv.grace_days; });
    $('drMsg').textContent = ''; $('drFinalMsg').textContent = '';
    $('drReview').hidden = false; $('drFinal').hidden = true;
    $('drProceed').disabled = false;
    review.hidden = false;
  }

  // Step 2: Proceed to delete. With money at stake there is one more warning before it goes through.
  $('drProceed').addEventListener('click', () => {
    if (busy || !pv) return;
    if (!pv.has_balance) { finalize(false); return; }
    const parts = [];
    if (Number(pv.totals.xera) > 0) parts.push(money(pv.totals.xera, 'XERA'));
    if (Number(pv.totals.ghs) > 0) parts.push(money(pv.totals.ghs, 'GHS'));
    $('drFinalAmounts').textContent = parts.join(' and ');
    $('drFinalMsg').textContent = '';
    $('drReview').hidden = true; $('drFinal').hidden = false;
  });
  $('drBack').addEventListener('click', () => { $('drFinal').hidden = true; $('drReview').hidden = false; });
  $('drConfirmLoss').addEventListener('click', () => finalize(true));
  $('drCancel').addEventListener('click', closeAll);
  $('drClose').addEventListener('click', closeAll);
  review.addEventListener('click', (e) => { if (e.target === review) closeAll(); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !review.hidden) closeAll(); });

  async function finalize(acknowledge) {
    if (busy || !pv) return;
    busy = true; $('drProceed').disabled = true; $('drConfirmLoss').disabled = true;
    const msg = acknowledge ? $('drFinalMsg') : $('drMsg');
    try {
      const out = await req('/request', { method: 'POST', body: JSON.stringify({
        password: pw, acknowledge_loss: !!acknowledge, seen_xera: pv.totals.xera, seen_ghs: pv.totals.ghs, continue_busy: stuckSeen,
      }) });
      closeAll();
      render(out);
    } catch (err) {
      if (err.status === 412) {      // a balance changed while the popup was open: show the new numbers
        try { pv = await req('/preview', { method: 'POST', body: JSON.stringify({ password: pw, continue_busy: stuckSeen }) }); showReview(); $('drMsg').textContent = err.message; }
        catch (e2) { closeAll(); setMsg(e2.message); }
      } else { msg.textContent = err.message; }
    } finally { busy = false; $('drProceed').disabled = false; $('drConfirmLoss').disabled = false; }
  }

  $('daUndo').addEventListener('click', async () => {
    if (busy) return;
    busy = true; $('daUndo').disabled = true;
    try { render(await req('/cancel', { method: 'POST' })); }
    catch (err) { $('daBlocked').textContent = err.message; $('daBlocked').hidden = false; }
    finally { busy = false; $('daUndo').disabled = false; }
  });

  load();
}
