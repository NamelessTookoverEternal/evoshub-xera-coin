// EVOSHUB — Website Creation: intake form + live chat
//
// Flow: visitor fills the form -> we ensure an anonymous Supabase session ->
// insert one row in website_requests (RLS stamps it as theirs) -> switch to
// the chat panel, which reads/writes website_chat_messages over Realtime,
// scoped to that request by RLS (see 20260709_website_creation.sql).
import { supabase, ensureVisitorSession } from './supabase-client.js'

const LOCAL_STORAGE_KEY = 'evoshub_website_request_id'
const MIN_FORM_TIME_MS = 2500 // real humans take at least this long to fill the form

const form        = document.getElementById('website-request-form')
const errorEl     = document.getElementById('wr-error')
const submitBtn   = document.getElementById('wr-submit')
const pkgCards    = document.querySelectorAll('.pkg-card')
const pkgSelect   = document.getElementById('wr-package')
const chatPanel   = document.getElementById('wr-chat-panel')
const chatLog     = document.getElementById('wr-chat-log')
const chatForm    = document.getElementById('wr-chat-form')
const chatInput   = document.getElementById('wr-chat-input')
const chatError   = document.getElementById('wr-chat-error')

const formLoadedAt = Date.now()
let activeRequestId = null
let realtimeChannel = null

// --- Package card <-> select sync -------------------------------------------------
pkgCards.forEach((card) => {
  card.addEventListener('click', () => {
    pkgCards.forEach((c) => c.classList.remove('selected'))
    card.classList.add('selected')
    pkgSelect.value = card.dataset.package
  })
})
pkgSelect.addEventListener('change', () => {
  pkgCards.forEach((c) => c.classList.toggle('selected', c.dataset.package === pkgSelect.value))
})

// --- Form submit --------------------------------------------------------------------
function showError(msg) {
  errorEl.textContent = msg
  errorEl.style.display = 'block'
}
function clearError() {
  errorEl.style.display = 'none'
  errorEl.textContent = ''
}

