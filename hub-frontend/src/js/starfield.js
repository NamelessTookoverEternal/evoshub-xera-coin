// EVOSHUB — Starfield
// Scatters a handful of twinkling points (+ a couple of shooting
// stars) into any element with class="starfield". Purely decorative:
// pointer-events are off in CSS, and it respects prefers-reduced-motion
// automatically via the global animation-kill rule in global.css.
const field = document.querySelector('.starfield')

if (field && !window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
  const count = window.innerWidth < 640 ? 40 : 75
  const frag = document.createDocumentFragment()

  for (let i = 0; i < count; i++) {
    const s = document.createElement('span')
    s.className = 'star'
    const size = (Math.random() * 1.8 + 0.8).toFixed(1)
    s.style.width  = `${size}px`
    s.style.height = `${size}px`
    s.style.left = `${(Math.random() * 100).toFixed(2)}%`
    s.style.top  = `${(Math.random() * 100).toFixed(2)}%`
    s.style.setProperty('--star-dur',   `${(Math.random() * 3 + 2).toFixed(1)}s`)
    s.style.setProperty('--star-delay', `${(Math.random() * 6).toFixed(1)}s`)
    s.style.setProperty('--star-peak',  (Math.random() * 0.5 + 0.4).toFixed(2))
    frag.appendChild(s)
  }

  for (let i = 0; i < 2; i++) {
    const sh = document.createElement('span')
    sh.className = 'shooting-star'
    sh.style.top  = `${(8 + Math.random() * 26)}%`
    sh.style.left = `${(45 + Math.random() * 45)}%`
    sh.style.setProperty('--star-delay', `${(i * 5 + Math.random() * 4).toFixed(1)}s`)
    frag.appendChild(sh)
  }

  field.appendChild(frag)
}
