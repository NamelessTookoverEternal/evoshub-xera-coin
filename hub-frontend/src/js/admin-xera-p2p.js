// Admin review of XERA P2P transfers. Authority is always the server: each call re-checks the admin
// token. All values from the database are shown with textContent (never as HTML).
const API_BASE = import.meta.env.VITE_API_BASE_URL ||
  ((location.hostname === 'localhost' || location.hostname === '127.0.0.1') ? 'http://localhost:8000' : 'https://api.evoshub.xyz');
const TOKEN_KEY = 'evoshub_admin_token';
const BASE = '/api/admin/xera/p2p';
const $ = (id) => document.getElementById(id);

const token = () => { try { return sessionStorage.getItem(TOKEN_KEY) || ''; } catch (e) { return ''; } };
const toLogin = () => { try { sessionStorage.removeItem(TOKEN_KEY); } catch (e) { /* ignore */ } (window.top || window).location.href = '/admin-login.html'; };
async function call(path, opts = {}) {
  const r = await fetch(API_BASE + path, { ...opts, headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token()}`, ...(opts.headers || {}) } });
  if (r.status === 401 || r.status === 403) { toLogin(); throw new Error('signed out'); }
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : 'Request failed');
  return d;
}
function el(tag, attrs = {}, kids = []) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) { if (k === 'class') n.className = v; else if (k === 'text') n.textContent = v; else n.setAttribute(k, v); }
  for (const c of [].concat(kids)) if (c) n.append(c);
  return n;
}
const fmt = (n) => Number(n || 0).toLocaleString('en-US', { maximumFractionDigits: 4 });
const when = (t) => { const d = new Date(t); return isNaN(d) ? '' : d.toLocaleString(); };
const err = (m) => { $('ppError').textContent = m || ''; };

if (!token()) toLogin();
$('ppSignout').addEventListener('click', toLogin);
$('ppWho').textContent = 'Admin';

let cfg = null;

function stat(label, value) { return el('div', { class: 'pp-stat' }, [el('span', { text: label }), el('b', { text: value })]); }

async function loadOverview() {
  const d = await call(`${BASE}/overview`);
  cfg = d.config;
  const v = d.fee_vault || {};
  const box = $('ppStats');
  box.replaceChildren(
    stat('Fees collected (look-only)', `${fmt(v.total_fees)} XERA`),
    stat('Fees, last 30 days', `${fmt(v.fees_last_30d)} XERA`),
    stat('Transfers', fmt(v.transfers_total)),
    stat('Transfers with a fee', fmt(v.transfers_with_fee)),
    stat('Volume', `${fmt(v.volume_total)} XERA`),
    stat('Unverified fee', `${fmt(cfg.unverified_fee_bps / 100)}%`),
  );
  $('ppIpNote').textContent = d.ip_check_configured
    ? 'VPN check is on: new transfers are tagged "VPN" when the IP looks like a VPN or proxy.'
    : 'VPN check is off. IP addresses are still recorded. To switch the check on, set XERA_IP_INTEL_PROVIDER=proxycheck and XERA_IP_INTEL_API_KEY in Render.';
  $('ppFlagHint').textContent = `A wallet is flagged when, in the last ${cfg.flag_window_days} days, it received XERA from ${cfg.flag_min_senders}+ different accounts that had not finished verification, or from 2+ accounts sharing one IP.`;
  const f = $('ppForm');
  f.unverified_fee_percent.value = cfg.unverified_fee_bps / 100;
  for (const k of ['unverified_daily_max', 'daily_max_total', 'min_amount', 'max_amount', 'flag_min_senders', 'flag_window_days']) f[k].value = cfg[k];
}

const REASON = { multiple_unverified_senders: 'Many unverified senders', senders_share_ip: 'Senders share an IP' };

async function loadFlagged() {
  const d = await call(`${BASE}/flagged`);
  const box = $('ppFlagged');
  box.replaceChildren();
  if (!d.flagged.length) { box.append(el('p', { class: 'pp-muted', text: 'No suspicious wallets right now.' })); return; }
  d.flagged.forEach((r) => {
    const tags = el('div', {}, (r.reasons || []).map((x) => el('span', { class: 'pp-tag pp-bad', text: REASON[x] || x })));
    if (Number(r.vpn_transfers) > 0) tags.append(el('span', { class: 'pp-tag pp-warn', text: `VPN x${r.vpn_transfers}` }));
    box.append(el('div', { class: 'pp-item' }, [
      el('div', { class: 'pp-line' }, [el('b', { text: r.recipient_xera_id }), el('span', { text: `${fmt(r.total_amount)} XERA in ${r.transfers} transfers` })]),
      tags,
      el('div', { class: 'pp-muted', text: `${r.distinct_senders} senders · ${r.unverified_senders} unverified · ${r.senders_sharing_ip} sharing an IP · ${when(r.first_at)} to ${when(r.last_at)}` }),
      el('div', { class: 'pp-muted', text: `User id ${r.recipient_user_id}` }),
    ]));
  });
}

let off = 0;
const PAGE = 40;
async function loadTransfers(reset) {
  if (reset) { off = 0; $('ppTransfers').replaceChildren(); }
  const q = new URLSearchParams({ limit: PAGE, offset: off });
  const rx = $('ppFilterRecipient').value.trim(); const sx = $('ppFilterSender').value.trim();
  if (rx) q.set('recipient_xera_id', rx);
  if (sx) q.set('sender_xera_id', sx);
  const d = await call(`${BASE}/transfers?${q}`);
  const box = $('ppTransfers');
  d.transfers.forEach((t) => {
    const tags = el('div', {});
    tags.append(el('span', { class: `pp-tag ${t.sender_verified ? 'pp-ok' : 'pp-warn'}`, text: t.sender_verified ? 'verified' : 'unverified' }));
    if (Number(t.fee_amount) > 0) tags.append(el('span', { class: 'pp-tag', text: `fee ${fmt(t.fee_amount)}` }));
    if (t.ip_risk && t.ip_risk.vpn === true) tags.append(el('span', { class: 'pp-tag pp-bad', text: (t.ip_risk.type && t.ip_risk.type.toUpperCase() !== 'VPN') ? `VPN (${t.ip_risk.type})` : 'VPN' }));
    else if (t.ip_risk && t.ip_risk.vpn === false) tags.append(el('span', { class: 'pp-tag pp-ok', text: 'no VPN' }));
    box.append(el('div', { class: 'pp-item' }, [
      el('div', { class: 'pp-line' }, [el('b', { text: `${t.sender_xera_id} → ${t.recipient_xera_id}` }), el('span', { text: `${fmt(t.amount)} XERA` })]),
      tags,
      el('div', { class: 'pp-muted', text: `#${t.id} · ${when(t.created_at)} · IP ${t.ip_address || 'not recorded'} · users ${t.sender_user_id} → ${t.recipient_user_id}` }),
    ]));
  });
  off += d.transfers.length;
  $('ppMore').hidden = d.transfers.length < PAGE;
  if (!box.children.length) box.append(el('p', { class: 'pp-muted', text: 'No transfers yet.' }));
}
$('ppFilterGo').addEventListener('click', () => loadTransfers(true).catch((e) => err(e.message)));
$('ppMore').addEventListener('click', () => loadTransfers(false).catch((e) => err(e.message)));

