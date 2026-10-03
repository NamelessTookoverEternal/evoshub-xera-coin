// EVOXERA — visual-only effects for the launch screen and /appevoxera.
// Ambient particles + pointer light on product panels. No routing, auth, PWA,
// storage or network logic lives here; removing this file leaves every page functional.

const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches

// ── Ambient particles (lightweight, ~30fps, paused when the tab is hidden) ──
function initParticles(canvas) {
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  let w = 0, h = 0, dpr = 1, parts = [], raf = 0, last = 0

  const seed = () => {
    const count = Math.round(Math.min(64, Math.max(22, (w * h) / 26000)))
    parts = Array.from({ length: count }, () => ({
      x: Math.random() * w, y: Math.random() * h,
      r: Math.random() * 1.1 + .35,
      vx: (Math.random() - .5) * .08, vy: -(Math.random() * .1 + .02),
      a: Math.random() * .35 + .08, t: Math.random() * 6.28, s: Math.random() * .6 + .25,
    }))
  }
  const size = () => {
    const box = canvas.parentElement.getBoundingClientRect()
    dpr = Math.min(window.devicePixelRatio || 1, 1.5)
    w = box.width; h = Math.max(box.height, canvas.parentElement.scrollHeight || 0)
    canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr)
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    seed()
  }
  const draw = (now) => {
    ctx.clearRect(0, 0, w, h)
    for (const p of parts) {
      const tw = .65 + .35 * Math.sin(now * .001 * p.s + p.t)
      ctx.fillStyle = `rgba(150,195,255,${(p.a * tw).toFixed(3)})`
      ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, 6.2832); ctx.fill()
    }
  }
  const tick = (now) => {
    raf = requestAnimationFrame(tick)
    if (now - last < 33) return
    last = now
    for (const p of parts) {
      p.x += p.vx; p.y += p.vy
      if (p.y < -4) { p.y = h + 4; p.x = Math.random() * w }
      if (p.x < -4) p.x = w + 4; else if (p.x > w + 4) p.x = -4
    }
    draw(now)
  }

  size()
  if (reduceMotion) { draw(0); window.addEventListener('resize', () => { size(); draw(0) }); return }
  raf = requestAnimationFrame(tick)
  let rt = 0
  window.addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(size, 150) })
  document.addEventListener('visibilitychange', () => {
    cancelAnimationFrame(raf)
    if (!document.hidden) raf = requestAnimationFrame(tick)
  })
}

// ── Pointer light on product panels (mouse / pen only; CSS handles focus + touch) ──
function initLight(el) {
  el.addEventListener('pointermove', (e) => {
    if (e.pointerType === 'touch') return
    const r = el.getBoundingClientRect()
    const x = e.clientX - r.left, y = e.clientY - r.top
    el.style.setProperty('--mx', x + 'px')
    el.style.setProperty('--my', y + 'px')
    el.style.setProperty('--px', (x / r.width).toFixed(3))
    el.style.setProperty('--py', (y / r.height).toFixed(3))
  })
  el.addEventListener('pointerleave', () => {
    ;['--mx', '--my', '--px', '--py'].forEach((k) => el.style.removeProperty(k))
  })
}

const canvas = document.querySelector('.fx-canvas')
if (canvas) initParticles(canvas)
document.querySelectorAll('.ptile:not(.ptile--soon)').forEach(initLight)
