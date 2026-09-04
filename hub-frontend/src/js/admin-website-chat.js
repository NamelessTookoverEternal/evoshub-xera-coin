// EVOSHUB — Admin/agent inbox for the Website Creation product.
//
// This talks only to the FastAPI backend, never to Supabase directly.
// Why: website_requests / website_chat_messages RLS requires a real
// Supabase Auth session (auth.uid()), and admin agents don't have one —
// they authenticate via the custom public.users + admin_agents flow. The
// backend re-verifies that same admin bearer token (already sitting in
// sessionStorage from admin-login.js — no separate sign-in step needed)
// and does the actual Supabase reads/writes server-side with the
// service_role key, which is allowed to bypass RLS.
//
// "Live" chat here means polling every few seconds, not a Supabase
// Realtime subscription — Realtime's client-side channel also assumes a
// Supabase Auth session, which doesn't apply to admins for the same
// reason above.

const API_BASE = "https://evoshub-xera-coin.onrender.com"
// The XERA admin API is a separate router mounted on the same backend and
// gated by the exact same admin_agents-backed token as /api/admin above —
// one admin login covers both, so no second sign-in is needed here.
const XERA_ADMIN_BASE = `${API_BASE}/api/admin/xera`
const TOKEN_STORAGE_KEY = "evoshub_admin_token"
const POLL_INTERVAL_MS = 4000

const whoamiEl    = document.getElementById('admin-whoami')
const signoutBtn  = document.getElementById('admin-signout')
const listEl      = document.getElementById('thread-list')
const headerEl    = document.getElementById('chat-header')
const logEl       = document.getElementById('admin-chat-log')
const statusSel   = document.getElementById('status-select')
const inputEl     = document.getElementById('admin-chat-input')
const sendBtn     = document.getElementById('admin-chat-send')

let requests = []
let activeRequestId = null
let knownMessageIds = new Set()
let requestsPollTimer = null
let messagesPollTimer = null

function authHeaders() {
  const token = sessionStorage.getItem(TOKEN_STORAGE_KEY)
  return token ? { Authorization: `Bearer ${token}` } : {}
}

function redirectToLogin() {
  window.location.href = '/admin-login.html'
}

// --- Gate the whole page behind a real server-side admin check -------------------
async function guard() {
  const token = sessionStorage.getItem(TOKEN_STORAGE_KEY)
  if (!token) {
    redirectToLogin()
    return null
  }

  try {
    const res = await fetch(`${API_BASE}/api/admin/me`, { headers: authHeaders() })
    if (!res.ok) {
      sessionStorage.removeItem(TOKEN_STORAGE_KEY)
      redirectToLogin()
      return null
    }
    const data = await res.json()
    whoamiEl.textContent = data.user?.display_name || data.user?.username || data.user?.email || 'Agent'
    return data.user
  } catch {
    // Network error on the guard check shouldn't force a logout — leave
    // the token in place and let the user retry, rather than bouncing
    // them out on a transient connectivity blip.
    console.error('[admin-inbox] guard check failed (network error)')
    return null
  }
}

signoutBtn.addEventListener('click', () => {
  clearInterval(requestsPollTimer)
  clearInterval(messagesPollTimer)
  sessionStorage.removeItem(TOKEN_STORAGE_KEY)
  redirectToLogin()
})

// --- Thread list ------------------------------------------------------------------
function renderThreadList() {
  if (!requests.length) {
    listEl.innerHTML = '<div class="empty-state">No requests yet</div>'
    return
  }
  listEl.innerHTML = ''
  requests.forEach((r) => {
    const item = document.createElement('div')
    item.className = 'thread-item' + (r.id === activeRequestId ? ' active' : '')
    const name = document.createElement('h4')
    name.textContent = r.full_name + '  ·  ' + r.package
    const meta = document.createElement('p')
    meta.textContent = `${r.email} — ${r.status}`
    item.appendChild(name)
    item.appendChild(meta)
    item.addEventListener('click', () => openRequest(r.id))
    listEl.appendChild(item)
  })
}

async function loadRequests() {
  try {
    const res = await fetch(`${API_BASE}/api/admin/website-requests`, { headers: authHeaders() })
    if (res.status === 401 || res.status === 403) return redirectToLogin()
    if (!res.ok) throw new Error(`status ${res.status}`)
    const data = await res.json()
    requests = data.requests || []
    renderThreadList()
  } catch (err) {
    console.error('[admin-inbox] failed to load requests', err)
  }
}