$('ppForm').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  err(''); $('ppSaved').textContent = '';
  const f = ev.target;
  const body = {};
  // Only send what the admin actually changed.
  const cur = { unverified_fee_percent: String(cfg.unverified_fee_bps / 100) };
  for (const k of ['unverified_daily_max', 'daily_max_total', 'min_amount', 'max_amount', 'flag_min_senders', 'flag_window_days']) cur[k] = String(cfg[k]);
  for (const k of Object.keys(cur)) {
    const v = f[k].value.trim();
    if (v !== '' && Number(v) !== Number(cur[k])) body[k] = ['flag_min_senders', 'flag_window_days'].includes(k) ? parseInt(v, 10) : v;
  }
  if (!Object.keys(body).length) { err('Nothing changed.'); return; }
  body.reason = f.reason.value.trim();
  $('ppSave').disabled = true;
  try {
    await call(`${BASE}/config`, { method: 'POST', body: JSON.stringify(body) });
    $('ppSaved').textContent = 'Saved.';
    f.reason.value = '';
    await Promise.all([loadOverview(), loadFlagged()]);
  } catch (e) { err(e.message); } finally { $('ppSave').disabled = false; }
});

(async () => {
  try { await Promise.all([loadOverview(), loadFlagged(), loadTransfers(true)]); }
  catch (e) { if (e.message !== 'signed out') err(e.message); }
})();
