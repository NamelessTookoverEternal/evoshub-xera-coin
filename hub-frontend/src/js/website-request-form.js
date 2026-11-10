// EVOSHUB — Website Creation: intake form -> pay now / talk first -> receipt + live chat
//
// Flow: visitor fills the form and attaches files -> we ensure an anonymous Supabase
// session -> the backend saves the request and the files -> the visitor either pays
// (Paystack or USDT crypto, optional XERA saving) or talks to our team first.
// After payment they get a receipt and a follow-up button that opens the chat.
//
// All prices and every payment decision come from the backend. This file only
// displays what it is told and sends "this request, this method, use XERA yes/no".
import { supabase, ensureVisitorSession } from './supabase-client.js'
import { detectCountry } from './evoxera-geo.js'

const LOCAL_STORAGE_KEY = 'evoshub_website_request_id'
const FOLLOWUP_KEY = 'evoshub_website_followup_sent'
const XERA_TOKEN_KEY = 'xera_evos_token'
const MIN_FORM_TIME_MS = 2500 // real humans take at least this long to fill the form
const MAX_FILES = 8
const MAX_FILE_BYTES = 5 * 1024 * 1024
const ALLOWED_TYPES = ['image/png', 'image/jpeg', 'image/webp', 'image/gif', 'application/pdf']

const API_BASE = import.meta.env.VITE_API_BASE_URL ||
  ((location.hostname === 'localhost' || location.hostname === '127.0.0.1')
    ? 'http://localhost:8000'
    : 'https://api.evoshub.xyz') // same fallback pattern as xera.js/xera-chain.js — see .env.example

const $ = (id) => document.getElementById(id)
const form        = $('website-request-form')
const errorEl     = $('wr-error')
const submitBtn   = $('wr-submit')
const pkgCards    = document.querySelectorAll('.pkg-card')
const pkgSelect   = $('wr-package')
const fileInput   = $('wr-files')
const fileListEl  = $('wr-file-list')
const choosePanel = $('wr-choose-panel')
const pendingPanel = $('wr-pending-panel')
const receiptPanel = $('wr-receipt-panel')
const chatPanel   = $('wr-chat-panel')
const chatLog     = $('wr-chat-log')
const chatForm    = $('wr-chat-form')
const chatInput   = $('wr-chat-input')
const chatError   = $('wr-chat-error')

const formLoadedAt = Date.now()
let activeRequestId = null
let payState = null      // last GET /payment response
let displayFx = { currency: 'GHS', rate: 1, converted: false }
let pollTimer = null
let receiptData = null

// --- Small helpers ---------------------------------------------------------------------
const ghs = (n) => 'GH₵' + Number(n).toLocaleString('en-GH', { minimumFractionDigits: Number.isInteger(Number(n)) ? 0 : 2, maximumFractionDigits: 2 })

function approx(amountGhs) {
  if (!displayFx.converted) return ''
  try {
    const v = Number(amountGhs) * displayFx.rate
    return '≈ ' + new Intl.NumberFormat(undefined, { style: 'currency', currency: displayFx.currency, maximumFractionDigits: 2 }).format(v)
  } catch { return '' }
}

