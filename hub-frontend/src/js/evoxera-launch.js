// EVOXERA — launch screen (/). Plays once per session, then hands off to /appevoxera.
import './pwa.js'

const HUB = '/appevoxera'
const SEEN_KEY = 'evx-launch-seen'

const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
const launch = document.getElementById('launch')

let alreadySeen = false
try { alreadySeen = sessionStorage.getItem(SEEN_KEY) === '1' } catch { /* storage unavailable */ }

function go() {
  try { sessionStorage.setItem(SEEN_KEY, '1') } catch { /* ignore */ }
  // replace(), so Back from the hub leaves the app instead of looping into the splash
  window.location.replace(HUB)
}

if (alreadySeen) {
  // e.g. a "Home" link elsewhere on the site: skip the animation, no wait
  window.location.replace(HUB)
} else {
  const total = reduceMotion ? 1400 : 2800
  const timer = window.setTimeout(() => {
    launch?.classList.add('is-leaving')
    window.setTimeout(go, reduceMotion ? 0 : 450)
  }, total)

  document.querySelector('.launch__skip')?.addEventListener('click', (e) => {
    e.preventDefault()
    window.clearTimeout(timer)
    go()
  })
}
