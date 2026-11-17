// XERA in-app P2P transfer page (/xera-transfer).
//
// Send XERA from your in-app balance to another XERA user, plus the public global ledger.
// Talks only to /api/xera/transfer/* (python/xera/p2p.py). The server decides everything:
// who the sender is (session token), the limits, the identity-check/fee gate and the balance move.
// This file only collects input and shows results. No on-chain code lives here.

const API = window.XERA_API_BASE || (import.meta.env && import.meta.env.VITE_API_BASE_URL) ||
  ((location.hostname === 'localhost' || location.hostname === '127.0.0.1') ? 'http://localhost:8000' : 'https://api.evoshub.xyz');
const BASE = API + '/api/xera/transfer';
const $ = (id) => document.getElementById(id);

const token = () => { try { return localStorage.getItem('xera_evos_token') || ''; } catch (_e) { return ''; } };
function expired(t) {
  try {
    const p = JSON.parse(atob(t.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')));
    return !!(p.exp && p.exp * 1000 < Date.now());
  } catch (_e) { return false; }
}
const signedIn = () => { const t = token(); return !!t && !expired(t); };
const fmt = (n) => Number(n || 0).toLocaleString('en-US', { maximumFractionDigits: 4 });

async function req(path, opts = {}) {
  const r = await fetch(path.startsWith('http') ? path : BASE + path, {
    ...opts,
    headers: { 'Content-Type': 'application/json', ...(signedIn() ? { Authorization: `Bearer ${token()}` } : {}), ...(opts.headers || {}) },
  });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) {
    // FastAPI validation errors are arrays of objects: never show those raw.
    const err = new Error(typeof d.detail === 'string' && d.detail ? d.detail : 'Please check the details and try again.');
    err.status = r.status;
    err.code = typeof d.code === 'string' ? d.code : '';
    err.missing = Array.isArray(d.messages) ? d.messages : (Array.isArray(d.missing) ? d.missing : []);
    throw err;
  }
  return d;
}

let me = null;          // GET /me
let pending = null;     // { xid, amount, name, requestId } while the confirm step is open
let sending = false;

function show(id, on) { const el = $(id); if (el) el.hidden = !on; }
function step(n) { show('step1', n === 1); show('step2', n === 2); show('step3', n === 3); }

// ---------------- tabs ----------------
function selectTab(which) {
  const send = which === 'send';
  $('tabSend').setAttribute('aria-selected', String(send));
  $('tabLedger').setAttribute('aria-selected', String(!send));
  show('sendPanel', send);
  show('ledgerPanel', !send);
  if (!send && !ledgerLoaded) loadLedger(true);
}
$('tabSend').addEventListener('click', () => selectTab('send'));
$('tabLedger').addEventListener('click', () => selectTab('ledger'));

// ---------------- load my info ----------------
async function loadMe() {
  if (!signedIn()) { show('tfGuest', true); return; }
  try {
    me = await req('/me');
  } catch (e) {
    if (e.status === 401) { show('tfGuest', true); return; }
    $('tfErr').textContent = e.message;
    show('step1', true);
    return;
  }
  $('myXeraId').textContent = me.xera_id || '—';
  $('tfLimits').textContent = `${fmt(me.limits.min)} to ${fmt(me.limits.max)} per transfer, ${fmt(me.limits.daily_total)} per 24 hours`;
  show('tfMe', true);

  try {
    const w = await req(API + '/api/xera/wallet');
    $('tfBalance').textContent = fmt(w.balance);
  } catch (_e) { $('tfBalance').textContent = '—'; }

  if (!me.enabled) { show('tfClosed', true); return; }
  if (me.missing && me.missing.length) showRequirements(me.missing);
  step(1);
}

const REQ_TEXT = {
  KYC: 'Identity verification',
  FEE: 'One-time first-transfer fee',
};
function showRequirements(missing) {
  const ul = $('tfReqList');
  ul.textContent = '';
  (missing || []).forEach((m) => {
    const li = document.createElement('li');
    li.textContent = REQ_TEXT[m] || String(m);
    ul.appendChild(li);
  });
  show('tfReq', (missing || []).length > 0);
}

$('copyId').addEventListener('click', async () => {
  try { await navigator.clipboard.writeText($('myXeraId').textContent); $('copyId').textContent = 'Copied'; }
  catch (_e) { $('copyId').textContent = 'Select and copy'; }
  setTimeout(() => { $('copyId').textContent = 'Copy'; }, 1800);
});

// ---------------- step 1: check recipient ----------------
function parseAmount(raw) {
  const s = String(raw || '').trim().replace(/,/g, '');
  if (!/^\d+(\.\d{1,4})?$/.test(s)) return null;
  const n = Number(s);
  return n > 0 ? { text: s, num: n } : null;
}

$('step1').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const err = $('tfErr');
  err.textContent = '';
  const xid = $('tfXid').value.trim().toUpperCase();
  if (!/^XR-[A-Z2-9]{8}$/.test(xid)) { err.textContent = 'Enter a valid XERA ID, like XR-7K4M9P2Q.'; return; }
  const amt = parseAmount($('tfAmount').value);
  if (!amt) { err.textContent = 'Enter a valid amount (up to 4 decimals).'; return; }
  if (me && (amt.num < me.limits.min || amt.num > me.limits.max)) {
    err.textContent = `Amount must be between ${fmt(me.limits.min)} and ${fmt(me.limits.max)} XERA.`; return;
  }
  const btn = $('tfCheck');
  btn.disabled = true;
  try {
    const d = await req('/lookup', { method: 'POST', body: JSON.stringify({ xera_id: xid }) });
    if (d.is_self) { err.textContent = "That's your own XERA ID."; return; }
    // One request id per confirmation. A retry after a network drop reuses it,
    // so the server can never send the same transfer twice.
    pending = { xid: d.xera_id, amount: amt.text, name: d.name, requestId: (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random().toString(16).slice(2)).replace(/[^A-Za-z0-9_-]/g, '') };
    $('cfName').textContent = d.name;
    $('cfXid').textContent = d.xera_id;
    $('cfAmount').textContent = fmt(amt.num);
    $('cfErr').textContent = '';
    step(2);
  } catch (e) {
    err.textContent = e.message;
  } finally {
    btn.disabled = false;
  }
});