function show(panel) {
  ;[choosePanel, pendingPanel, receiptPanel, chatPanel].forEach((p) => { p.style.display = p === panel ? 'block' : 'none' })
  form.closest('.card').style.display = 'none'
  panel.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function showErr(el, msg) { el.textContent = msg; el.style.display = 'block' }
function hideErr(el) { el.style.display = 'none'; el.textContent = '' }
function showError(msg) { showErr(errorEl, msg) }
function clearError() { hideErr(errorEl) }

async function authHeaders(extra = {}) {
  const session = await ensureVisitorSession()
  const h = { Authorization: `Bearer ${session.access_token}`, ...extra }
  let xera = ''
  try { xera = localStorage.getItem(XERA_TOKEN_KEY) || '' } catch { /* storage blocked */ }
  if (xera) h['X-Xera-Authorization'] = `Bearer ${xera}`
  return h
}

async function api(path, { method = 'GET', body, formData } = {}) {
  const headers = await authHeaders(body ? { 'Content-Type': 'application/json' } : {})
  let res
  try {
    res = await fetch(`${API_BASE}/api/website-requests${path}`, {
      method,
      headers,
      body: formData || (body ? JSON.stringify(body) : undefined),
    })
  } catch (netErr) {
    // "Failed to fetch": the server could not be reached at all (offline, server asleep or down,
    // or this page's address is not allowed by the server's CORS list).
    console.error('[website-request-form] cannot reach', API_BASE, netErr)
    const err = new Error("We couldn't reach our server. Please check your internet connection and try again in a minute. If it keeps happening, message us on WhatsApp.")
    err.status = 0
    err.network = true
    throw err
  }
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    const err = new Error(typeof data.detail === 'string' ? data.detail : `request_failed_${res.status}`)
    err.status = res.status
    throw err
  }
  return data
}

// --- Price cards (prices come from the backend; the HTML holds the same defaults) --------
function renderCards(packages) {
  Object.values(packages || {}).forEach((p) => {
    if (!p) return
    const was = document.querySelector(`[data-was="${p.package}"]`)
    const now = document.querySelector(`[data-now="${p.package}"]`)
    const badges = document.querySelector(`[data-badges="${p.package}"]`)
    const ap = document.querySelector(`[data-approx="${p.package}"]`)
    if (now) now.textContent = ghs(p.price)
    if (was) {
      was.hidden = !(p.percent_off > 0)
      was.textContent = ghs(p.list_price)
    }
    if (badges) {
      badges.textContent = ''
      if (p.percent_off > 0) {
        const off = document.createElement('span'); off.className = 'pkg-off'; off.textContent = `${p.percent_off}% off`
        badges.appendChild(off)
      }
      if (p.xera_percent > 0) {
        const x = document.createElement('span'); x.className = 'pkg-xera'
        x.textContent = `Extra ${p.xera_percent}% off when you pay with XERA`
        badges.appendChild(x)
      }
    }
    if (ap) ap.textContent = approx(p.price)
  })
}

async function loadPricingAndCurrency() {
  try {
    const country = await detectCountry()
    const [pr, fx] = await Promise.all([
      fetch(`${API_BASE}/api/website-requests/pricing`).then((r) => (r.ok ? r.json() : null)),
      fetch(`${API_BASE}/api/evosgpt/currency${country ? '?country=' + country : ''}`).then((r) => (r.ok ? r.json() : null)).catch(() => null),
    ])
    if (fx && fx.currency) displayFx = fx
    if (pr && pr.packages) renderCards(pr.packages)
  } catch (err) {
    console.warn('[website-request-form] pricing refresh failed, showing built-in prices', err)
  }
}
loadPricingAndCurrency()

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

// --- File picking (client-side limits are a convenience; the server enforces them) ----------
let pickedFiles = []
function renderPickedFiles(results = null) {
  fileListEl.textContent = ''
  pickedFiles.forEach((f, i) => {
    const li = document.createElement('li')
    const name = document.createElement('span'); name.textContent = f.name
    const state = document.createElement('span')
    const r = results && results[i]
    if (r && r.error) { state.className = 'bad'; state.textContent = r.error }
    else if (r && r.ok) state.textContent = 'Uploaded'
    else state.textContent = `${(f.size / 1024 / 1024).toFixed(1)} MB`
    li.append(name, state)
    fileListEl.appendChild(li)
  })
}
fileInput.addEventListener('change', () => {
  clearError()
  const all = Array.from(fileInput.files || [])
  const problems = []
  const ok = all.filter((f) => {
    if (!ALLOWED_TYPES.includes(f.type)) { problems.push(`${f.name}: only images and PDFs are accepted`); return false }
    if (f.size > MAX_FILE_BYTES) { problems.push(`${f.name}: larger than 5 MB`); return false }
    return true
  })
  if (ok.length > MAX_FILES) problems.push(`Only the first ${MAX_FILES} files will be sent`)
  pickedFiles = ok.slice(0, MAX_FILES)
  renderPickedFiles()
  if (problems.length) showError(problems.join('. ') + '.')
})

