// Admin "Product switches" screen. Same admin session as the rest of the console. The BACKEND decides who may
// flip a switch (token + live admin_agents row on every call); this page only renders what it returns.
// All server text is set with textContent.
import { API_BASE, authHeaders, signedOut } from './admin-console-session.js'

const $ = (id) => document.getElementById(id)
const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n }

function showError(msg) { const b = $('ps-error'); b.textContent = msg || ''; b.hidden = !msg }

async function call(path, opts = {}) {
  const res = await fetch(`${API_BASE}/api/admin/products${path}`, {
    ...opts,
    headers: { ...authHeaders(), ...(opts.body ? { 'Content-Type': 'application/json' } : {}) },
  })
  if (res.status === 401 || res.status === 403) { signedOut(); throw new Error('SIGNED_OUT') }
  const data = await res.json().catch(() => ({}))
  if (!res.ok) { const e = new Error(typeof data.detail === 'string' ? data.detail : `Request failed (${res.status})`); e.status = res.status; throw e }
  return data
}

function when(iso) { try { return iso ? new Date(iso).toLocaleString('en-GH') : '' } catch { return '' } }

async function patch(key, body) {
  showError('')
  try { await call(`/${encodeURIComponent(key)}`, { method: 'PATCH', body: JSON.stringify(body) }) }
  catch (e) {
    if (e.status === 409 && window.confirm(`${e.message}\n\nSwitch it off anyway?`)) {
      try { await call(`/${encodeURIComponent(key)}`, { method: 'PATCH', body: JSON.stringify({ ...body, confirm: true }) }) } catch (e2) { if (e2.message !== 'SIGNED_OUT') showError(e2.message) }
    } else if (e.message !== 'SIGNED_OUT' && e.status !== 409) showError(e.message)
  }
  await initProducts()
}

function card(p) {
  const c = el('div', 'dx-card dx-panel')
  const head = el('div', 'dx-panel-head')
  head.append(el('h2', 'dx-panel-title', p.label), el('span', 'dx-note', p.enabled ? 'On' : 'Off — tile is greyed out'))
  c.append(head)

  const rowOn = el('div', 'dx-row')
  const lblOn = el('label', '', 'Switched on'); lblOn.htmlFor = `ps-on-${p.key}`
  const on = el('input'); on.type = 'checkbox'; on.id = `ps-on-${p.key}`; on.checked = p.enabled
  on.addEventListener('change', () => { on.disabled = true; patch(p.key, { enabled: on.checked }) })
  rowOn.append(lblOn, on)
  c.append(rowOn)

  const rowEnf = el('div', 'dx-row')
  const lblEnf = el('label', '', 'Block new activity while off'); lblEnf.htmlFor = `ps-enf-${p.key}`
  const enf = el('input'); enf.type = 'checkbox'; enf.id = `ps-enf-${p.key}`; enf.checked = p.enforce
  enf.addEventListener('change', () => { enf.disabled = true; patch(p.key, { enforce: enf.checked }) })
  rowEnf.append(lblEnf, enf)
  c.append(rowEnf)

  const rowMsg = el('div', 'dx-row')
  const lblMsg = el('label', '', 'Message when tapped'); lblMsg.htmlFor = `ps-msg-${p.key}`
  const msg = el('input', 'dx-input'); msg.id = `ps-msg-${p.key}`; msg.maxLength = 200; msg.value = p.message || ''
  msg.placeholder = `${p.label} is switched off for now. Please check back soon.`
  rowMsg.append(lblMsg, msg)
  c.append(rowMsg)

  const save = el('button', 'dx-btn sm ghost', 'Save message'); save.type = 'button'; save.style.marginTop = '10px'
  save.addEventListener('click', () => { save.disabled = true; patch(p.key, { message: msg.value }) })
  c.append(save)

  if (p.updated_at) c.append(el('p', 'dx-note', `Last changed ${when(p.updated_at)}${p.updated_by ? ` by admin #${p.updated_by}` : ''}`))
  return c
}

export async function initProducts() {
  const list = $('ps-list')
  try {
    const { products } = await call('')
    list.textContent = ''
    products.forEach((p) => list.append(card(p)))
    showError('')
  } catch (e) {
    if (e.message !== 'SIGNED_OUT') showError(e.message || 'Could not load the switches.')
  }
}
