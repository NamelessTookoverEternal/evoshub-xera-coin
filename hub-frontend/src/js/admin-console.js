// EVOXERA admin console: one page, one sign-in, a side menu of sections (same layout idea as DashXera).
// Talks only to the FastAPI backend with the admin bearer token. The server re-checks that token and the
// live admin_agents row on every call; nothing here is an authority. All server text is set with textContent.
import { API_BASE, TOKEN_KEY, token, authHeaders, setSignedOutHandler, signedOut } from './admin-console-session.js'

const XERA_ADMIN = `${API_BASE}/api/admin/xera`
const POLL_MS = 4000
const $ = (id) => document.getElementById(id)
const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n }

const SECTIONS = [
  { id: 'overview', label: 'Overview', icon: '▤' },
  { id: 'requests', label: 'Website requests', icon: '☰' },
  { id: 'token', label: 'Token dashboard', icon: '◈' },
  { id: 'vault', label: 'Discount vault', icon: '▣' },
  { id: 'wallet', label: 'XERA wallet (pilot)', icon: '◐' },
  { id: 'kyc', label: 'XERA KYC review', icon: '✓' },
  { id: 'updates', label: 'App updates', icon: '◇' },
  { id: 'products', label: 'Product switches', icon: '⏻' },
]

let section = ''
let requests = []
let activeId = null
let knownMsgs = new Set()
let reqTimer = null
let msgTimer = null
let kycPending = null
const loaded = {}

/* ------------------------------------------------------------------ api */
async function api(path, opts = {}) {
  const res = await fetch(path.startsWith('http') ? path : API_BASE + path, {
    ...opts,
    headers: { ...authHeaders(), ...(opts.body && !(opts.body instanceof FormData) ? { 'Content-Type': 'application/json' } : {}), ...(opts.headers || {}) },
  })
  if (res.status === 401 || res.status === 403) { signedOut(); throw new Error('SIGNED_OUT') }
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `Request failed (${res.status})`)
  return data
}
function showError(msg) { const b = $('dx-err'); b.textContent = msg || ''; b.hidden = !msg }
const fail = (e) => { if (e && e.message !== 'SIGNED_OUT') showError(e.message || 'Something went wrong.') }
const fmt = (n) => Number(n || 0).toLocaleString('en-US', { maximumFractionDigits: 4 })

/* ------------------------------------------------------------- sign-in */
function showGate(message) {
  clearInterval(reqTimer); clearInterval(msgTimer)
  $('dx-app').hidden = true
  $('dx-gate').hidden = false
  $('dx-login-err').textContent = message || ''
}
setSignedOutHandler(() => showGate('Signed out. Sign in again to continue.'))

$('dx-login').addEventListener('submit', async (e) => {
  e.preventDefault()
  const identifier = $('dx-id').value.trim(), password = $('dx-pw').value
  const err = $('dx-login-err'), btn = $('dx-login-btn')
  err.textContent = ''
  if (!identifier || !password) { err.textContent = 'Enter your username or email and password.'; return }
  btn.disabled = true; btn.textContent = 'Signing in…'
  try {
    const res = await fetch(`${API_BASE}/api/admin/login`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ identifier, password }) })
    const data = await res.json().catch(() => ({}))
    if (res.status === 429) err.textContent = data.detail || 'Too many attempts. Please wait and try again.'
    else if (data.status === 'ok' && data.token) {
      sessionStorage.setItem(TOKEN_KEY, data.token); $('dx-pw').value = ''
      await boot(); return
    } else if (data.status === 'not_authorized') err.textContent = "This account doesn't have admin access."
    else err.textContent = 'Incorrect username/email or password.'
  } catch { err.textContent = "Couldn't reach the server. Check your connection and try again." }
  finally { btn.disabled = false; btn.textContent = 'Sign in' }
})

$('dx-signout').addEventListener('click', () => { signedOut() })

/* ----------------------------------------------------------- navigation */
function buildNav() {
  const nav = $('dx-nav'); nav.textContent = ''
  SECTIONS.forEach((s) => {
    const b = el('button'); b.type = 'button'; b.dataset.sec = s.id
    b.append(el('span', 'ic', s.icon), el('span', 'lbl', s.label))
    const badge = el('span', 'dx-badge'); badge.id = `badge-${s.id}`; badge.hidden = true; b.append(badge)
    b.addEventListener('click', () => goTo(s.id))
    nav.append(b)
  })
}
function setBadge(id, n) { const b = $(`badge-${id}`); if (!b) return; b.textContent = n; b.hidden = !n }
function openDrawer(open) { $('dx-side').classList.toggle('open', open); $('dx-scrim').hidden = !open }
$('dx-toggle').addEventListener('click', () => openDrawer(true))
$('dx-scrim').addEventListener('click', () => openDrawer(false))

