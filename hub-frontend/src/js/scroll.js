// EVOSHUB — Scroll Animations
const observer = new IntersectionObserver((entries) => {
  entries.forEach(el => { if (el.isIntersecting) el.target.classList.add('visible') })
}, { threshold: 0.12, rootMargin: '0px 0px -40px 0px' })

document.querySelectorAll('.fade-up').forEach((el, i) => {
  el.style.transitionDelay = (i % 4) * 0.08 + 's'
  observer.observe(el)
})