function startRequestsPolling() {
  clearInterval(requestsPollTimer)
  requestsPollTimer = setInterval(loadRequests, POLL_INTERVAL_MS)
}

// --- Chat panel ---------------------------------------------------------------------
function renderMessage(msg) {
  const row = document.createElement('div')
  row.style.cssText = 'display:flex; flex-direction:column; align-items:' +
    (msg.sender_role === 'admin' ? 'flex-end' : 'flex-start') + ';'
  const bubble = document.createElement('div')
  bubble.style.cssText = 'max-width:70%; padding:9px 13px; border-radius:12px; font-size:13.5px; line-height:1.5;' +
    (msg.sender_role === 'admin'
      ? 'background:var(--blue); color:#fff;'
      : 'background:var(--surface2); color:var(--text);')
  bubble.textContent = msg.body // textContent only — never innerHTML with chat text
  row.appendChild(bubble)
  logEl.appendChild(row)
  logEl.scrollTop = logEl.scrollHeight
}

async function loadMessages(requestId, { silent = false } = {}) {
  try {
    const res = await fetch(`${API_BASE}/api/admin/website-requests/${requestId}/messages`, {
      headers: authHeaders(),
    })
    if (res.status === 401 || res.status === 403) return redirectToLogin()
    if (!res.ok) throw new Error(`status ${res.status}`)
    const data = await res.json()
    const messages = data.messages || []

    if (!silent) {
      // Full repaint on first open.
      logEl.innerHTML = ''
      knownMessageIds = new Set()
      messages.forEach((m) => {
        renderMessage(m)
        knownMessageIds.add(m.id)
      })
      return
    }

    // Polling tick: only append messages we haven't rendered yet, so the
    // log doesn't flicker/rebuild every 4 seconds.
    messages.forEach((m) => {
      if (!knownMessageIds.has(m.id)) {
        renderMessage(m)
        knownMessageIds.add(m.id)
      }
    })
  } catch (err) {
    console.error('[admin-inbox] failed to load messages', err)
  }
}

function startMessagesPolling(requestId) {
  clearInterval(messagesPollTimer)
  messagesPollTimer = setInterval(() => loadMessages(requestId, { silent: true }), POLL_INTERVAL_MS)
}

async function openRequest(requestId) {
  activeRequestId = requestId
  renderThreadList()

  const req = requests.find((r) => r.id === requestId)
  headerEl.innerHTML = ''
  const h = document.createElement('strong')
  h.textContent = `${req.full_name} — ${req.package}`
  headerEl.appendChild(h)

  statusSel.disabled = false
  statusSel.value = req.status
  inputEl.disabled = false
  sendBtn.disabled = false

  await loadMessages(requestId)
  startMessagesPolling(requestId)

  // Mark as in_chat the first time an agent opens it.
  if (req.status === 'new') {
    await updateStatus(requestId, 'in_chat')
    req.status = 'in_chat'
    statusSel.value = 'in_chat'
    renderThreadList()
  }
}

async function updateStatus(requestId, status) {
  try {
    const res = await fetch(`${API_BASE}/api/admin/website-requests/${requestId}/status`, {
      method: 'PATCH',
      headers: { ...authHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ status }),
    })
    if (res.status === 401 || res.status === 403) return redirectToLogin()
    if (!res.ok) throw new Error(`status ${res.status}`)
  } catch (err) {
    console.error('[admin-inbox] status update failed', err)
  }
}

statusSel.addEventListener('change', async () => {
  if (!activeRequestId) return
  await updateStatus(activeRequestId, statusSel.value)
  const req = requests.find((r) => r.id === activeRequestId)
  if (req) req.status = statusSel.value
  renderThreadList()
})

async function sendReply() {
  const body = inputEl.value.trim()
  if (!body || !activeRequestId) return

  sendBtn.disabled = true
  try {
    const res = await fetch(`${API_BASE}/api/admin/website-requests/${activeRequestId}/messages`, {
      method: 'POST',
      headers: { ...authHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ body }),
    })
    if (res.status === 401 || res.status === 403) return redirectToLogin()
    if (!res.ok) throw new Error(`status ${res.status}`)
    const data = await res.json()
    if (data.message) {
      renderMessage(data.message)
      knownMessageIds.add(data.message.id)
    }
    inputEl.value = ''
  } catch (err) {
    console.error('[admin-inbox] send failed', err)
  } finally {
    sendBtn.disabled = false
  }
}

sendBtn.addEventListener('click', sendReply)
inputEl.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') sendReply()
})