function goTo(id) {
  if (!SECTIONS.some((s) => s.id === id)) id = 'overview'
  section = id
  openDrawer(false); showError('')
  SECTIONS.forEach((s) => { const p = $(`sec-${s.id}`); if (p) p.hidden = s.id !== id })
  document.querySelectorAll('#dx-nav button').forEach((b) => b.classList.toggle('active', b.dataset.sec === id))
  $('dx-title').textContent = SECTIONS.find((s) => s.id === id).label
  $('dx-sub').textContent = ''
  try { history.replaceState(null, '', id === 'overview' ? location.pathname : `#${id}`) } catch { /* ignore */ }
  clearInterval(reqTimer)
  if (id !== 'requests') clearInterval(msgTimer)
  loadSection(id, false)
}

async function loadSection(id, force) {
  try {
    if (id === 'overview') await loadOverview()
    else if (id === 'requests') { await loadRequests(); clearInterval(reqTimer); reqTimer = setInterval(loadRequests, POLL_MS); if (activeId) startMsgPoll(activeId) }
    else if (id === 'token') { if (force || !loaded.token) { loaded.token = true; await Promise.all([loadTokenStats(), loadDailyConfig(), loadEcosystem()]) } }
    else if (id === 'wallet') await openWallet(force)
    else if (id === 'kyc') { const m = await import('./admin-console-kyc.js'); await m.initKyc() }
    else if (id === 'updates') { const m = await import('./admin-console-updates.js'); m.initUpdates() }
    else if (id === 'vault') await loadVault()
    else if (id === 'products') { const m = await import('./admin-console-products.js'); await m.initProducts() }
    $('dx-sub').textContent = `Synced ${new Date().toLocaleTimeString('en-GH')}`
  } catch (e) { fail(e) }
}
$('dx-refresh').addEventListener('click', () => { showError(''); loadSection(section, true) })

/* ------------------------------------------------------------- overview */
function kpi(label, value, foot, tone) {
  const c = el('div', 'dx-card dx-kpi')
  const v = el('div', 'v', value === undefined || value === null ? '—' : String(value)); if (tone) v.style.color = tone
  c.append(el('div', 'l', label), v); if (foot) c.append(el('div', 'f', foot))
  return c
}
async function loadOverview() {
  const [reqs, stats, kyc] = await Promise.all([
    api('/api/admin/website-requests').catch((e) => { if (e.message === 'SIGNED_OUT') throw e; return null }),
    api('/api/admin/xera/stats').catch((e) => { if (e.message === 'SIGNED_OUT') throw e; return null }),
    api('/api/admin/xera/kyc?status=PENDING').catch((e) => { if (e.message === 'SIGNED_OUT') throw e; return null }),
  ])
  const list = reqs ? (reqs.requests || []) : null
  if (list) requests = list
  const attn = $('ov-attn'); attn.textContent = ''
  const addAttn = (title, detail, target) => {
    const b = el('button'); b.type = 'button'
    const t = el('span', 't'); t.append(el('strong', '', title), el('span', '', detail))
    b.append(el('span', 'dot'), t, el('span', 'go', 'Open')); b.addEventListener('click', () => goTo(target)); attn.append(b)
  }
  const kpis = $('ov-kpis'); kpis.textContent = ''
  if (list) {
    const fresh = list.filter((r) => r.status === 'new').length
    const paid = list.filter((r) => r.payment_status === 'paid').length
    const waiting = list.filter((r) => r.payment_status === 'pending').length
    setBadge('requests', fresh)
    if (fresh) addAttn(`${fresh} new website request${fresh > 1 ? 's' : ''}`, 'Customers are waiting for a first reply.', 'requests')
    kpis.append(kpi('Website requests', list.length, 'All time'), kpi('New', fresh, 'Not opened yet', fresh ? '#fb923c' : undefined),
      kpi('Paid', paid, 'Payment confirmed', '#4ade80'), kpi('Payment pending', waiting, 'Started, not completed'))
  } else kpis.append(kpi('Website requests', '—', 'Could not load'))
  if (stats) kpis.append(kpi('XERA wallets', stats.total_users), kpi('Active miners', stats.active_miners), kpi('Mining distributed', fmt(stats.mining_distributed)))
  if (kyc) {
    kycPending = (kyc.items || []).length
    setBadge('kyc', kycPending)
    if (kycPending) addAttn(`${kycPending} KYC case${kycPending > 1 ? 's' : ''} to review`, 'Users are waiting before their first on-chain transfer.', 'kyc')
    kpis.append(kpi('KYC pending', kycPending, 'Waiting for review', kycPending ? '#fb923c' : undefined))
  }
}

