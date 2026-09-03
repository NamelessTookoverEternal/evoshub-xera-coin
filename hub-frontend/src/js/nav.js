// EVOSHUB — Navigation
import './theme.js'

const hamburger = document.querySelector('.hamburger')
const navLinks  = document.querySelector('.nav-links')

hamburger?.addEventListener('click', () => {
  navLinks.classList.toggle('nav-links--open')
  hamburger.classList.toggle('is-open')
})

navLinks?.querySelectorAll('a').forEach(a => {
  a.addEventListener('click', () => {
    navLinks.classList.remove('nav-links--open')
    hamburger?.classList.remove('is-open')
  })
})

// Close the mobile menu on resize back up to desktop, and on Escape.
window.addEventListener('resize', () => {
  if (window.innerWidth > 860) {
    navLinks?.classList.remove('nav-links--open')
    hamburger?.classList.remove('is-open')
  }
})
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    navLinks?.classList.remove('nav-links--open')
    hamburger?.classList.remove('is-open')
  }
})

// Active highlight on scroll (only relevant on pages with in-page sections)
const sections = document.querySelectorAll('section[id]')
const links    = document.querySelectorAll('.nav-links a')

if (sections.length) {
  window.addEventListener('scroll', () => {
    let current = ''
    sections.forEach(s => { if (window.scrollY >= s.offsetTop - 100) current = s.id })
    links.forEach(a => {
      a.classList.toggle('active', a.getAttribute('href') === '#' + current)
    })
  }, { passive: true })
}
