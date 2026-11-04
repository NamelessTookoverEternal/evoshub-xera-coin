// Shared by the app home card, the /updates page and the admin form.
// Everything admin-written is inserted with textContent / createTextNode — never innerHTML.
import { XERA_API } from './xera-public.js'

export const SEEN_KEY = 'evos_updates_seen'

export function getSeen() {
  try { return Number(localStorage.getItem(SEEN_KEY)) || 0 } catch (e) { return 0 }
}
export function setSeen(id) {
  try { if (id > getSeen()) localStorage.setItem(SEEN_KEY, String(id)) } catch (e) { /* private mode: badge just stays */ }
}

export async function fetchUpdates({ limit = 20, before } = {}) {
  const q = new URLSearchParams({ limit: String(limit) })
  if (before) q.set('before', String(before))
  const res = await fetch(`${XERA_API}/api/updates?${q}`)
  if (!res.ok) throw new Error('updates_' + res.status)
  const j = await res.json()
  return { updates: j.updates || [], hasMore: !!j.has_more }
}

export function ago(iso) {
  const t = new Date(iso).getTime()
  if (!Number.isFinite(t)) return ''
  const mins = Math.floor((Date.now() - t) / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  if (mins < 1440) return `${Math.floor(mins / 60)}h ago`
  if (mins < 10080) return `${Math.floor(mins / 1440)}d ago`
  return new Date(t).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
}

const URL_RE = /https?:\/\/[^\s<>"']+/g

// Plain text -> DOM nodes, turning http(s) links into safe anchors. Admin-only content.
export function linkify(text) {
  const frag = document.createDocumentFragment()
  let last = 0
  for (const m of String(text || '').matchAll(URL_RE)) {
    let url = m[0]
    const trail = (url.match(/[.,;:!?)\]]+$/) || [''])[0]
    if (trail) url = url.slice(0, -trail.length)
    if (m.index > last) frag.appendChild(document.createTextNode(text.slice(last, m.index)))
    try {
      const u = new URL(url)
      if (u.protocol !== 'https:' && u.protocol !== 'http:') throw new Error('scheme')
      const a = document.createElement('a')
      a.href = u.href
      a.target = '_blank'
      a.rel = 'noopener noreferrer nofollow'
      a.textContent = url
      frag.appendChild(a)
    } catch (e) {
      frag.appendChild(document.createTextNode(url))
    }
    if (trail) frag.appendChild(document.createTextNode(trail))
    last = m.index + m[0].length
  }
  if (last < text.length) frag.appendChild(document.createTextNode(text.slice(last)))
  return frag
}

export function shareUrl(id) {
  return `${location.origin}/updates#u-${id}`
}

export async function sharePost(post) {
  const url = shareUrl(post.id)
  const text = (post.body || 'Update from Evoxera').slice(0, 160)
  if (navigator.share) {
    try { await navigator.share({ title: 'Evoxera update', text, url }); return 'shared' } catch (e) { if (e && e.name === 'AbortError') return 'cancelled' }
  }
  try { await navigator.clipboard.writeText(url); return 'copied' } catch (e) { return 'failed' }
}

// ---------------------------------------------------------------- toast
export function toast(msg) {
  document.querySelectorAll('.up-toast').forEach((n) => n.remove())
  const t = document.createElement('div')
  t.className = 'up-toast'
  t.setAttribute('role', 'status')
  t.textContent = msg
  document.body.appendChild(t)
  setTimeout(() => t.remove(), 2200)
}

// ---------------------------------------------------------------- icons (static strings, no user data)
const ICON = {
  shield: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2 4 5v6c0 5 3.4 9.4 8 11 4.6-1.6 8-6 8-11V5l-8-3Zm-1.2 14-3.3-3.3 1.4-1.4 1.9 1.9 4.6-4.6 1.4 1.4-6 6Z"/></svg>',
  share: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><path d="m8.6 13.5 6.8 4M15.4 6.5l-6.8 4"/></svg>',
  down: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12m0 0-4-4m4 4 4-4M4 21h16"/></svg>',
}
export function iconButton(label, icon, extraClass = '') {
  const b = document.createElement('button')
  b.type = 'button'
  b.className = `up-btn ${extraClass}`.trim()
  b.innerHTML = `${ICON[icon] || ''}<span></span>`   // icon markup is a constant above
  b.lastChild.textContent = label
  return b
}