/* ------------------------------------------------------ website requests */
function renderThreads() {
  const box = $('thread-list')
  if (!requests.length) { box.innerHTML = '<div class="dx-empty">No requests yet</div>'; return }
  box.textContent = ''
  requests.forEach((r) => {
    const item = el('div', 'dx-thread' + (r.id === activeId ? ' active' : ''))
    item.append(el('h4', '', `${r.full_name}  ·  ${r.package}`))
    const tag = r.payment_status === 'paid' ? ' · PAID' : r.payment_status === 'pending' ? ' · payment pending' : ''
    item.append(el('p', '', `${r.email} — ${r.status}${tag}`))
    item.addEventListener('click', () => openRequest(r.id))
    box.append(item)
  })
}
async function loadRequests() {
  try { requests = (await api('/api/admin/website-requests')).requests || []; renderThreads(); setBadge('requests', requests.filter((r) => r.status === 'new').length) }
  catch (e) { fail(e) }
}
function renderMessage(m) {
  const log = $('chat-log')
  const row = el('div', `dx-bubble-row ${m.sender_role === 'admin' ? 'admin' : 'user'}`)
  row.append(el('div', 'dx-bubble', m.body)); log.append(row); log.scrollTop = log.scrollHeight
}
async function loadMessages(id, silent) {
  try {
    const msgs = (await api(`/api/admin/website-requests/${id}/messages`)).messages || []
    if (id !== activeId) return
    if (!silent) { $('chat-log').textContent = ''; knownMsgs = new Set() }
    msgs.forEach((m) => { if (!knownMsgs.has(m.id)) { renderMessage(m); knownMsgs.add(m.id) } })
  } catch (e) { if (!silent) fail(e) }
}
function startMsgPoll(id) { clearInterval(msgTimer); msgTimer = setInterval(() => loadMessages(id, true), POLL_MS) }
async function loadFiles(id, box) {
  try {
    const d = await api(`/api/admin/website-requests/${id}/files`)
    if (!d.files || !d.files.length || activeId !== id) return
    const wrap = el('div', 'files')
    d.files.forEach((f) => { if (!f.url) return; const a = el('a', '', `${f.file_name} (${(f.size_bytes / 1024).toFixed(0)} KB)`); a.href = f.url; a.target = '_blank'; a.rel = 'noopener noreferrer'; wrap.append(a) })
    box.append(wrap)
  } catch { /* files are optional */ }
}
async function setStatus(id, status) {
  try { await api(`/api/admin/website-requests/${id}/status`, { method: 'PATCH', body: JSON.stringify({ status }) }); return true } catch (e) { fail(e); return false }
}
async function openRequest(id) {
  activeId = id; renderThreads()
  const r = requests.find((x) => x.id === id); if (!r) return
  const head = $('chat-head'); head.textContent = ''
  head.append(el('strong', '', `${r.full_name} — ${r.package}`))
  if (r.payment_status === 'paid') head.append(el('div', 'meta', `Paid GH₵${Number(r.amount_due_ghs || 0).toLocaleString()} via ${r.payment_method} · receipt ${r.receipt_no}`))
  loadFiles(id, head)
  $('status-select').disabled = false; $('status-select').value = r.status
  $('chat-input').disabled = false; $('chat-send').disabled = false
  await loadMessages(id, false); startMsgPoll(id)
  if (r.status === 'new' && (await setStatus(id, 'in_chat'))) { r.status = 'in_chat'; $('status-select').value = 'in_chat'; renderThreads() }
}
$('status-select').addEventListener('change', async () => {
  if (!activeId) return
  if (await setStatus(activeId, $('status-select').value)) { const r = requests.find((x) => x.id === activeId); if (r) r.status = $('status-select').value; renderThreads() }
})
async function sendReply() {
  const input = $('chat-input'), body = input.value.trim()
  if (!body || !activeId) return
  $('chat-send').disabled = true
  try {
    const d = await api(`/api/admin/website-requests/${activeId}/messages`, { method: 'POST', body: JSON.stringify({ body }) })
    if (d.message) { renderMessage(d.message); knownMsgs.add(d.message.id) }
    input.value = ''
  } catch (e) { fail(e) } finally { $('chat-send').disabled = false }
}
$('chat-send').addEventListener('click', sendReply)
$('chat-input').addEventListener('keydown', (e) => { if (e.key === 'Enter') sendReply() })

