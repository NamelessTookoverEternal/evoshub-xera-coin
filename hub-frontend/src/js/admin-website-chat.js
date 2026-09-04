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

// --- Boot -----------------------------------------------------------------------
;(async function init() {
  const user = await guard()
  if (!user) return
  await loadRequests()
  startRequestsPolling()
})()