async function uploadFiles(requestId) {
  const results = []
  for (const f of pickedFiles) {
    const fd = new FormData()
    fd.append('file', f, f.name)
    try {
      await api(`/${requestId}/files`, { method: 'POST', formData: fd })
      results.push({ ok: true })
    } catch (err) {
      results.push({ error: err.message || 'failed' })
    }
    renderPickedFiles(results)
  }
  return results
}

// --- Form submit --------------------------------------------------------------------
form.addEventListener('submit', async (e) => {
  e.preventDefault()
  clearError()

  // Honeypot: bots fill every field, humans never see this one.
  const honeypot = form.querySelector('#wr-website').value
  if (honeypot) return // silently "succeed" so the bot learns nothing, but do nothing

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
    // Submitted through the FastAPI backend rather than a direct client insert: the backend
    // re-verifies this session's token with Supabase Auth, re-sanitizes every field, and
    // applies a per-IP rate limit. DB-level RLS still applies underneath as a second line.
    const body = await api('', {
      method: 'POST',
      body: {
        full_name:     data.full_name.trim(),
        email:         data.email.trim(),
        phone:         data.phone?.trim() || null,
        business_name: data.business_name?.trim() || null,
        package:       data.package,
        budget_range:  data.budget_range?.trim() || null,
        timeline:      data.timeline?.trim() || null,
        project_brief: data.project_brief.trim(),
        website:       honeypot || null,
      },
    })
    try { localStorage.setItem(LOCAL_STORAGE_KEY, body.request_id) } catch { /* storage blocked */ }
    activeRequestId = body.request_id

    if (pickedFiles.length) {
      submitBtn.textContent = 'Uploading files…'
      const results = await uploadFiles(body.request_id)
      if (results.some((r) => r.error)) {
        // The request itself is saved; tell them which files missed and carry on.
        console.warn('[website-request-form] some uploads failed', results)
      }
    }
    await enterNextStep(body.request_id, body.pricing)
  } catch (err) {
    console.error('[website-request-form] submit failed', err)
    const msg = String(err.message || '')
    if (msg.includes('rate limit') || err.status === 429) {
      showError("You've submitted a few requests already — please wait a bit before sending another.")
    } else if (err.network) {
      showError(msg)
    } else {
      showError('Something went wrong submitting your request. Please try again.')
    }
    submitBtn.disabled = false
    submitBtn.textContent = 'Continue'
  }
})

// --- Step 2: pay now / talk first ----------------------------------------------------------
async function enterNextStep(requestId, pricing) {
  activeRequestId = requestId
  if (!pricing) { // "Let's talk" package: quote only, straight to the team
    await startChat(requestId, { payable: false })
    return
  }
  await showChoose(requestId)
}

async function showChoose(requestId) {
  try {
    payState = await api(`/${requestId}/payment`)
  } catch (err) {
    console.error('[website-request-form] payment state failed', err)
    await startChat(requestId, { payable: false })
    return
  }
  routeByStatus()
}

function routeByStatus() {
  if (payState.status === 'paid') return showPaid()
  if (payState.status === 'pending') return showPending()
  renderChoose()
  show(choosePanel)
}

function row(label, value, cls = '') {
  const r = document.createElement('div'); r.className = `pay-row ${cls}`
  const a = document.createElement('span'); a.textContent = label
  const b = document.createElement('span')
  if (typeof value === 'string') b.textContent = value
  else b.appendChild(value)
  r.append(a, b)
  return r
}