/* -------------------------------------------------------- token dashboard */
async function loadTokenStats() {
  const d = await api(`${XERA_ADMIN}/stats`)
  $('td-total-users').textContent = d.total_users ?? '—'
  $('td-active-miners').textContent = d.active_miners ?? '—'
  $('td-mining-distributed').textContent = fmt(d.mining_distributed)
  $('td-mining-remaining').textContent = fmt(d.mining_remaining)
}
async function loadDailyConfig() {
  const cfg = (await api(`${XERA_ADMIN}/daily-config`)).daily_config || {}
  $('dc-enabled').checked = !!cfg.enabled; $('dc-amount').value = cfg.reward_amount ?? ''
}
function note(id, text, kind) { const m = $(id); m.textContent = text; m.className = 'dx-msg' + (kind ? ' ' + kind : '') }
$('dc-save').addEventListener('click', async () => {
  note('dc-msg', '')
  const amount = parseFloat($('dc-amount').value)
  if (!Number.isFinite(amount) || amount <= 0) return note('dc-msg', 'Enter a reward amount greater than zero.', 'error')
  try {
    await api(`${XERA_ADMIN}/daily-config`, { method: 'PUT', body: JSON.stringify({ updates: { enabled: $('dc-enabled').checked, reward_amount: amount } }) })
    note('dc-msg', 'Saved.', 'ok')
  } catch (e) { if (e.message !== 'SIGNED_OUT') note('dc-msg', e.message || 'Could not save daily claim settings.', 'error') }
})

let links = []
function renderEco() {
  const tb = $('eco-rows'); tb.textContent = ''
  if (!links.length) { const tr = el('tr'); const td = el('td', 'dx-dim', 'No ecosystem links yet.'); td.colSpan = 5; tr.append(td); tb.append(tr); return }
  links.forEach((l) => {
    const tr = el('tr')
    const logo = el('td'); const img = el('img'); img.src = l.image_url; img.alt = ''; logo.append(img)
    const url = el('td', '', l.url); url.style.cssText = 'max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap'
    const act = el('td'); const cb = el('input'); cb.type = 'checkbox'; cb.checked = !!l.is_active
    cb.addEventListener('change', async () => { try { await api(`${XERA_ADMIN}/ecosystem/${l.id}`, { method: 'PUT', body: JSON.stringify({ is_active: cb.checked }) }); l.is_active = cb.checked } catch (e) { fail(e); loadEcosystem() } })
    act.append(cb)
    const del = el('td'); const b = el('button', 'dx-btn sm danger', 'Delete'); b.type = 'button'
    b.addEventListener('click', async () => {
      if (!confirm('Remove this ecosystem link?')) return
      try { await api(`${XERA_ADMIN}/ecosystem/${l.id}`, { method: 'DELETE' }); links = links.filter((x) => x.id !== l.id); renderEco() } catch (e) { fail(e) }
    })
    del.append(b); tr.append(logo, el('td', '', l.name), url, act, del); tb.append(tr)
  })
}
async function loadEcosystem() { links = (await api(`${XERA_ADMIN}/ecosystem`)).links || []; renderEco() }
$('eco-add').addEventListener('click', async () => {
  note('eco-msg', '')
  const name = $('eco-name').value.trim(), url = $('eco-url').value.trim(), image = $('eco-image').value.trim()
  if (!name || !url || !image) return note('eco-msg', 'Fill in name, URL, and logo image URL.', 'error')
  try {
    await api(`${XERA_ADMIN}/ecosystem`, { method: 'POST', body: JSON.stringify({ name, url, image_url: image, sort_order: links.length, is_active: true }) })
    $('eco-name').value = ''; $('eco-url').value = ''; $('eco-image').value = ''
    note('eco-msg', 'Added.', 'ok'); await loadEcosystem()
  } catch (e) { if (e.message !== 'SIGNED_OUT') note('eco-msg', e.message || 'Could not add this link.', 'error') }
})