// ---------------------------------------------------------------- lightbox (full screen + Download)
export function openLightbox(images, start = 0) {
  let i = start
  const opener = document.activeElement
  const root = document.createElement('div')
  root.className = 'up-lb'
  root.setAttribute('role', 'dialog')
  root.setAttribute('aria-modal', 'true')
  root.setAttribute('aria-label', 'Image viewer')
  const bar = document.createElement('div'); bar.className = 'up-lb-bar'
  const count = document.createElement('span'); count.className = 'up-lb-count'
  const dl = document.createElement('a'); dl.className = 'up-btn'; dl.innerHTML = ICON.down + '<span>Download</span>'
  const close = document.createElement('button'); close.type = 'button'; close.className = 'up-btn'; close.textContent = 'Close'
  bar.append(count, dl, close)
  const stage = document.createElement('div'); stage.className = 'up-lb-stage'
  const img = document.createElement('img'); img.alt = ''
  stage.appendChild(img)
  const prev = document.createElement('button'); prev.type = 'button'; prev.className = 'up-lb-nav up-lb-prev'; prev.textContent = '‹'; prev.setAttribute('aria-label', 'Previous image')
  const next = document.createElement('button'); next.type = 'button'; next.className = 'up-lb-nav up-lb-next'; next.textContent = '›'; next.setAttribute('aria-label', 'Next image')
  if (images.length > 1) stage.append(prev, next)
  root.append(bar, stage)

  const show = () => {
    img.src = images[i].url
    dl.href = images[i].download_url        // Supabase ?download= -> saves as a file on phones, cross-origin
    dl.setAttribute('download', '')
    count.textContent = images.length > 1 ? `${i + 1} / ${images.length}` : ''
  }
  const go = (d) => { i = (i + d + images.length) % images.length; show() }
  const shut = () => { document.removeEventListener('keydown', onKey); root.remove(); document.body.style.overflow = ''; if (opener && opener.focus) opener.focus() }
  const onKey = (e) => { if (e.key === 'Escape') shut(); else if (e.key === 'ArrowLeft' && images.length > 1) go(-1); else if (e.key === 'ArrowRight' && images.length > 1) go(1) }
  close.addEventListener('click', shut)
  prev.addEventListener('click', () => go(-1))
  next.addEventListener('click', () => go(1))
  stage.addEventListener('click', (e) => { if (e.target === stage) shut() })
  document.addEventListener('keydown', onKey)
  document.body.style.overflow = 'hidden'
  document.body.appendChild(root)
  show()
  close.focus()
}

// ---------------------------------------------------------------- one post card
export function renderPost(post, { isNew = false } = {}) {
  const el = document.createElement('article')
  el.className = 'up-card' + (isNew ? ' is-new' : '')
  el.id = `u-${post.id}`

  const meta = document.createElement('div'); meta.className = 'up-meta'
  const badge = document.createElement('span'); badge.className = 'up-badge'
  badge.innerHTML = ICON.shield + '<span></span>'
  badge.lastChild.textContent = post.badge || 'Evoxera Admin'
  meta.appendChild(badge)
  if (isNew) { const n = document.createElement('span'); n.className = 'up-new'; n.textContent = 'New'; meta.appendChild(n) }
  const time = document.createElement('time'); time.className = 'up-time'
  time.dateTime = post.created_at || ''
  time.title = post.created_at ? new Date(post.created_at).toLocaleString() : ''
  time.textContent = ago(post.created_at)
  meta.appendChild(time)
  el.appendChild(meta)

  if (post.body) {
    const p = document.createElement('p'); p.className = 'up-body'
    p.appendChild(linkify(post.body))
    el.appendChild(p)
  }
  if (post.edited_at) { const e = document.createElement('p'); e.className = 'up-edited'; e.textContent = 'Edited'; el.appendChild(e) }

  const imgs = post.images || []
  if (imgs.length) {
    const grid = document.createElement('div'); grid.className = 'up-imgs'; grid.dataset.n = String(imgs.length)
    imgs.forEach((im, idx) => {
      const b = document.createElement('button'); b.type = 'button'; b.className = 'up-img'; b.setAttribute('aria-label', `Open image ${idx + 1} of ${imgs.length}`)
      const t = document.createElement('img'); t.src = im.url; t.alt = ''; t.loading = 'lazy'; t.decoding = 'async'
      if (im.width && im.height) { t.width = im.width; t.height = im.height }
      b.appendChild(t)
      b.addEventListener('click', () => openLightbox(imgs, idx))
      grid.appendChild(b)
    })
    el.appendChild(grid)
  }

  const actions = document.createElement('div'); actions.className = 'up-actions'
  const share = iconButton('Share', 'share')
  share.addEventListener('click', async () => {
    const r = await sharePost(post)
    if (r === 'copied') toast('Link copied')
    else if (r === 'failed') toast('Could not share')
  })
  actions.appendChild(share)
  if (imgs.length) {
    const dl = iconButton(imgs.length > 1 ? 'Download images' : 'Download image', 'down')
    dl.addEventListener('click', () => openLightbox(imgs, 0))
    actions.appendChild(dl)
  }
  el.appendChild(actions)
  return { el, actions }
}