function currentTotals() {
  const p = payState.pricing
  const useX = $('wr-use-xera').checked && payState.xera && payState.xera.eligible
  const discount = useX ? Number(payState.xera.discount_ghs) : 0
  return { p, useX, discount, total: Math.round((p.price - discount) * 100) / 100 }
}

function renderChoose() {
  const p = payState.pricing
  const x = payState.xera
  const wrap = $('wr-pay-summary')
  wrap.textContent = ''

  const xeraRow = $('wr-xera-row')
  const xeraNote = $('wr-xera-note')
  xeraRow.style.display = 'none'
  xeraNote.style.display = 'none'
  if (x && x.enabled) {
    if (x.eligible) {
      xeraRow.style.display = 'flex'
      $('wr-xera-text').textContent =
        `Pay with XERA and save an extra ${p.xera_percent}% (${ghs(x.discount_ghs)}). Uses ${Number(x.xera_amount).toLocaleString()} XERA from your wallet.`
    } else if (x.reason === 'not_signed_in') {
      xeraNote.style.display = 'block'
      xeraNote.textContent = ''
      const a = document.createElement('a'); a.href = '/xera'; a.textContent = 'Sign in to XERA'
      xeraNote.append(a, ` to save an extra ${p.xera_percent}% (${ghs(p.xera_saving)}).`)
    } else if (x.message) {
      xeraNote.style.display = 'block'
      xeraNote.textContent = x.message
    }
  }

  const draw = () => {
    wrap.textContent = ''
    const t = currentTotals()
    wrap.appendChild(row(p.label, ghs(p.price)))
    if (p.percent_off > 0) {
      const was = document.createElement('span'); was.className = 'was'; was.textContent = ghs(p.list_price)
      wrap.appendChild(row(`Regular price (${p.percent_off}% off applied)`, was))
    }
    if (t.useX) wrap.appendChild(row('XERA saving', '−' + ghs(t.discount)))
    const total = document.createElement('span')
    total.textContent = ghs(t.total)
    const hint = approx(t.total)
    if (hint) { const s = document.createElement('small'); s.style.cssText = 'font-weight:500;color:var(--text3);margin-left:8px;'; s.textContent = hint; total.appendChild(s) }
    wrap.appendChild(row('Total today', total, 'pay-row--total'))
  }
  draw()
  $('wr-use-xera').onchange = draw

  $('wr-pay-paystack').style.display = payState.methods.paystack ? '' : 'none'
  $('wr-pay-crypto').style.display = payState.methods.crypto ? '' : 'none'
  hideErr($('wr-pay-error'))
}

async function pay(method) {
  const btns = [$('wr-pay-paystack'), $('wr-pay-crypto'), $('wr-talk-first')]
  btns.forEach((b) => { b.disabled = true })
  hideErr($('wr-pay-error'))
  try {
    const useXera = $('wr-use-xera').checked && payState.xera && payState.xera.eligible
    const res = await api(`/${activeRequestId}/pay`, { method: 'POST', body: { method, use_xera: !!useXera } })
    window.location.assign(res.url) // provider's hosted checkout; it returns to this page afterwards
  } catch (err) {
    console.error('[website-request-form] pay failed', err)
    showErr($('wr-pay-error'), err.message && err.message.length < 200 ? err.message : 'Could not start the payment. Please try again.')
    btns.forEach((b) => { b.disabled = false })
    if (err.status === 409 || err.status === 401) { try { await showChoose(activeRequestId) } catch { /* keep current view */ } }
  }
}
$('wr-pay-paystack').addEventListener('click', () => pay('paystack'))
$('wr-pay-crypto').addEventListener('click', () => pay('crypto'))
$('wr-talk-first').addEventListener('click', async () => {
  try { await api(`/${activeRequestId}/talk-first`, { method: 'POST' }) } catch (err) { console.warn('[website-request-form] talk-first not recorded', err) }
  await startChat(activeRequestId, { payable: true })
})

