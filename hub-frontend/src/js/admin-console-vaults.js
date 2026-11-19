// Admin console: Vaults tab. Look-only: every number is worked out on the server from the XERA ledger.
// Shows one card per vault plus the combined total; clicking a card opens that vault's activity.
// To add a vault: add it in python/xera/routes_admin_vaults.py and add a DETAIL entry below.
import { API_BASE, token, signedOut } from './admin-console-session.js';

const $ = (id) => document.getElementById(id);
const fmt = (n) => Number(n || 0).toLocaleString('en-US', { maximumFractionDigits: 4 });
const when = (t) => { const d = new Date(t); return isNaN(d) ? '—' : d.toLocaleString('en-GH', { dateStyle: 'medium', timeStyle: 'short' }); };
function el(tag, cls, text) { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; }

async function call(path) {
  const r = await fetch(API_BASE + path, { headers: { Authorization: `Bearer ${token()}` } });
  if (r.status === 401 || r.status === 403) { signedOut(); throw new Error('signed out'); }
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : 'Request failed');
  return d;
}
const err = (m) => { const b = $('vl-err'); b.textContent = m || ''; b.hidden = !m; };
const pill = (text, tone) => el('span', `dx-pill ${tone}`, text);

function fill(tbody, rows, cols, emptyText, build) {
  tbody.textContent = '';
  if (!rows.length) { const tr = el('tr'); const td = el('td', 'dx-dim', emptyText); td.colSpan = cols; tr.append(td); tbody.append(tr); return; }
  rows.forEach((r) => {
    const tr = el('tr');
    build(r).forEach((c) => { const td = el('td'); if (c instanceof Node) td.append(c); else td.textContent = c; tr.append(td); });
    tbody.append(tr);
  });
}

// One entry per vault that has an activity list.
const DETAIL = {
  discount: {
    title: 'Discount vault',
    async load() {
      const d = await call('/api/admin/xera/vault');
      const sm = d.summary || {};
      const k = $('vl-d-kpis'); k.textContent = '';
      [['Vault balance', fmt(sm.balance), 'XERA collected, after refunds', '#c8ff3e'], ['Orders', fmt(sm.orders), 'Discounted orders counted'],
       ['Last 30 days', fmt(sm.last_30_days), 'XERA collected'], ['Refunded', fmt(sm.total_refunded), 'Taken out of the vault']]
        .forEach(([l, v, f, tone]) => { const c = el('div', 'dx-card dx-kpi'); const x = el('div', 'v', v); if (tone) x.style.color = tone; c.append(el('div', 'l', l), x, el('div', 'f', f)); k.append(c); });
      fill($('vl-d-rows'), d.deposits || [], 5, 'No discount deposits yet.', (r) =>
        [when(r.created_at), r.order_ref || '—', `#${r.user_id}`, fmt(r.amount), pill(r.refunded ? 'Refunded' : 'Collected', r.refunded ? 'mute' : 'ok')]);
    },
  },
  p2p: {
    title: 'P2P fee vault',
    async load() {
      const d = await call('/api/admin/xera/vaults/p2p-fees');
      fill($('vl-p-rows'), d.fees || [], 6, 'No fees collected yet.', (r) =>
        [when(r.created_at), `${r.sender_xera_id} (#${r.sender_user_id})`, r.recipient_xera_id, fmt(r.amount), fmt(r.fee_amount),
         pill(r.sender_verified ? 'Verified' : 'Not verified', r.sender_verified ? 'ok' : 'warn')]);
    },
  },
};

function showView(which) { // 'list' | a DETAIL id
  $('vl-list').hidden = which !== 'list';
  Object.keys(DETAIL).forEach((id) => { const p = $(`vl-detail-${id}`); if (p) p.hidden = which !== id; });
  $('vl-back').hidden = which === 'list';
  $('vl-title').textContent = which === 'list' ? 'All vaults' : DETAIL[which].title;
  try { history.replaceState(null, '', which === 'list' ? '#vaults' : `#vaults/${which}`); } catch (_e) { /* ignore */ }
}

async function openDetail(id) {
  if (!DETAIL[id]) return showView('list');
  err('');
  showView(id);
  try { await DETAIL[id].load(); } catch (e) { if (e.message !== 'signed out') err(e.message); }
}

async function loadList() {
  const d = await call('/api/admin/xera/vaults');
  const total = Number(d.total) || 0;
  $('vl-total').textContent = fmt(d.total);
  const cards = $('vl-cards'); cards.textContent = '';
  (d.vaults || []).forEach((v) => {
    const c = el('button', 'dx-card dx-kpi'); c.type = 'button';
    c.style.cssText = 'text-align:left;cursor:pointer;font:inherit;color:inherit';
    const val = el('div', 'v', fmt(v.balance)); val.style.color = '#c8ff3e';
    const share = total > 0 ? ` · ${fmt((Number(v.balance) / total) * 100)}% of total` : '';
    c.append(el('div', 'l', v.label), val, el('div', 'f', `XERA${share}`), el('div', 'f', v.description),
             el('div', 'f', `${fmt(v.count)} ${v.count_label} · ${fmt(v.last_30_days)} in the last 30 days`),
             el('div', 'f', DETAIL[v.id] ? 'Click to see who and what →' : ''));
    if (DETAIL[v.id]) c.addEventListener('click', () => openDetail(v.id));
    cards.append(c);
  });
}

let wired = false;
export async function initVaults() {
  if (!wired) { wired = true; $('vl-back').addEventListener('click', () => { showView('list'); loadList().catch(() => {}); }); }
  err('');
  const sub = (location.hash.split('/')[1] || '').trim();
  try {
    if (sub && DETAIL[sub]) { showView(sub); await Promise.all([loadList(), DETAIL[sub].load()]); }
    else { showView('list'); await loadList(); }
  } catch (e) { if (e.message !== 'signed out') err(e.message); }
}
