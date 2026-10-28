// Admin KYC review queue. Authority is always the server: every call re-checks the admin token and
// the live admin_agents row, and only that API can set a user's KYC status. All user-supplied text is
// shown with textContent (never as HTML).
const API_BASE = import.meta.env.VITE_API_BASE_URL ||
  ((location.hostname === 'localhost' || location.hostname === '127.0.0.1') ? 'http://localhost:8000' : 'https://api.evoshub.xyz');
const TOKEN_KEY = 'evoshub_admin_token';
const $ = (id) => document.getElementById(id);
const STATUSES = [['PENDING', 'Pending'], ['PROVIDER_DECLINED', 'Provider rejected'], ['MORE_INFO', 'More info'], ['FAILED', 'Failed'], ['VERIFIED', 'Verified']];
let declinedCount = null;
let current = 'PENDING';

const token = () => { try { return sessionStorage.getItem(TOKEN_KEY) || ''; } catch (e) { return ''; } };
const toLogin = () => { try { sessionStorage.removeItem(TOKEN_KEY); } catch (e) { /* ignore */ } location.href = '/admin-login.html'; };
async function call(path, opts = {}) {
  const r = await fetch(API_BASE + path, { ...opts, headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token()}`, ...(opts.headers || {}) } });
  if (r.status === 401 || r.status === 403) { toLogin(); throw new Error('signed out'); }
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : 'Request failed');
  return d;
}

function el(tag, attrs = {}, kids = []) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) { if (k === 'class') n.className = v; else if (k === 'text') n.textContent = v; else if (k.startsWith('on')) n.addEventListener(k.slice(2), v); else n.setAttribute(k, v); }
  for (const c of [].concat(kids)) if (c) n.append(c);
  return n;
}

function card(it) {
  const note = el('textarea', { maxlength: '300', placeholder: 'Note for the user (required for Failed / More info)', 'aria-label': 'Note for the user' });
  const msg = el('p', { class: 'banner-error', role: 'alert' });
  const buttons = [];
  const isProvider = it.method === 'PROVIDER';
  const provOk = !isProvider || it.provider_status === 'APPROVED';
  const decide = (decision, cls, label) => {
    const b = el('button', { type: 'button', class: cls, text: label });
    b.addEventListener('click', async () => {
      msg.textContent = '';
      buttons.forEach((x) => { x.disabled = true; });
      try {
        await call(`/api/admin/xera/kyc/${it.user_id}/review`, { method: 'POST', body: JSON.stringify({ decision, note: note.value }) });
        await load();
      } catch (e) { msg.textContent = e.message; buttons.forEach((x) => { x.disabled = false; }); }
    });
    if (decision === 'VERIFIED' && !provOk) { b.disabled = true; b.title = 'The verification provider has not approved this case.'; }
    else buttons.push(b);
    return b;
  };
  const when = it.submitted_at ? new Date(it.submitted_at).toLocaleString() : '—';
  return el('div', { class: 'kyc-box kyc-item' }, [
    el('dl', {}, [
      el('dt', { text: 'User id' }), el('dd', { text: String(it.user_id) }),
      el('dt', { text: 'Legal name' }), el('dd', { text: it.legal_name || '—' }),
      el('dt', { text: 'Country' }), el('dd', { text: it.country || '—' }),
      el('dt', { text: 'ID type' }), el('dd', { text: it.id_type || '—' }),
      el('dt', { text: 'ID (last 4)' }), el('dd', { text: it.id_last4 || '—' }),
      el('dt', { text: 'Submitted' }), el('dd', { text: when }),
      isProvider ? el('dt', { text: 'Provider' }) : null, isProvider ? el('dd', { text: `${it.provider || '—'} · result: ${it.provider_status || '—'}` }) : null,
      isProvider && it.provider_reason ? el('dt', { text: 'Provider reason' }) : null, isProvider && it.provider_reason ? el('dd', { text: it.provider_reason }) : null,
      isProvider ? el('dt', { text: 'Provider reference' }) : null, isProvider ? el('dd', { text: it.provider_ref || '—' }) : null,
      it.review_note ? el('dt', { text: 'Last note' }) : null, it.review_note ? el('dd', { text: it.review_note }) : null,
    ]),
    isProvider ? el('p', { class: 'kyc-hint', text: it.provider_status === 'APPROVED'
      ? 'The provider approved this case. Open it in the provider portal and check the ID and selfie before you press Verify.'
      : it.provider_status === 'DECLINED'
        ? 'The provider rejected this case (for example an ID type it does not support). The user can try again and will be sent to the second provider.'
        : 'Waiting for the provider result. Verify unlocks once the provider approves.' }) : null,
    note,
    el('div', { class: 'kyc-actions' }, [decide('VERIFIED', 'kyc-ok', 'Verify'), decide('MORE_INFO', 'kyc-info', 'More info'), decide('FAILED', 'kyc-bad', 'Fail')]),
    msg,
  ]);
}

async function load() {
  $('kycError').textContent = '';
  try {
    const d = await call(`/api/admin/xera/kyc?status=${encodeURIComponent(current)}`);
    declinedCount = d.provider_declined_count ?? declinedCount;
    renderTabs();
    const list = $('kycList');
    list.replaceChildren(...(d.items.length ? d.items.map(card) : [el('p', { class: 'kyc-box', text: 'Nothing here.' })]));
  } catch (e) { if (e.message !== 'signed out') $('kycError').textContent = e.message; }
}

function renderTabs() {
  $('kycTabs').replaceChildren(...STATUSES.map(([v, label]) => {
    const badge = v === 'PROVIDER_DECLINED' && declinedCount ? ` (${declinedCount})` : '';
    const b = el('button', { type: 'button', text: label + badge, 'aria-pressed': String(v === current) });
    b.addEventListener('click', () => { current = v; renderTabs(); load(); });
    return b;
  }));
}

async function init() {
  if (!token()) { toLogin(); return; }
  $('kycSignout').addEventListener('click', toLogin);
  try {
    const me = await call('/api/admin/me');
    const u = me.user || {};
    $('kycWho').textContent = u.display_name || u.username || u.email || 'Admin';
  } catch (e) { return; }
  renderTabs();
  load();
}
init();