// --- Token dashboard (XERA) --------------------------------------------------------
const tabRequestsBtn = document.getElementById('tab-requests')
const tabTokenBtn    = document.getElementById('tab-token')
const panelRequests  = document.getElementById('panel-requests')
const panelToken     = document.getElementById('panel-token')

let tokenDashboardLoaded = false

function xeraAdminHeaders() {
  return { ...authHeaders(), 'Content-Type': 'application/json' }
}

function fmtAmount(n) {
  return Number(n || 0).toLocaleString('en-US', { maximumFractionDigits: 4 })
}

async function loadTokenStats() {
  try {
    const res = await fetch(`${XERA_ADMIN_BASE}/stats`, { headers: authHeaders() })
    if (res.status === 401 || res.status === 403) return redirectToLogin()
    if (!res.ok) throw new Error(`status ${res.status}`)
    const data = await res.json()
    document.getElementById('td-total-users').textContent = data.total_users ?? '—'
    document.getElementById('td-active-miners').textContent = data.active_miners ?? '—'
    document.getElementById('td-mining-distributed').textContent = fmtAmount(data.mining_distributed)
    document.getElementById('td-mining-remaining').textContent = fmtAmount(data.mining_remaining)
  } catch (err) {
    console.error('[token-dashboard] failed to load stats', err)
  }
}

async function loadDailyConfig() {
  try {
    const res = await fetch(`${XERA_ADMIN_BASE}/daily-config`, { headers: authHeaders() })
    if (res.status === 401 || res.status === 403) return redirectToLogin()
    if (!res.ok) throw new Error(`status ${res.status}`)
    const data = await res.json()
    const cfg = data.daily_config || {}
    document.getElementById('dc-enabled').checked = !!cfg.enabled
    document.getElementById('dc-amount').value = cfg.reward_amount ?? ''
  } catch (err) {
    console.error('[token-dashboard] failed to load daily config', err)
  }
}

document.getElementById('dc-save').addEventListener('click', async () => {
  const msgEl = document.getElementById('dc-msg')
  msgEl.textContent = ''
  msgEl.className = 'td-msg'

  const enabled = document.getElementById('dc-enabled').checked
  const amount = parseFloat(document.getElementById('dc-amount').value)
  if (!Number.isFinite(amount) || amount <= 0) {
    msgEl.textContent = 'Enter a reward amount greater than zero.'
    msgEl.className = 'td-msg error'
    return
  }

  try {
    const res = await fetch(`${XERA_ADMIN_BASE}/daily-config`, {
      method: 'PUT',
      headers: xeraAdminHeaders(),
      body: JSON.stringify({ updates: { enabled, reward_amount: amount } }),
    })
    if (res.status === 401 || res.status === 403) return redirectToLogin()
    const data = await res.json().catch(() => ({}))
    if (!res.ok) throw new Error(data.detail || `status ${res.status}`)
    msgEl.textContent = 'Saved.'
    msgEl.className = 'td-msg ok'
  } catch (err) {
    msgEl.textContent = err.message || 'Could not save daily claim settings.'
    msgEl.className = 'td-msg error'
  }
})

// --- Ecosystem links CRUD -----------------------------------------------------------

let ecosystemLinks = []

function renderEcosystemRows() {
  const tbody = document.getElementById('eco-rows')
  if (!ecosystemLinks.length) {
    tbody.innerHTML = '<tr><td colspan="5" style="color:var(--text3);">No ecosystem links yet.</td></tr>'
    return
  }
  tbody.innerHTML = ''
  ecosystemLinks.forEach((link) => {
    const tr = document.createElement('tr')

    const logoTd = document.createElement('td')
    const img = document.createElement('img')
    img.src = link.image_url
    img.alt = ''
    logoTd.appendChild(img)

    const nameTd = document.createElement('td')
    nameTd.textContent = link.name

    const urlTd = document.createElement('td')
    urlTd.style.cssText = 'max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;'
    urlTd.textContent = link.url

    const activeTd = document.createElement('td')
    const activeCb = document.createElement('input')
    activeCb.type = 'checkbox'
    activeCb.checked = !!link.is_active
    activeCb.addEventListener('change', () => toggleEcosystemActive(link.id, activeCb.checked))
    activeTd.appendChild(activeCb)

    const actionsTd = document.createElement('td')
    actionsTd.className = 'actions'
    const delBtn = document.createElement('button')
    delBtn.className = 'btn btn--ghost'
    delBtn.textContent = 'Delete'
    delBtn.addEventListener('click', () => deleteEcosystemLink(link.id))
    actionsTd.appendChild(delBtn)

    tr.append(logoTd, nameTd, urlTd, activeTd, actionsTd)
    tbody.appendChild(tr)
  })
}

