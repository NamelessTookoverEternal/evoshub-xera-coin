// EVOS Hub app home (/appevoxera): greeting, one XERA status card, icon grid, last 3 activity.
// Guest-first: everything is browsable signed out; balance / mining / activity need an account
// and are fetched only when signed in. Nothing here starts or claims mining — the card opens XERA.
import './theme.js'
import './hub-auth.js'
import './evosdata-gate.js'
import { initInstallButton } from './pwa.js'
import { isLoggedIn, getUser } from './evos-session.js'
import { apiFetch as api } from './hub-api.js'
import { requireAuthFor } from './guest-access.js'
import { fetchPublicJson } from './xera-public.js'
import { resolveEcosystemLink, makeEcosystemDeduper } from './internal-links.js'
import { fetchUpdates, getSeen, ago as updatesAgo } from './updates-core.js'

initInstallButton(document.getElementById('install-btn'), { alwaysShow: true, hint: document.getElementById('install-hint') })

const $ = (id) => document.getElementById(id)
const signedIn = isLoggedIn()

// ---- icon tiles: real logo when it loads, else the glyph ----
function wireTiles(root) {
  root.querySelectorAll('.ah-tile img').forEach((img) => {
    const svg = img.parentElement.querySelector('svg')
    const ok = () => { if (img.naturalWidth > 0 && svg) svg.style.display = 'none' }
    img.addEventListener('error', () => img.remove(), { once: true })
    if (img.complete) { if (img.naturalWidth > 0) ok(); else img.remove() }
    else img.addEventListener('load', ok, { once: true })
  })
}
const grid = $('appGrid')
wireTiles(grid)
fetchPublicJson('/api/xera/ecosystem').then((d) => {
  const isDuplicate = makeEcosystemDeduper(grid, '.ah-app-name')
  ;(d.links || []).forEach((l) => {
    const dest = resolveEcosystemLink(l.url)
    if (isDuplicate(l, dest)) return   // already has a built-in tile (e.g. EVOS GPT)
    const a = document.createElement('a')
    a.className = 'ah-app'
    a.href = dest.href
    if (dest.external) { a.target = '_blank'; a.rel = 'noopener' }
    const tile = document.createElement('span')
    tile.className = 'ah-tile'
    if (l.image_url) { const img = document.createElement('img'); img.src = l.image_url; img.alt = ''; img.loading = 'lazy'; tile.appendChild(img) }
    const name = document.createElement('span')
    name.className = 'ah-app-name'
    name.textContent = l.name // textContent only: admin text is never parsed as HTML
    a.append(tile, name)
    grid.appendChild(a)
  })
  wireTiles(grid)
}).catch(() => { /* curated icons are optional */ })

// ---- greeting ----
const user = getUser()
const first = String(user?.full_name || user?.username || '').trim().split(/\s+/)[0]
if (signedIn) { $('greetEyebrow').textContent = 'Welcome back'; $('welcomeName').textContent = first || 'there' }
else { $('welcomeName').textContent = 'there' }

// ---- XERA status card ----
const card = $('xeraStatusCard')
const setCard = (state, text) => { card.dataset.state = state; $('xeraCardPill').textContent = text; $('barMid')?.classList.toggle('is-mining', state === 'mining') }
const fmt = (n) => (Number(n) || 0).toLocaleString(undefined, { maximumFractionDigits: 3, minimumFractionDigits: 0 })
const clock = (ms) => {
  const t = Math.max(0, Math.floor(ms / 1000))
  return [Math.floor(t / 3600), Math.floor((t % 3600) / 60), t % 60].map((v) => String(v).padStart(2, '0')).join(':')
}

async function loadXera() {
  if (!signedIn) { setCard('guest', 'Sign in to start mining'); return }
  const [w, m] = await Promise.allSettled([api('/api/xera/wallet'), api('/api/xera/mining/status')])
  const wallet = w.status === 'fulfilled' ? w.value : null
  $('xeraCardBalance').textContent = wallet && wallet.status === 'ok' ? fmt(wallet.balance) : '—'
  const mining = m.status === 'fulfilled' && m.value && m.value.status === 'ok' ? (m.value.mining || null) : undefined
  if (mining === undefined) return setCard('unknown', 'Open XERA')
  if (!mining) return setCard('ready', 'Ready to mine')
  const end = new Date(mining.expires_at).getTime()
  const tick = () => {
    const left = end - Date.now()
    if (!Number.isFinite(left)) return setCard('unknown', 'Open XERA')
    if (left <= 0) { clearInterval(timer); return setCard('claim', 'Claim ready') }
    setCard('mining', `Mining · ${clock(left)} left`)
  }
  const timer = setInterval(tick, 1000)
  tick()
}

