// Admin page: post, edit and delete app updates. Same admin session as the rest of the console
// (sessionStorage token from admin-login.js). The BACKEND decides who may post — it re-checks
// admin_agents.is_active on every call — this page only hides itself from people without a session.
import { fetchUpdates, renderPost, toast } from './updates-core.js'

const API_BASE = import.meta.env.VITE_API_BASE_URL ||
  ((location.hostname === 'localhost' || location.hostname === '127.0.0.1') ? 'http://localhost:8000' : 'https://api.evoshub.xyz')
const TOKEN_KEY = 'evoshub_admin_token'
const MAX_IMAGES = 4
const MAX_SIDE = 1600

const $ = (id) => document.getElementById(id)
const auth = () => ({ Authorization: `Bearer ${sessionStorage.getItem(TOKEN_KEY) || ''}` })
const toLogin = () => { window.location.href = '/admin-login.html' }

async function guard() {
  if (!sessionStorage.getItem(TOKEN_KEY)) return toLogin()
  try {
    const res = await fetch(`${API_BASE}/api/admin/me`, { headers: auth() })
    if (!res.ok) { sessionStorage.removeItem(TOKEN_KEY); return toLogin() }
    const d = await res.json()
    $('admin-whoami').textContent = d.user?.display_name || d.user?.username || d.user?.email || 'Agent'
  } catch (e) { /* offline blip: stay, the first request will tell */ }
}
$('admin-signout').addEventListener('click', () => { sessionStorage.removeItem(TOKEN_KEY); toLogin() })

function msg(text, kind) { const m = $('au-msg'); m.textContent = text || ''; m.className = 'au-msg ' + (kind || '') }

// ---------------------------------------------------------------- images: shrink in the browser (also drops EXIF/GPS)
let picked = []   // [{ blob, url }]

async function shrink(file) {
  if (!/^image\/(jpeg|png|webp)$/.test(file.type)) throw new Error('Only JPEG, PNG or WebP images.')
  let bmp
  try { bmp = await createImageBitmap(file, { imageOrientation: 'from-image' }) } catch (e) { return file }   // server re-validates anyway
  const k = Math.min(1, MAX_SIDE / Math.max(bmp.width, bmp.height))
  const w = Math.max(1, Math.round(bmp.width * k)), h = Math.max(1, Math.round(bmp.height * k))
  const c = document.createElement('canvas'); c.width = w; c.height = h
  const ctx = c.getContext('2d')
  const toBlob = (type, q) => new Promise((r) => c.toBlob(r, type, q))
  if (file.type === 'image/png') {                       // logos / flyers: keep transparency if it fits
    ctx.drawImage(bmp, 0, 0, w, h)
    const png = await toBlob('image/png')
    if (png && png.size <= 1.5 * 1024 * 1024) return png
    ctx.clearRect(0, 0, w, h)
  }
  ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, w, h)
  ctx.drawImage(bmp, 0, 0, w, h)
  return (await toBlob('image/jpeg', 0.85)) || file
}

function renderPicked() {
  const box = $('au-previews'); box.textContent = ''
  picked.forEach((p, i) => {
    const d = document.createElement('div'); d.className = 'au-prev'
    const im = document.createElement('img'); im.src = p.url; im.alt = `Image ${i + 1}`
    const x = document.createElement('button'); x.type = 'button'; x.textContent = '×'; x.setAttribute('aria-label', `Remove image ${i + 1}`)
    x.addEventListener('click', () => { URL.revokeObjectURL(p.url); picked.splice(i, 1); renderPicked() })
    d.append(im, x); box.appendChild(d)
  })
  $('au-count').textContent = `${picked.length} of ${MAX_IMAGES}`
  $('au-add').disabled = picked.length >= MAX_IMAGES
}

$('au-add').addEventListener('click', () => $('au-files').click())
$('au-files').addEventListener('change', async (e) => {
  msg('')
  const files = [...e.target.files]; e.target.value = ''
  if (picked.length + files.length > MAX_IMAGES) msg(`Only ${MAX_IMAGES} images per update. Extra ones were skipped.`, 'error')
  for (const f of files.slice(0, MAX_IMAGES - picked.length)) {
    try { const blob = await shrink(f); picked.push({ blob, url: URL.createObjectURL(blob) }) } catch (err) { msg(err.message || 'Could not read that image.', 'error') }
  }
  renderPicked()
})

$('au-body').addEventListener('input', () => { $('au-chars').textContent = `${$('au-body').value.length} / 4000` })