// --- Waiting for confirmation ----------------------------------------------------------------
function showPending() {
  show(pendingPanel)
  $('wr-pending-text').textContent = payState.payment_method === 'crypto'
    ? 'Waiting for your USDT payment to confirm on the network. This can take a few minutes. You can leave this page open.'
    : 'This usually takes a few seconds.'
  clearInterval(pollTimer)
  let tries = 0
  pollTimer = setInterval(async () => {
    tries += 1
    try {
      payState = await api(`/${activeRequestId}/payment`)
      if (payState.status !== 'pending') { clearInterval(pollTimer); routeByStatus() }
    } catch (err) { console.warn('[website-request-form] poll failed', err) }
    if (tries > 120) clearInterval(pollTimer) // ~10 minutes; they can come back, we resume on reload
  }, 5000)
}
$('wr-pending-back').addEventListener('click', async () => {
  clearInterval(pollTimer)
  // Starting another payment replaces the pending attempt on the server.
  payState.status = 'unpaid'
  renderChoose(); show(choosePanel)
})
$('wr-pending-chat').addEventListener('click', () => startChat(activeRequestId, { payable: true }))

// --- Paid: receipt + follow-up ---------------------------------------------------------------
async function showPaid() {
  clearInterval(pollTimer)
  try {
    receiptData = (await api(`/${activeRequestId}/receipt`)).receipt
  } catch (err) {
    console.error('[website-request-form] receipt failed', err)
    receiptData = null
  }
  const r = receiptData
  $('wr-receipt-no').textContent = r ? r.receipt_no : (payState.receipt_no || '')
  $('wr-receipt-date').textContent = r && r.paid_at ? new Date(r.paid_at).toLocaleString() : ''
  const rows = $('wr-receipt-rows')
  rows.textContent = ''
  if (r) {
    const add = (k, v) => { const tr = document.createElement('tr'); const a = document.createElement('td'); a.textContent = k; const b = document.createElement('td'); b.textContent = v; tr.append(a, b); rows.appendChild(tr) }
    add('Customer', r.customer.name + (r.customer.business ? ` (${r.customer.business})` : ''))
    add('Item', r.item)
    if (r.package_discount > 0) add('Regular price', ghs(r.list_price))
    add('Package price', ghs(r.price))
    if (r.xera_discount > 0) add('XERA saving', '−' + ghs(r.xera_discount))
    add('Total paid', ghs(r.amount_paid) + (r.crypto_usd ? `  (≈ $${r.crypto_usd.toFixed(2)} USDT)` : ''))
    add('Payment method', r.method)
    add('Reference', r.reference)
  }
  show(receiptPanel)
}
$('wr-print').addEventListener('click', () => window.print())
$('wr-followup').addEventListener('click', async () => {
  await startChat(activeRequestId, { payable: false, paid: true })
  // Tell customer service once per receipt, so repeat clicks just reopen the chat.
  const no = receiptData ? receiptData.receipt_no : payState.receipt_no
  let already = ''
  try { already = localStorage.getItem(FOLLOWUP_KEY) || '' } catch { /* storage blocked */ }
  if (no && already !== no) {
    await sendChatMessage(`Hi, I'm following up on my paid order (receipt ${no}).`)
    try { localStorage.setItem(FOLLOWUP_KEY, no) } catch { /* storage blocked */ }
  }
})

