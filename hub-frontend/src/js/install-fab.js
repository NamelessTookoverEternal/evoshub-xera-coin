// Floating "Install app" button for the Evos Hub home page and the XERA app.
// Uses the browser's own install popup (beforeinstallprompt) via pwa.js. Chrome/Edge/Android show the popup;
// iPhone Safari has no popup, so tapping the button shows "Share, then Add to Home Screen".
// Hidden once the app is installed or opened from the home screen. The person can dismiss it (remembered).
import { initInstallButton } from './pwa.js'

const KEY = 'evos-install-dismissed'
const stored = (fn) => { try { return fn() } catch (_e) { return null } }

const standalone = window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true
if (!standalone && !stored(() => localStorage.getItem(KEY))) {
  const label = document.documentElement.dataset.installLabel || 'Install app'

  const css = document.createElement('style')
  css.textContent =
    '.evos-fab{position:fixed;right:12px;bottom:calc(84px + env(safe-area-inset-bottom));z-index:9000;display:none;max-width:min(320px,calc(100vw - 24px));flex-direction:column;align-items:flex-end;gap:8px}' +
    '.evos-fab.is-on{display:flex}' +
    '.evos-fab-row{display:flex;align-items:center;gap:6px;padding:4px 4px 4px 4px;border-radius:999px;background:#10162a;border:1px solid rgba(255,255,255,.18);box-shadow:0 6px 22px rgba(0,0,0,.4)}' +
    '.evos-fab button{font:inherit;color:#fff;cursor:pointer;border:0;background:transparent}' +
    '.evos-fab-go{padding:8px 14px;border-radius:999px;font-size:13px;font-weight:600;background:#2f6bff!important}' +
    '.evos-fab-x{width:28px;height:28px;border-radius:50%;font-size:16px;line-height:1;opacity:.7}' +
    '.evos-fab-hint{margin:0;padding:10px 12px;border-radius:12px;background:#10162a;border:1px solid rgba(255,255,255,.18);color:#dbe3f5;font-size:12.5px;line-height:1.5}' +
    '.evos-fab-hint[hidden]{display:none}'
  document.head.appendChild(css)

  const wrap = document.createElement('div'); wrap.className = 'evos-fab'
  const hint = document.createElement('p'); hint.className = 'evos-fab-hint'; hint.setAttribute('role', 'status'); hint.hidden = true
  const row = document.createElement('div'); row.className = 'evos-fab-row'
  const go = document.createElement('button'); go.type = 'button'; go.className = 'evos-fab-go'; go.textContent = label
  const x = document.createElement('button'); x.type = 'button'; x.className = 'evos-fab-x'; x.setAttribute('aria-label', 'Hide install button'); x.textContent = '×'
  row.append(go, x); wrap.append(hint, row)
  document.body.appendChild(wrap)

  // pwa.js adds .is-available to the button when the browser reports the app is installable.
  // On iPhone it never does, so show it there from the start (tap = how-to hint).
  const ua = navigator.userAgent || ''
  const ios = /iPad|iPhone|iPod/.test(ua) || (ua.includes('Mac') && navigator.maxTouchPoints > 1)
  initInstallButton(go, { alwaysShow: false, hint })
  const sync = () => wrap.classList.toggle('is-on', go.classList.contains('is-available') || ios)
  new MutationObserver(sync).observe(go, { attributes: true, attributeFilter: ['class'] })
  sync()

  x.addEventListener('click', () => { wrap.classList.remove('is-on'); stored(() => localStorage.setItem(KEY, '1')) })
  window.addEventListener('appinstalled', () => wrap.classList.remove('is-on'))
}