/* ------------------------------------------------------------ discount vault (look-only) */
async function loadVault() {
  const d = await api(`${XERA_ADMIN}/vault`)
  const sm = d.summary || {}
  const k = $('vt-kpis'); k.textContent = ''
  k.append(kpi('Vault balance', fmt(sm.balance), 'XERA collected, after refunds', '#c8ff3e'),
    kpi('Orders', sm.orders ?? 0, 'Discounted orders counted'),
    kpi('Last 30 days', fmt(sm.last_30_days), 'XERA collected'),
    kpi('Refunded', fmt(sm.total_refunded), 'Taken out of the vault'))
  const tb = $('vt-rows'); tb.textContent = ''
  const rows = d.deposits || []
  if (!rows.length) { const tr = el('tr'); const td = el('td', 'dx-dim', 'No discount deposits yet.'); td.colSpan = 5; tr.append(td); tb.append(tr); return }
  rows.forEach((r) => {
    const tr = el('tr')
    const when = r.created_at ? new Date(r.created_at).toLocaleString('en-GH', { dateStyle: 'medium', timeStyle: 'short' }) : '—'
    const pill = el('span', 'dx-pill ' + (r.refunded ? 'mute' : 'ok'), r.refunded ? 'Refunded' : 'Collected')
    const st = el('td'); st.append(pill)
    tr.append(el('td', '', when), el('td', '', r.order_ref || '—'), el('td', '', `#${r.user_id}`), el('td', '', fmt(r.amount)), st)
    tb.append(tr)
  })
}

/* ------------------------------------------------------------ XERA wallet */
// The wallet panel itself is the shared xera-chain.js module. It must be told it is in admin pilot mode
// BEFORE it loads (it normally decides that from the page URL), so we pass the config explicitly.
// Claim signing is still gated server-side by the pilot flag and the admin token.
let chainLoaded = false
function chainBox(name, c) {
  const box = el('div'); box.append(el('b', '', name))
  const a = el('div', c.distributor_configured ? 'pilot-ok' : 'pilot-off', c.distributor_configured ? 'Contract address set' : 'Contract address missing')
  const u = el('div', '', c.user_claims_open ? 'Open to users' : 'Closed to users'); u.style.opacity = '.75'
  box.append(a, u); return box
}
async function openWallet() {
  $('pilotError').textContent = ''
  try {
    const s = await api('/api/admin/xera/pilot/status')
    const on = !!s.pilot_enabled
    $('pilotBadge').textContent = on ? 'PILOT ON' : 'PILOT OFF'; $('pilotBadge').className = 'pilot-badge ' + (on ? 'pilot-ok' : 'pilot-off')
    const rl = s.relayer || {}
    $('pilotFlag').textContent = (on ? 'Claim signing is enabled for admins. You can link wallets and try a claim.'
      : 'You can link wallets, but claim signing is off. Set XERA_ADMIN_ONCHAIN_PILOT=true on the backend to try a claim.') +
      (rl.configured ? ` Automatic sending is ready (gas wallet ${rl.address.slice(0, 6)}…${rl.address.slice(-4)}). Keep it funded with a little tBNB.`
        : ' Automatic sending is NOT set up: add XERA_RELAYER_PRIVATE_KEY (or XERA_RELAYER_USE_SIGNER=true on testnet) on the backend.')
    $('pilotChains').replaceChildren(chainBox('BNB', s.chains.BNB), chainBox('TON', s.chains.TON))
    $('pilotStatus').hidden = false
  } catch (e) { if (e.message === 'SIGNED_OUT') return; $('pilotError').textContent = e.message }
  if (!chainLoaded) {
    chainLoaded = true
    window.XERA_CHAIN_CONFIG = { prefix: '/api/admin/xera/pilot', noMigration: true, relay: true, getToken: token, onUnauthorized: signedOut }
    window.__xeraOnchainEnabled = true   // the panel refuses to open without this; the server still enforces the pilot flag
    await import('./xera-chain.js')
  }
  $('openChain').click()
}

/* ------------------------------------------------------------------- boot */
async function boot() {
  if (!token()) return showGate('')
  try {
    const me = await fetch(`${API_BASE}/api/admin/me`, { headers: authHeaders() })
    if (!me.ok) { try { sessionStorage.removeItem(TOKEN_KEY) } catch { /* ignore */ } return showGate(me.status === 401 || me.status === 403 ? '' : 'Could not verify your session.') }
    const u = (await me.json()).user || {}
    $('dx-who').textContent = `Signed in as ${u.display_name || u.username || u.email || 'Admin'}`
  } catch { return showGate("Couldn't reach the server. Check your connection and try again.") }
  $('dx-gate').hidden = true; $('dx-app').hidden = false
  if (!$('dx-nav').children.length) buildNav()
  goTo(location.hash.slice(1) || 'overview')
  // Fill the menu badges without waiting for the person to open Overview.
  if (section !== 'overview') loadOverview().catch(() => {})
}
window.addEventListener('hashchange', () => { if (!$('dx-app').hidden) goTo(location.hash.slice(1) || 'overview') })
boot()
