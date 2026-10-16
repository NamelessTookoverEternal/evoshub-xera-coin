// PWA install helper — captures the browser's install prompt once at load so
// any component can offer "Install app" whenever it likes.
let deferred = null;
const listeners = new Set();
const emit = () => listeners.forEach((fn) => fn());

if (typeof window !== "undefined") {
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    deferred = e;
    emit();
  });
  window.addEventListener("appinstalled", () => {
    deferred = null;
    try { localStorage.setItem("evosInstalled", "1"); } catch { /* ignore */ }
    emit();
  });
}

export const subscribeInstall = (fn) => { listeners.add(fn); return () => listeners.delete(fn); };

export const isStandalone = () =>
  typeof window !== "undefined" &&
  (window.matchMedia?.("(display-mode: standalone)").matches || window.navigator.standalone === true);

export const isIOS = () =>
  typeof navigator !== "undefined" &&
  (/iphone|ipad|ipod/i.test(navigator.userAgent) ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1));

export const hasNativePrompt = () => !!deferred;

// Resolves true if the user accepted the native prompt, false if dismissed,
// and null when there is no native prompt (caller should show manual steps).
export async function promptInstall() {
  if (!deferred) return null;
  deferred.prompt();
  const choice = await deferred.userChoice.catch(() => null);
  deferred = null;
  emit();
  return choice?.outcome === "accepted";
}