// ---- last 3 activity ----
const LABELS = { MINING_REWARD: 'Mining reward', DAILY_CLAIM: 'Daily claim', REFERRAL_REWARD: 'Referral reward', XERA_PURCHASE: 'XERA purchase', BONUS: 'Bonus', ADMIN_CREDIT: 'Balance adjustment', ADMIN_DEBIT: 'Balance adjustment', REVERSAL: 'Reversal', MIGRATION: 'Migration' }
const esc = (s) => { const d = document.createElement('div'); d.textContent = String(s ?? ''); return d.innerHTML }
function ago(iso) {
  const mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  if (mins < 1440) return `${Math.floor(mins / 60)}h ago`
  return `${Math.floor(mins / 1440)}d ago`
}
async function loadActivity() {
  const list = $('activityList')
  if (!signedIn) { list.innerHTML = '<p class="ah-empty"><a href="/xera">Sign in</a> to see your XERA activity.</p>'; return }
  try {
    const res = await api('/api/xera/transactions?limit=3')
    const txs = res.status === 'ok' ? (res.transactions || []).slice(0, 3) : []
    if (!txs.length) { list.innerHTML = '<p class="ah-empty">No activity yet — start mining to see it here.</p>'; return }
    list.innerHTML = txs.map((tx) => {
      const type = String(tx.type || '').toUpperCase()
      const label = LABELS[type] || (type ? type.replaceAll('_', ' ').toLowerCase().replace(/^\w/, (c) => c.toUpperCase()) : 'Transaction')
      const credit = tx.direction ? tx.direction === 'CREDIT' : Number(tx.amount) > 0
      return `<div class="ah-row"><div><p class="ah-row-title">${esc(label)}</p><p class="ah-row-time">${esc(tx.created_at ? ago(tx.created_at) : '')}</p></div><span class="ah-row-amt${credit ? ' pos' : ''}">${credit ? '+' : '-'}${fmt(Math.abs(Number(tx.amount) || 0))} XERA</span></div>`
    }).join('')
  } catch (e) { list.innerHTML = '<p class="ah-empty">Couldn’t load activity right now.</p>' }
}

// Guests tapping Activity get the standard sign-in prompt instead of an empty list.
$('barActivity').addEventListener('click', (e) => {
  if (!signedIn) { e.preventDefault(); requireAuthFor('see your activity', { next: '/appevoxera' }) }
})

loadXera()
loadActivity()

// ---- Updates card: newest announcement + unread count (read-only, public, no sign-in needed) ----
async function loadUpdatesCard() {
  const row = $('updatesRow')
  try {
    const { updates, hasMore } = await fetchUpdates({ limit: 10 })
    if (!updates.length) { row.innerHTML = '<p class="ah-updates-empty">No updates yet.</p>'; return }
    const seen = getSeen()
    const fresh = updates.filter((u) => u.id > seen).length
    if (fresh) {
      $('updatesCount').textContent = `${fresh >= 10 && hasMore ? '10+' : fresh} new`
      $('updatesCount').hidden = false
      $('updatesCard').classList.add('has-new')
    }
    const top = updates[0]
    row.textContent = ''
    if (top.images && top.images[0]) {
      const t = document.createElement('img'); t.className = 'ah-updates-thumb'; t.src = top.images[0].url; t.alt = ''; t.loading = 'lazy'; t.width = 54; t.height = 54
      t.addEventListener('error', () => t.remove(), { once: true })
      row.appendChild(t)
    }
    const box = document.createElement('div'); box.style.minWidth = '0'
    const txt = document.createElement('p'); txt.className = 'ah-updates-text'
    txt.textContent = top.body || (top.images && top.images.length > 1 ? `${top.images.length} new images` : 'New image')   // textContent only
    const tm = document.createElement('p'); tm.className = 'ah-updates-time'; tm.textContent = updatesAgo(top.created_at)
    box.append(txt, tm)
    row.appendChild(box)
  } catch (e) { row.innerHTML = '<p class="ah-updates-empty">Tap to see the latest updates.</p>' }
}
loadUpdatesCard()

// ---- Admin shortcut: only for an active admin agent. This just shows a button; every admin page still needs the admin login. ----
async function initAdminStrip() {
  if (!signedIn) return
  let res
  try { res = await api('/api/updates/agent-status') } catch (e) { return }
  if (!res || res.is_agent !== true) return
  const strip = $('admStrip'), scrim = $('admScrim')
  strip.hidden = false
  const open = () => { scrim.hidden = false; document.addEventListener('keydown', onKey); $('admClose').focus() }
  const close = () => { scrim.hidden = true; document.removeEventListener('keydown', onKey); strip.focus() }
  const onKey = (e) => { if (e.key === 'Escape') close() }
  strip.addEventListener('click', open)
  $('admClose').addEventListener('click', close)
  scrim.addEventListener('click', (e) => { if (e.target === scrim) close() })
  scrim.querySelectorAll('a').forEach((a) => a.addEventListener('click', () => setTimeout(close, 0)))
}
initAdminStrip()


// ---- invite button: share a join link (uses your XERA referral link when signed in) ----
{
  const btn = $('inviteBtn'), sub = $('inviteSub')
  const idle = sub.textContent
  const say = (t) => { sub.textContent = t; setTimeout(() => { sub.textContent = idle }, 2200) }
  btn.addEventListener('click', async () => {
    let link = `${location.origin}/`
    if (signedIn) {
      try { const r = await api('/api/xera/referral/me'); if (r && r.link) link = r.link } catch (e) { /* share the plain site link */ }
    }
    const text = `Join me on Evoxera Technology, a hub for tech fans: blockchain and more. ${link}`
    try {
      if (navigator.share) await navigator.share({ title: 'Join Evoxera Technology', text })
      else { await navigator.clipboard.writeText(text); say('Invite link copied') }
    } catch (e) { if (e && e.name !== 'AbortError') say('Could not share. Try again.') }
  })
}