// ---------------- step 2: confirm and send ----------------
$('cfBack').addEventListener('click', () => { pending = null; $('cfErr').textContent = ''; step(1); });

$('cfSend').addEventListener('click', async () => {
  if (!pending || sending) return;
  sending = true;
  const btn = $('cfSend');
  btn.disabled = true;
  $('cfErr').textContent = '';
  try {
    const d = await req('/send', {
      method: 'POST',
      body: JSON.stringify({ xera_id: pending.xid, amount: pending.amount, request_id: pending.requestId }),
    });
    $('doneTitle').textContent = 'Sent';
    $('doneMsg').textContent = `${fmt(d.transfer.amount)} XERA sent to ${pending.name} (${pending.xid}).` +
      (d.new_balance != null ? ` Your balance is now ${fmt(d.new_balance)} XERA.` : '');
    if (d.new_balance != null) $('tfBalance').textContent = fmt(d.new_balance);
    pending = null;
    ledgerLoaded = false;
    step(3);
  } catch (e) {
    if (e.code === 'transfer_requirements_incomplete') {
      pending = null; step(1); showRequirements(me ? me.missing && me.missing.length ? me.missing : ['KYC', 'FEE'] : ['KYC', 'FEE']);
      $('tfErr').textContent = e.message;
    } else {
      // Keep `pending` (and its request id) so pressing Send again is safe after a dropped connection.
      $('cfErr').textContent = e.status ? e.message : 'Connection problem. Your transfer may not have gone through. Check your balance, or press Send again: it will not send twice.';
    }
  } finally {
    sending = false;
    btn.disabled = false;
  }
});

$('again').addEventListener('click', () => {
  $('tfXid').value = '';
  $('tfAmount').value = '';
  $('tfErr').textContent = '';
  step(1);
});

// ---------------- public ledger ----------------
let ledgerLoaded = false;
let ledgerOffset = 0;
const PAGE = 30;

function ledgerRow(t) {
  const row = document.createElement('div');
  row.className = 'tf-ledger-item';
  const l1 = document.createElement('div');
  l1.className = 'tf-l1';
  const who = document.createElement('span');
  who.textContent = `${t.sender} → ${t.recipient}`;
  const amt = document.createElement('span');
  amt.textContent = `${fmt(t.amount)} XERA`;
  l1.append(who, amt);
  const l2 = document.createElement('div');
  l2.className = 'tf-l2';
  const when = new Date(t.created_at);
  l2.textContent = `#${t.id} · ${isNaN(when) ? '' : when.toLocaleString()} · ${t.status}`;
  row.append(l1, l2);
  return row;
}

async function loadLedger(reset) {
  const list = $('ledgerList');
  const more = $('ledgerMore');
  $('ledgerErr').textContent = '';
  if (reset) { ledgerOffset = 0; list.textContent = ''; }
  more.disabled = true;
  try {
    const d = await req(`/ledger?limit=${PAGE}&offset=${ledgerOffset}`);
    const rows = d.transfers || [];
    rows.forEach((t) => list.appendChild(ledgerRow(t)));
    ledgerOffset += rows.length;
    ledgerLoaded = true;
    more.hidden = rows.length < PAGE;
    if (!list.children.length) {
      const empty = document.createElement('p');
      empty.className = 'tf-box';
      empty.textContent = 'No transfers yet.';
      list.appendChild(empty);
    }
  } catch (e) {
    $('ledgerErr').textContent = e.message;
  } finally {
    more.disabled = false;
  }
}
$('ledgerMore').addEventListener('click', () => loadLedger(false));

loadMe();
