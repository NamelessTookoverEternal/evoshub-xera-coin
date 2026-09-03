// EVOSHUB — 3D staggered card entrance + tilt-on-hover
// ─────────────────────────────────────────────────────────────
// Wrap any card grid with `data-stagger-cards` and every direct
// `.card` inside it gets:
//   1. A 3D entrance (rotate + rise + fade in) the first time it
//      scrolls into view, staggered by its position in the grid.
//   2. A gentle ±5deg tilt that follows the cursor while hovered
//      (mouse/trackpad only — never fires on touch).
//
// This runs independently of the existing `.fade-up` system in
// scroll.js; the two can be used side by side on the same page.

import { isMotion3DEnabled, onMotion3DChange } from './motion3d.js'

const STAGGER_STEP_MS = 90
const STAGGER_CAP_MS = 450
const TILT_MAX_DEG = 5
const isFinePointer = window.matchMedia('(pointer: fine)').matches
const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches

// ── 1. Scroll entrance ──────────────────────────────────────
document.querySelectorAll('[data-stagger-cards]').forEach(grid => {
  const cards = Array.from(grid.querySelectorAll('.card'))
  if (!cards.length) return

  if (reduceMotion) {
    cards.forEach(c => c.classList.add('card-3d-in'))
    return
  }

  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (!entry.isIntersecting) return
      const card = entry.target
      const i = cards.indexOf(card)
      const delay = Math.min(i * STAGGER_STEP_MS, STAGGER_CAP_MS)
      card.style.transitionDelay = `${delay}ms`

      card.addEventListener('transitionend', function clearDelay(e) {
        if (e.propertyName !== 'transform') return
        card.style.transitionDelay = '' // don't delay future hover transitions
        card.removeEventListener('transitionend', clearDelay)
      })

      card.classList.add('card-3d-in')
      observer.unobserve(card)
    })
  }, { threshold: 0.15, rootMargin: '0px 0px -60px 0px' })

  cards.forEach(card => observer.observe(card))
})

// ── 2. Tilt-on-hover ─────────────────────────────────────────
if (isFinePointer && !reduceMotion) {
  const tiltCards = document.querySelectorAll('[data-stagger-cards] .card')
  const unbinders = []

  tiltCards.forEach(card => {
    function handleMove(e) {
      if (!isMotion3DEnabled()) return
      const rect = card.getBoundingClientRect()
      const px = (e.clientX - rect.left) / rect.width - 0.5   // -0.5..0.5
      const py = (e.clientY - rect.top) / rect.height - 0.5
      card.style.setProperty('--tilt-x', `${(-py * TILT_MAX_DEG * 2).toFixed(2)}deg`)
      card.style.setProperty('--tilt-y', `${(px * TILT_MAX_DEG * 2).toFixed(2)}deg`)
    }
    function handleLeave() {
      card.style.setProperty('--tilt-x', '0deg')
      card.style.setProperty('--tilt-y', '0deg')
    }

    card.addEventListener('pointermove', handleMove)
    card.addEventListener('pointerleave', handleLeave)
    unbinders.push(() => {
      card.removeEventListener('pointermove', handleMove)
      card.removeEventListener('pointerleave', handleLeave)
      handleLeave()
    })
  })

  onMotion3DChange(on => {
    if (!on) unbinders.forEach(fn => fn())
    // Re-binding isn't needed — listeners stay attached, they just
    // no-op via the isMotion3DEnabled() check inside handleMove.
  })
}