async function loadEcosystemLinks() {
  const tbody = document.getElementById('eco-rows')
  try {
    const res = await fetch(`${XERA_ADMIN_BASE}/ecosystem`, { headers: authHeaders() })
    if (res.status === 401 || res.status === 403) return redirectToLogin()
    if (!res.ok) throw new Error(`status ${res.status}`)
    const data = await res.json()
    ecosystemLinks = data.links || []
    renderEcosystemRows()
  } catch (err) {
    tbody.innerHTML = '<tr><td colspan="5" style="color:#ff6b6b;">Could not load ecosystem links.</td></tr>'
    console.error('[token-dashboard] failed to load ecosystem links', err)
  }
}

async function toggleEcosystemActive(id, isActive) {
  try {
    const res = await fetch(`${XERA_ADMIN_BASE}/ecosystem/${id}`, {
      method: 'PUT',
      headers: xeraAdminHeaders(),
      body: JSON.stringify({ is_active: isActive }),
    })
    if (res.status === 401 || res.status === 403) return redirectToLogin()
    if (!res.ok) throw new Error(`status ${res.status}`)
    const link = ecosystemLinks.find((l) => l.id === id)
    if (link) link.is_active = isActive
  } catch (err) {
    console.error('[token-dashboard] failed to update link', err)
    await loadEcosystemLinks() // resync the checkbox state on failure
  }
}

async function deleteEcosystemLink(id) {
  if (!confirm('Remove this ecosystem link?')) return
  try {
    const res = await fetch(`${XERA_ADMIN_BASE}/ecosystem/${id}`, { method: 'DELETE', headers: authHeaders() })
    if (res.status === 401 || res.status === 403) return redirectToLogin()
    if (!res.ok) throw new Error(`status ${res.status}`)
    ecosystemLinks = ecosystemLinks.filter((l) => l.id !== id)
    renderEcosystemRows()
  } catch (err) {
    console.error('[token-dashboard] failed to delete link', err)
  }
}

document.getElementById('eco-add').addEventListener('click', async () => {
  const msgEl = document.getElementById('eco-msg')
  msgEl.textContent = ''
  msgEl.className = 'td-msg'

  const name = document.getElementById('eco-name').value.trim()
  const url = document.getElementById('eco-url').value.trim()
  const imageUrl = document.getElementById('eco-image').value.trim()

  if (!name || !url || !imageUrl) {
    msgEl.textContent = 'Fill in name, URL, and logo image URL.'
    msgEl.className = 'td-msg error'
    return
  }

  try {
    const res = await fetch(`${XERA_ADMIN_BASE}/ecosystem`, {
      method: 'POST',
      headers: xeraAdminHeaders(),
      body: JSON.stringify({ name, url, image_url: imageUrl, sort_order: ecosystemLinks.length, is_active: true }),
    })
    if (res.status === 401 || res.status === 403) return redirectToLogin()
    const data = await res.json().catch(() => ({}))
    if (!res.ok) throw new Error(data.detail || `status ${res.status}`)
    document.getElementById('eco-name').value = ''
    document.getElementById('eco-url').value = ''
    document.getElementById('eco-image').value = ''
    msgEl.textContent = 'Added.'
    msgEl.className = 'td-msg ok'
    await loadEcosystemLinks()
  } catch (err) {
    msgEl.textContent = err.message || 'Could not add this link.'
    msgEl.className = 'td-msg error'
  }
})

async function openTokenDashboard() {
  tabRequestsBtn.classList.remove('active')
  tabTokenBtn.classList.add('active')
  panelRequests.hidden = true
  panelToken.hidden = false

  if (!tokenDashboardLoaded) {
    tokenDashboardLoaded = true
    await Promise.all([loadTokenStats(), loadDailyConfig(), loadEcosystemLinks()])
  }
}

function openRequestsTab() {
  tabTokenBtn.classList.remove('active')
  tabRequestsBtn.classList.add('active')
  panelToken.hidden = true
  panelRequests.hidden = false
}

tabTokenBtn.addEventListener('click', openTokenDashboard)
tabRequestsBtn.addEventListener('click', openRequestsTab)

// --- Boot -----------------------------------------------------------------------
;(async function init() {
  const user = await guard()
  if (!user) return
  await loadRequests()
  startRequestsPolling()
})()
