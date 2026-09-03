// EVOSHUB — Hero 3D flow-in + parallax
// ─────────────────────────────────────────────────────────────
// Tag any hero element with `data-flow-in` and (optionally)
// `data-depth="N"` to control how far it drifts on mouse parallax
// (bigger N = more movement — use bigger values for elements meant
// to feel "closer" to the viewer). Example:
//
//   <h1 data-flow-in data-depth="10">...</h1>
//   <p  data-flow-in data-depth="6">...</p>
//
// Entrance: elements fade/translate/rotate in once on load, in the
// order they appear in the DOM (staggered via transition-delay).
//
// Parallax: only binds on non-touch pointers, only while 3D effects
// are enabled, and only inside the nearest `.hero`/`.biz-hero`
// ancestor so it doesn't fire for the whole page.

import { isMotion3DEnabled, onMotion3DChange } from './motion3d.js'

const els = Array.from(document.querySelectorAll('[data-flow-in]'))

if (els.length && !window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
  // Stagger: give each element a small extra delay if it doesn't
  // already declare one inline, so the heading leads and the
  // subhead/buttons "flow in" a beat behind it.
  els.forEach((el, i) => {
    if (!el.style.transitionDelay) el.style.transitionDelay = `${i * 90}ms`
  })

  // Trigger the entrance on the next frame (so the resting styles in
  // motion-3d.css are painted first and the transition actually runs).
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      els.forEach(el => el.classList.add('flow-in-visible'))
    })
  })

  // Once the longest entrance transition finishes, switch to the
  // faster "parallax-ready" transition and start tracking the
  // pointer — but only on devices with a fine pointer (mouse/trackpad),
  // never on touch, and never if effects are toggled off.
  const isFinePointer = window.matchMedia('(pointer: fine)').matches
  const longestDelay = Math.max(...els.map((_, i) => i * 90))

  setTimeout(() => {
    els.forEach(el => el.classList.add('flow-in-parallax-ready'))
    if (isFinePointer) bindParallax()
  }, longestDelay + 750)
}

function bindParallax() {
  const hero = els[0].closest('.hero, .biz-hero') || document.body
  let bound = false

  function handleMove(e) {
    if (!isMotion3DEnabled()) return
    const rect = hero.getBoundingClientRect()
    // Normalise to -0.5..0.5 across the hero's own bounds.
    const nx = ((e.clientX - rect.left) / rect.width) - 0.5
    const ny = ((e.clientY - rect.top) / rect.height) - 0.5

    els.forEach(el => {
      const depth = Number(el.dataset.depth || 6)
      const rotX = (-ny * 3).toFixed(2)
      const rotY = (nx * 3).toFixed(2)
      const tx = (nx * depth).toFixed(1)
      const ty = (ny * depth * 0.6).toFixed(1)
      el.style.transform =
        `translate(${tx}px, ${ty}px) translateZ(0) rotateX(${rotX}deg) rotateY(${rotY}deg)`
    })
  }

  function reset() {
    els.forEach(el => { el.style.transform = 'translate(0,0) translateZ(0) rotateX(0deg) rotateY(0deg)' })
  }

  function bind() {
    if (bound || !isMotion3DEnabled()) return
    hero.addEventListener('pointermove', handleMove, { passive: true })
    hero.addEventListener('pointerleave', reset, { passive: true })
    bound = true
  }
  function unbind() {
    if (!bound) return
    hero.removeEventListener('pointermove', handleMove)
    hero.removeEventListener('pointerleave', reset)
    bound = false
    reset()
  }

  bind()
  onMotion3DChange(on => (on ? bind() : unbind()))
}
