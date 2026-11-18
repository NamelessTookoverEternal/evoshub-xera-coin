// Admin console: XERA P2P review tab. Authority is always the server: every call re-checks the admin
// token and the live admin_agents row. Nothing here moves money; the only write is the limits/fee form,
// which the server logs with the admin id. All values from the database are set with textContent.
import { API_BASE, token, signedOut } from './admin-console-session.js';

const BASE = '/api/admin/xera/p2p';
const $ = (id) => document.getElementById(id);
const fmt = (n) => Number(n || 0).toLocaleString('en-US', { maximumFractionDigits: 4 });
const when = (t) => { const d = new Date(t); return isNaN(d) ? '' : d.toLocaleString('en-GH', { dateStyle: 'medium', timeStyle: 'short' }); };

async function call(path, opts = {}) {
  const r = await fetch(API_BASE + path, { ...opts, headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token()}`, ...(opts.headers || {}) } });
  if (r.status === 401 || r.status === 403) { signedOut(); throw new Error('signed out'); }
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : 'Request failed');
  return d;
}
function el(tag, cls, text) { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; }
function row(tbody, cells, colspan) {
  const tr = el('tr');
  if (colspan) { const td = el('td', 'dx-dim', cells); td.colSpan = colspan; tr.append(td); }
  else cells.forEach((c) => { const td = el('td'); if (c instanceof Node) td.append(c); else td.textContent = c; tr.append(td); });
  tbody.append(tr);
}
const pill = (text, tone) => el('span', `dx-pill ${tone}`, text);
const err = (m) => { const b = $('p2p-err'); b.textContent = m || ''; b.hidden = !m; };

let cfg = null;
let off = 0;
const PAGE = 40;
let wired = false;

async function loadOverview() {
  const d = await call(`${BASE}/overview`);
  cfg = d.config;
  const v = d.fee_vault || {};
  const k = $('p2p-kpis'); k.textContent = '';
  const kpi = (l, val, f, tone) => {
    const c = el('div', 'dx-card dx-kpi'); const x = el('div', 'v', val); if (tone) x.style.color = tone;
    c.append(el('div', 'l', l), x); if (f) c.append(el('div', 'f', f)); k.append(c);
  };
  kpi('Fees collected', fmt(v.total_fees), 'XERA, look-only total', '#c8ff3e');
  kpi('Last 30 days', fmt(v.fees_last_30d), 'XERA in fees');
  kpi('Transfers', fmt(v.transfers_total), `${fmt(v.transfers_with_fee)} paid a fee`);
  kpi('Volume', fmt(v.volume_total), 'XERA sent between users');
  kpi('Unverified fee', `${fmt(cfg.unverified_fee_bps / 100)}%`, 'Charged on top of the amount');
  $('p2p-ipnote').textContent = d.ip_check_configured
    ? 'VPN check is on: new transfers are tagged VPN when the IP looks like a VPN or proxy.'
    : 'VPN check is off. IP addresses are still recorded. To switch the check on, set XERA_IP_INTEL_PROVIDER=proxycheck and XERA_IP_INTEL_API_KEY in Render.';
  $('p2p-flaghint').textContent = `A wallet is flagged when, in the last ${cfg.flag_window_days} days, it received XERA from ${cfg.flag_min_senders}+ different accounts that had not finished verification, or from 2+ accounts sharing one IP.`;
  const f = $('p2p-form');
  f.unverified_fee_percent.value = cfg.unverified_fee_bps / 100;
  ['unverified_daily_max', 'daily_max_total', 'min_amount', 'max_amount', 'flag_min_senders', 'flag_window_days'].forEach((n) => { f[n].value = cfg[n]; });
}

const REASON = { multiple_unverified_senders: 'Many unverified senders', senders_share_ip: 'Senders share an IP' };

async function loadFlagged() {
  const d = await call(`${BASE}/flagged`);
  const tb = $('p2p-flagged'); tb.textContent = '';
  if (!d.flagged.length) { row(tb, 'No suspicious wallets right now.', 5); return; }
  d.flagged.forEach((r) => {
    const why = el('div');
    (r.reasons || []).forEach((x) => { const p = pill(REASON[x] || x, 'warn'); p.style.marginRight = '4px'; why.append(p); });
    if (Number(r.vpn_transfers) > 0) why.append(pill(`VPN x${r.vpn_transfers}`, 'mute'));
    row(tb, [
      `${r.recipient_xera_id} (user ${r.recipient_user_id})`,
      why,
      `${r.distinct_senders} senders, ${r.unverified_senders} unverified, ${r.senders_sharing_ip} sharing an IP`,
      `${fmt(r.total_amount)} in ${r.transfers}`,
      `${when(r.first_at)} to ${when(r.last_at)}`,
    ]);
  });
}

async function loadTransfers(reset) {
  if (reset) { off = 0; $('p2p-rows').textContent = ''; }
  const q = new URLSearchParams({ limit: PAGE, offset: off });
  const rx = $('p2p-f-rec').value.trim(), sx = $('p2p-f-snd').value.trim();
  if (rx) q.set('recipient_xera_id', rx);
  if (sx) q.set('sender_xera_id', sx);
  const d = await call(`${BASE}/transfers?${q}`);
  const tb = $('p2p-rows');
  d.transfers.forEach((t) => {
    const tags = el('div');
    tags.append(pill(t.sender_verified ? 'verified' : 'unverified', t.sender_verified ? 'ok' : 'warn'));
    if (Number(t.fee_amount) > 0) { const p = pill(`fee ${fmt(t.fee_amount)}`, 'mute'); p.style.marginLeft = '4px'; tags.append(p); }
    const vpn = t.ip_risk && t.ip_risk.vpn;
    if (vpn === true) { const p = pill((t.ip_risk.type && String(t.ip_risk.type).toUpperCase() !== 'VPN') ? `VPN (${t.ip_risk.type})` : 'VPN', 'warn'); p.style.marginLeft = '4px'; tags.append(p); }
    else if (vpn === false) { const p = pill('no VPN', 'ok'); p.style.marginLeft = '4px'; tags.append(p); }
    row(tb, [when(t.created_at), `${t.sender_xera_id} → ${t.recipient_xera_id}`, `${fmt(t.amount)}`, tags, t.ip_address || 'not recorded']);
  });
  off += d.transfers.length;
  $('p2p-more').hidden = d.transfers.length < PAGE;
  if (!tb.children.length) row(tb, 'No transfers yet.', 5);
}

function wire() {
  $('p2p-filter').addEventListener('click', () => loadTransfers(true).catch((e) => err(e.message)));
  $('p2p-more').addEventListener('click', () => loadTransfers(false).catch((e) => err(e.message)));
  $('p2p-form').addEventListener('submit', async (ev) => {
    ev.preventDefault();
    err(''); $('p2p-saved').textContent = '';
    const f = ev.target; const body = {};
    const cur = { unverified_fee_percent: cfg.unverified_fee_bps / 100 };
    ['unverified_daily_max', 'daily_max_total', 'min_amount', 'max_amount', 'flag_min_senders', 'flag_window_days'].forEach((n) => { cur[n] = cfg[n]; });
    Object.keys(cur).forEach((n) => {
      const v = f[n].value.trim();
      if (v !== '' && Number(v) !== Number(cur[n])) body[n] = ['flag_min_senders', 'flag_window_days'].includes(n) ? parseInt(v, 10) : v;
    });
    if (!Object.keys(body).length) { err('Nothing changed.'); return; }
    body.reason = f.reason.value.trim();
    $('p2p-save').disabled = true;
    try {
      await call(`${BASE}/config`, { method: 'POST', body: JSON.stringify(body) });
      $('p2p-saved').textContent = 'Saved.'; f.reason.value = '';
      await Promise.all([loadOverview(), loadFlagged()]);
    } catch (e) { err(e.message); } finally { $('p2p-save').disabled = false; }
  });
}

// Called each time the tab opens (and by the Refresh button).
export async function initP2p() {
  if (!wired) { wired = true; wire(); }
  err('');
  try { await Promise.all([loadOverview(), loadFlagged(), loadTransfers(true)]); }
  catch (e) { if (e.message !== 'signed out') err(e.message); }
}
