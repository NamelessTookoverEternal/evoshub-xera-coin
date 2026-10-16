import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import { stripBase, IS_HUB_MOUNT } from './lib/basePath'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

// Dismiss the launch splash (defined in index.html). On an agent store link it
// stays up until StorePage reports the store has loaded (capped so a slow API
// can never trap a customer), so they never see a half-loaded page.
(function hideSplash() {
  const el = document.getElementById("splash");
  if (!el) return;
  const isStore = stripBase(window.location.pathname).startsWith("/store/");
  const MIN_MS = isStore ? 900 : 1400;
  const MAX_MS = 6000;
  const started = window.__splashStart || Date.now();
  let done = false;

  const finish = () => {
    if (done) return;
    done = true;
    el.classList.add("out");
    try { sessionStorage.setItem("evos_splash", "1"); } catch { /* private mode */ }
    setTimeout(() => el.remove(), 500);
  };
  const tryFinish = () => {
    const ready = !isStore || window.__evosReady;
    const elapsed = Date.now() - started;
    if (ready && elapsed >= MIN_MS) return finish();
    if (elapsed >= MAX_MS) return finish();
    setTimeout(tryFinish, 100);
  };
  tryFinish();
})();

// Make the site installable + fast on repeat visits (production only)
// Inside the Hub the Hub's own service worker owns the origin; registering a second
// root-scoped one here would fight it, so only the standalone build registers.
if (!IS_HUB_MOUNT && "serviceWorker" in navigator && import.meta.env.PROD) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  });
}