form.addEventListener('submit', async (e) => {
  e.preventDefault()
  clearError()

  // Honeypot: bots fill every field, humans never see this one.
  const honeypot = form.querySelector('#wr-website').value
  if (honeypot) {
    // Silently "succeed" so the bot doesn't learn anything, but do nothing.
    return
  }

  // Basic bot-speed check — a real person needs at least a couple seconds.
  if (Date.now() - formLoadedAt < MIN_FORM_TIME_MS) {
    showError('Please take a moment to review your details before submitting.')
    return
  }

  const data = Object.fromEntries(new FormData(form).entries())
  if (!data.package) return showError('Please choose a package.')
  if (!data.full_name?.trim()) return showError('Please enter your name.')
  if (!data.email?.trim()) return showError('Please enter your email.')
  if (!data.project_brief?.trim()) return showError('Please tell us about your project.')

  submitBtn.disabled = true
  submitBtn.textContent = 'Submitting…'

  try {
    const session = await ensureVisitorSession()

    // Submitted through the FastAPI backend rather than a direct client
    // insert: the backend independently re-verifies this session's access
    // token against Supabase's own Auth server (never trusts a client-sent
    // id), re-sanitizes every field server-side, and applies a per-IP rate
    // limit — a layer a purely client-side insert can't provide, since a
    // bot can always mint a fresh anonymous session to dodge a per-visitor
    // limit. The DB-level RLS policies and triggers still apply underneath
    // this as a second, independent line of defense.
    const apiBase = import.meta.env.VITE_API_BASE_URL
    const res = await fetch(`${apiBase}/api/website-requests`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${session.access_token}`,
      },
      body: JSON.stringify({
        full_name:     data.full_name.trim(),
        email:         data.email.trim(),
        phone:         data.phone?.trim() || null,
        business_name: data.business_name?.trim() || null,
        package:       data.package,
        budget_range:  data.budget_range?.trim() || null,
        timeline:      data.timeline?.trim() || null,
        project_brief: data.project_brief.trim(),
        website:       honeypot || null,
      }),
    })

    const body = await res.json().catch(() => ({}))
    if (!res.ok) throw new Error(body.detail || `request_failed_${res.status}`)

    localStorage.setItem(LOCAL_STORAGE_KEY, body.request_id)
    startChat(body.request_id)
  } catch (err) {
    console.error('[website-request-form] submit failed', err)
    const msg = String(err.message || '')
    if (msg.includes('rate limit') || msg.includes('429')) {
      showError("You've submitted a few requests already — please wait a bit before sending another.")
    } else {
      showError('Something went wrong submitting your request. Please try again.')
    }
    submitBtn.disabled = false
    submitBtn.textContent = 'Submit & start chat'
  }
})

// --- Chat panel ----------------------------------------------------------------------
function renderMessage(msg) {
  const row = document.createElement('div')
  row.style.cssText = 'display:flex; flex-direction:column; align-items:' +
    (msg.sender_role === 'admin' ? 'flex-start' : 'flex-end') + ';'

  const bubble = document.createElement('div')
  bubble.style.cssText = 'max-width:80%; padding:9px 13px; border-radius:12px; font-size:13.5px; line-height:1.5;' +
    (msg.sender_role === 'admin'
      ? 'background:var(--surface2); color:var(--text);'
      : 'background:var(--blue); color:#fff;')
  // Always render via textContent — never innerHTML with raw user text — so
  // even if server-side sanitization ever changed, the browser still can't
  // execute anything from a chat message.
  bubble.textContent = msg.body
  row.appendChild(bubble)
  chatLog.appendChild(row)
  chatLog.scrollTop = chatLog.scrollHeight
}

async function loadMessages(requestId) {
  const { data, error } = await supabase
    .from('website_chat_messages')
    .select('id, sender_role, body, created_at')
    .eq('request_id', requestId)
    .order('created_at', { ascending: true })

  if (error) {
    console.error('[website-chat] load failed', error)
    return
  }
  chatLog.innerHTML = ''
  data.forEach(renderMessage)
}

function subscribeToChat(requestId) {
  if (realtimeChannel) supabase.removeChannel(realtimeChannel)

  realtimeChannel = supabase
    .channel(`website_chat_${requestId}`)
    .on(
      'postgres_changes',
      {
        event: 'INSERT',
        schema: 'public',
        table: 'website_chat_messages',
        filter: `request_id=eq.${requestId}`,
      },
      (payload) => renderMessage(payload.new)
    )
    .subscribe()
}

async function startChat(requestId) {
  activeRequestId = requestId
  form.closest('.card').style.display = 'none'
  chatPanel.style.display = 'block'
  chatPanel.scrollIntoView({ behavior: 'smooth', block: 'start' })
  await loadMessages(requestId)
  subscribeToChat(requestId)
}

chatForm.addEventListener('submit', async (e) => {
  e.preventDefault()
  chatError.style.display = 'none'
  const body = chatInput.value.trim()
  if (!body || !activeRequestId) return

  const sendBtn = document.getElementById('wr-chat-send')
  sendBtn.disabled = true

  try {
    const { data: { session } } = await supabase.auth.getSession()
    const { error } = await supabase.from('website_chat_messages').insert({
      request_id:  activeRequestId,
      sender_id:   session.user.id,
      sender_role: 'visitor',
      body,
    })
    if (error) throw error
    chatInput.value = ''
  } catch (err) {
    console.error('[website-chat] send failed', err)
    chatError.textContent = String(err.message || '').includes('rate_limit_exceeded')
      ? "You're sending messages too fast — please slow down."
      : 'Message failed to send. Please try again.'
    chatError.style.display = 'block'
  } finally {
    sendBtn.disabled = false
  }
})

// --- Resume an existing session on page reload ----------------------------------------
;(async function resumeIfExisting() {
  const savedId = localStorage.getItem(LOCAL_STORAGE_KEY)
  if (!savedId) return

  try {
    await ensureVisitorSession()
    // RLS guarantees this only returns something if it's still this
    // visitor's own row — a stale/foreign id in localStorage just returns
    // nothing and we silently fall back to showing the empty form.
    const { data, error } = await supabase
      .from('website_requests')
      .select('id')
      .eq('id', savedId)
      .maybeSingle()

    if (!error && data) {
      startChat(data.id)
    } else {
      localStorage.removeItem(LOCAL_STORAGE_KEY)
    }
  } catch (err) {
    console.error('[website-request-form] resume failed', err)
  }
})()
