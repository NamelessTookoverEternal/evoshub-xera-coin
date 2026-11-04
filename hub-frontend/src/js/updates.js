// /updates — public read-only feed of admin announcements. Anyone can read; nothing here writes.
import './theme.js'
import { fetchUpdates, getSeen, setSeen, renderPost } from './updates-core.js'

const $ = (id) => document.getElementById(id)
const feed = $('feed')
const seenAtLoad = getSeen()           // "New" marks are decided once per visit, then the seen mark moves on
let oldest = null
let busy = false

function state(msg, retry) {
  feed.querySelectorAll('.up-state').forEach((n) => n.remove())
  const d = document.createElement('div'); d.className = 'up-state'
  d.textContent = msg
  if (retry) { const b = document.createElement('button'); b.type = 'button'; b.className = 'up-btn'; b.textContent = 'Try again'; b.addEventListener('click', retry); d.appendChild(b) }
  feed.appendChild(d)
}

async function load(first) {
  if (busy) return
  busy = true
  $('moreBtn').hidden = true
  try {
    const { updates, hasMore } = await fetchUpdates({ limit: 15, before: first ? undefined : oldest })
    feed.querySelectorAll('.up-state').forEach((n) => n.remove())
    if (first && !updates.length) { state('No updates yet. Check back soon.'); return }
    if (first) setSeen(updates[0].id)
    for (const u of updates) feed.appendChild(renderPost(u, { isNew: u.id > seenAtLoad }).el)
    if (updates.length) oldest = updates[updates.length - 1].id
    $('moreBtn').hidden = !hasMore
    if (first && location.hash.startsWith('#u-')) document.getElementById(location.hash.slice(1))?.scrollIntoView({ block: 'start' })
  } catch (e) {
    state('Could not load updates right now.', () => { busy = false; load(first) })
  } finally { busy = false }
}

$('moreBtn').addEventListener('click', () => load(false))
state('Loading…')
load(true)