// --- Chat panel ----------------------------------------------------------------------
function renderMessage(msg) {
  const team = msg.sender_role === 'admin'
  const rowEl = document.createElement('div')
  rowEl.className = 'wr-msg ' + (team ? 'wr-msg--team' : 'wr-msg--me')

  const who = document.createElement('div')
  who.className = 'wr-who'
  who.textContent = team ? 'Customer service' : 'You'

  const bubble = document.createElement('div')
  bubble.className = 'wr-bubble'
  // Always render via textContent, never innerHTML with raw user text.
  bubble.textContent = msg.body

  rowEl.append(who, bubble)
  if (msg.created_at) {
    const d = new Date(msg.created_at)
    if (!Number.isNaN(d.getTime())) {
      const t = document.createElement('div')
      t.className = 'wr-time'
      t.textContent = d.toLocaleString([], { hour: '2-digit', minute: '2-digit', day: 'numeric', month: 'short' })
      rowEl.appendChild(t)
    }
  }
  chatLog.appendChild(rowEl)
  chatLog.scrollTop = chatLog.scrollHeight
}

let seenMsgIds = new Set()
let chatPoll = null

const chatFetch = (method = 'GET', body) => api(`/${activeRequestId}/messages`, { method, body })

function addNewMessages(list) {
  list.forEach((m) => { if (!seenMsgIds.has(m.id)) { seenMsgIds.add(m.id); renderMessage(m) } })
}

async function loadMessages(requestId, { silent = false } = {}) {
  if (requestId !== activeRequestId) return
  try {
    const { messages } = await chatFetch()
    chatError.style.display = 'none'
    addNewMessages(messages || [])
  } catch (err) {
    console.error('[website-chat] load failed', err)
    if (!silent) {
      chatError.textContent = "We couldn't load your messages. Please refresh the page. Your messages are safe."
      chatError.style.display = 'block'
    }
  }
}

async function startChat(requestId, { payable = false, paid = false } = {}) {
  activeRequestId = requestId
  clearInterval(pollTimer)
  clearInterval(chatPoll)
  seenMsgIds = new Set()
  chatLog.innerHTML = ''
  show(chatPanel)
  $('wr-chat-intro').textContent = paid
    ? 'Thanks for your payment. Tell us anything else we should know, or ask us a question. We usually reply within 3 to 5 hours.'
    : "We've received your request. We usually reply within 3 to 5 hours. Feel free to add more details below."
  $('wr-chat-paybar').style.display = payable ? 'block' : 'none'
  await loadMessages(requestId)
  chatPoll = setInterval(() => loadMessages(requestId, { silent: true }), 4000)
}
$('wr-chat-paynow').addEventListener('click', () => showChoose(activeRequestId))

async function sendChatMessage(body) {
  const { message } = await chatFetch('POST', { body })
  if (message) addNewMessages([message])
}

chatForm.addEventListener('submit', async (e) => {
  e.preventDefault()
  chatError.style.display = 'none'
  const body = chatInput.value.trim()
  if (!body || !activeRequestId) return

  const sendBtn = $('wr-chat-send')
  sendBtn.disabled = true
  try {
    await sendChatMessage(body)
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

// --- Resume an existing request on page load / after returning from the payment page ----------
;(async function resumeIfExisting() {
  let savedId = null
  try { savedId = localStorage.getItem(LOCAL_STORAGE_KEY) } catch { /* storage blocked */ }
  if (!savedId) return

  try {
    await ensureVisitorSession()
    // RLS guarantees this only returns something if it's still this visitor's own row — a
    // stale/foreign id in localStorage just returns nothing and we show the empty form.
    const { data, error } = await supabase
      .from('website_requests')
      .select('id, package, contact_path, payment_status')
      .eq('id', savedId)
      .maybeSingle()

    if (error || !data) {
      try { localStorage.removeItem(LOCAL_STORAGE_KEY) } catch { /* ignore */ }
      return
    }
    activeRequestId = data.id
    if (data.package === 'custom') return startChat(data.id, { payable: false })

    const returnedFromPayment = new URLSearchParams(location.search).has('pay')
    if (data.contact_path === 'talk' && data.payment_status === 'unpaid' && !returnedFromPayment) {
      return startChat(data.id, { payable: true })
    }
    await showChoose(data.id) // routes to choose / pending / receipt by the live payment status
  } catch (err) {
    console.error('[website-request-form] resume failed', err)
  }
})()
