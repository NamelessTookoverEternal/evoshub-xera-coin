// EVOSHUB — 3D Motion: shared toggle & state
// ─────────────────────────────────────────────────────────────
// Single source of truth for whether the "light 3D" enhancements
// (hero flow-in/parallax, card stagger+tilt, background blobs) are
// allowed to run. Other modules read `isMotion3DEnabled()` once and
// subscribe to `onMotion3DChange()` for live updates when the user
// flips the toggle mid-session.
//
// Default OFF triggers (any one is enough):
//   - prefers-reduced-motion: reduce
//   - navigator.connection.saveData (user has "Data Saver" on)
// Otherwise defaults ON, then remembers the user's choice.

const STORAGE_KEY = 'evos-motion3d'

function systemPrefersReducedMotion() {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

function systemPrefersSavingData() {
  return !!(navigator.connection && navigator.connection.saveData)
}

function computeDefault() {
  if (systemPrefersReducedMotion() || systemPrefersSavingData()) return false
  return true
}

function readStoredPreference() {
  try {
    const v = localStorage.getItem(STORAGE_KEY)
    if (v === 'on') return true
    if (v === 'off') return false
  } catch (e) { /* localStorage unavailable (private mode, etc.) — fall through */ }
  return null
}

let enabled = readStoredPreference()
if (enabled === null) enabled = computeDefault()

document.documentElement.setAttribute('data-motion3d', enabled ? 'on' : 'off')

export function isMotion3DEnabled() {
  return enabled
}

export function setMotion3DEnabled(next) {
  enabled = !!next
  document.documentElement.setAttribute('data-motion3d', enabled ? 'on' : 'off')
  try { localStorage.setItem(STORAGE_KEY, enabled ? 'on' : 'off') } catch (e) { /* ignore */ }
  document.dispatchEvent(new CustomEvent('motion3d-change', { detail: { enabled } }))
  syncButtons()
}

export function onMotion3DChange(handler) {
  document.addEventListener('motion3d-change', (e) => handler(e.detail.enabled))
}

// If the OS-level setting changes while the page is open, follow it
// (only when the user hasn't explicitly chosen a preference already).
window.matchMedia('(prefers-reduced-motion: reduce)').addEventListener?.('change', (e) => {
  if (readStoredPreference() !== null) return // user already made an explicit choice — respect it
  setMotion3DEnabled(!e.matches)
})

// ── Toggle button — small pill next to the existing theme-toggle.
// Injected next to every .theme-toggle found on the page so it shows
// up automatically without editing every page's markup by hand. ──
function buildButton() {
  const btn = document.createElement('button')
  btn.type = 'button'
  btn.className = 'motion3d-toggle'
  btn.setAttribute('aria-label', 'Toggle 3D effects')
  btn.setAttribute('aria-pressed', String(enabled))
  btn.title = enabled ? '3D effects: on (click to turn off for performance)' : '3D effects: off (click to turn on)'
  btn.textContent = '✨'
  btn.addEventListener('click', () => setMotion3DEnabled(!isMotion3DEnabled()))
  return btn
}

const buttons = []
function syncButtons() {
  buttons.forEach(btn => {
    btn.setAttribute('aria-pressed', String(enabled))
    btn.title = enabled ? '3D effects: on (click to turn off for performance)' : '3D effects: off (click to turn on)'
  })
}

document.querySelectorAll('.theme-toggle').forEach(themeBtn => {
  const b = buildButton()
  themeBtn.insertAdjacentElement('afterend', b)
  buttons.push(b)
})