// ---------------------------------------------------------------- post
$('au-form').addEventListener('submit', async (e) => {
  e.preventDefault()
  const body = $('au-body').value.trim()
  if (!body && !picked.length) return msg('Write something or add an image.', 'error')
  const btn = $('au-send'); btn.disabled = true; btn.textContent = 'Posting…'; msg('')
  try {
    const fd = new FormData()
    fd.append('body', body)
    picked.forEach((p, i) => fd.append('images', p.blob, `image-${i + 1}.${p.blob.type === 'image/png' ? 'png' : 'jpg'}`))
    const res = await fetch(`${API_BASE}/api/admin/updates`, { method: 'POST', headers: auth(), body: fd })   // no Content-Type: the browser sets the multipart boundary
    if (res.status === 401 || res.status === 403) return toLogin()
    const j = await res.json().catch(() => ({}))
    if (!res.ok) return msg(j.detail || 'Could not post. Try again.', 'error')
    $('au-body').value = ''; $('au-chars').textContent = '0 / 4000'
    picked.forEach((p) => URL.revokeObjectURL(p.url)); picked = []; renderPicked()
    msg('Posted. It is live in the app now.', 'ok')
    listEl.prepend(withControls(j.update))
    listEl.querySelectorAll('.au-hint').forEach((n) => n.remove())
  } catch (err) { msg('Network problem. Check your connection and try again.', 'error') }
  finally { btn.disabled = false; btn.textContent = 'Post update' }
})

// ---------------------------------------------------------------- list + edit/delete
const listEl = $('au-list')
let oldest = null

function withControls(post) {
  const { el } = renderPost(post)
  const manage = document.createElement('div'); manage.className = 'au-manage'
  const edit = document.createElement('button'); edit.type = 'button'; edit.className = 'btn btn--ghost'; edit.textContent = 'Edit text'
  const del = document.createElement('button'); del.type = 'button'; del.className = 'btn btn--ghost'; del.textContent = 'Delete'
  manage.append(edit, del); el.appendChild(manage)

  edit.addEventListener('click', () => {
    if (el.querySelector('.au-edit')) return
    const wrap = document.createElement('div'); wrap.className = 'au-edit'
    const ta = document.createElement('textarea'); ta.className = 'form-input'; ta.rows = 4; ta.maxLength = 4000; ta.value = post.body || ''; ta.setAttribute('aria-label', 'Edit text')
    const row = document.createElement('div'); row.className = 'au-manage'
    const save = document.createElement('button'); save.type = 'button'; save.className = 'btn btn--primary'; save.textContent = 'Save'
    const cancel = document.createElement('button'); cancel.type = 'button'; cancel.className = 'btn btn--ghost'; cancel.textContent = 'Cancel'
    row.append(save, cancel); wrap.append(ta, row); manage.before(wrap); ta.focus()
    cancel.addEventListener('click', () => wrap.remove())
    save.addEventListener('click', async () => {
      save.disabled = true
      try {
        const res = await fetch(`${API_BASE}/api/admin/updates/${post.id}`, { method: 'PATCH', headers: { ...auth(), 'Content-Type': 'application/json' }, body: JSON.stringify({ body: ta.value }) })
        if (res.status === 401 || res.status === 403) return toLogin()
        const j = await res.json().catch(() => ({}))
        if (!res.ok) { toast(j.detail || 'Could not save'); return }
        el.replaceWith(withControls(j.update)); toast('Saved')
      } catch (err) { toast('Network problem') } finally { save.disabled = false }
    })
  })

  del.addEventListener('click', async () => {
    if (!confirm('Delete this update and its images for everyone? This cannot be undone.')) return
    del.disabled = true
    try {
      const res = await fetch(`${API_BASE}/api/admin/updates/${post.id}`, { method: 'DELETE', headers: auth() })
      if (res.status === 401 || res.status === 403) return toLogin()
      const j = await res.json().catch(() => ({}))
      if (!res.ok) { toast(j.detail || 'Could not delete'); del.disabled = false; return }
      el.remove(); toast('Deleted')
    } catch (err) { toast('Network problem'); del.disabled = false }
  })
  return el
}

async function load(first) {
  try {
    const { updates, hasMore } = await fetchUpdates({ limit: 15, before: first ? undefined : oldest })
    if (first) listEl.textContent = ''
    if (first && !updates.length) { const p = document.createElement('p'); p.className = 'au-hint'; p.textContent = 'Nothing published yet.'; listEl.appendChild(p) }
    updates.forEach((u) => listEl.appendChild(withControls(u)))
    if (updates.length) oldest = updates[updates.length - 1].id
    $('au-more').hidden = !hasMore
  } catch (e) { if (first) listEl.textContent = 'Could not load published updates.' }
}
$('au-more').addEventListener('click', () => load(false))

guard(); renderPicked(); load(true)
