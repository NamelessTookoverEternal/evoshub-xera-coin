// EVOS Hub — PWA support: service worker registration + optional install prompt.
// Installation is never forced: the install button only appears when the
// browser itself reports the app is installable.

if ('serviceWorker' in navigator && window.isSecureContext) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch((err) => {
      console.warn('[evos] service worker not registered:', err)
    })
  })
}

let deferredPrompt = null

export function initInstallButton(button) {
  if (!button) return

  const standalone =
    window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true
  if (standalone) return

  window.addEventListener('beforeinstallprompt', (event) => {
    event.preventDefault()
    deferredPrompt = event
    button.classList.add('is-available')
  })

  button.addEventListener('click', async () => {
    if (!deferredPrompt) return
    deferredPrompt.prompt()
    await deferredPrompt.userChoice.catch(() => null)
    deferredPrompt = null
    button.classList.remove('is-available')
  })

  window.addEventListener('appinstalled', () => {
    deferredPrompt = null
    button.classList.remove('is-available')
  })
}
