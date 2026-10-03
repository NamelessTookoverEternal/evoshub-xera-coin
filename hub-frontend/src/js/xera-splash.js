// XERA — app startup splash. Plays once per session on /xera, then reveals the dashboard underneath.
import './pwa.js'

const SEEN_KEY = 'xera-splash-seen'
const splash = document.getElementById('xeraSplash')

if (splash) {
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches

  let seen = false
  try { seen = sessionStorage.getItem(SEEN_KEY) === '1' } catch { /* storage unavailable */ }

  const finish = () => {
    try { sessionStorage.setItem(SEEN_KEY, '1') } catch { /* ignore */ }
    splash.classList.add('is-leaving')
    window.setTimeout(() => splash.remove(), reduceMotion ? 0 : 500)
  }

  if (seen) {
    splash.remove()
  } else {
    const timer = window.setTimeout(finish, reduceMotion ? 1400 : 2800)
    splash.querySelector('.xsplash__skip')?.addEventListener('click', (e) => {
      e.preventDefault()
      window.clearTimeout(timer)
      finish()
    })
  }
}
