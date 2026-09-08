// EVOSHUB — Theme Toggle (dark/light, persisted)
const STORAGE_KEY = 'evos-theme'
const root = document.documentElement

function applyTheme(theme) {
  root.setAttribute('data-theme', theme)
  document.querySelectorAll('.theme-toggle').forEach(btn => {
    btn.setAttribute('aria-label', theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode')
  })
}

function getInitialTheme() {
  const saved = localStorage.getItem(STORAGE_KEY)
  if (saved === 'dark' || saved === 'light') return saved
  return window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark'
}

applyTheme(getInitialTheme())

document.querySelectorAll('.theme-toggle').forEach(btn => {
  btn.addEventListener('click', () => {
    const next = root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark'
    applyTheme(next)
    localStorage.setItem(STORAGE_KEY, next)
  })
})
