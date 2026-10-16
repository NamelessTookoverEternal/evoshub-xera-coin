import axios from "axios";

// =========================
// SINGLE SOURCE OF TRUTH
// =========================
// Change hosts here — every page/component picks it up automatically.
// Overridable at build time (Vite) so no environment URL is hard-wired into a build.
// Defaults keep the standalone deployment working exactly as before.
const env = import.meta.env;

// Hub-mounted build (evoshub.xyz/evosdata): the EVOS Hub backend IS the Evosdata
// API (mounted at /api/evosdata). No standalone Evosdata host is contacted.
export const HUB_API_BASE = (env.VITE_HUB_API_URL || "https://api.evoshub.xyz").replace(/\/$/, "");
const HUB_EVOSDATA_API = `${HUB_API_BASE}/api/evosdata`;

// Standalone build (evosdata.xyz): unchanged defaults, overridable at build time.
export const PRIMARY_BASE = __HUB_MOUNT__
  ? HUB_EVOSDATA_API
  : (env.VITE_EVOSDATA_API_URL || "https://evos-data-services.fly.dev");
export const FALLBACK_BASE = __HUB_MOUNT__
  ? HUB_EVOSDATA_API   // single backend: nothing else to fail over to
  : (env.VITE_EVOSDATA_FALLBACK_API_URL || "https://api.evosdata.xyz");

// Order-sync endpoint used by the tracking page.
export const BUSINESS_HUB_API_BASE = __HUB_MOUNT__ ? HUB_EVOSDATA_API : "https://evos-business-hub.onrender.com";

const TIMEOUT_MS = 8000; // how long we wait on primary before trying fallback

// =========================
// fetch()-based failover
// =========================
async function fetchWithTimeout(url, options, timeoutMs) {
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    clearTimeout(id);
  }
}

/**
 * Drop-in replacement for fetch(`${API_BASE}${path}`, options).
 * Tries PRIMARY_BASE first. Only falls back to FALLBACK_BASE if the
 * primary never responds at all (timeout / DNS / connection error) —
 * a normal HTTP error response (4xx/5xx) is returned as-is and does NOT
 * trigger a retry, since re-sending a POST against a second host could
 * double-fire something like a withdrawal or a deposit.
 */
export async function smartFetch(path, options = {}, timeoutMs = TIMEOUT_MS) {
  try {
    return await fetchWithTimeout(`${PRIMARY_BASE}${path}`, options, timeoutMs);
  } catch (err) {
    console.warn(`⚠️ ${PRIMARY_BASE} unreachable, falling back to ${FALLBACK_BASE}`, err?.message || err);
    return fetchWithTimeout(`${FALLBACK_BASE}${path}`, options, timeoutMs);
  }
}

// =========================
// axios-based failover (for pages still using axios directly)
// =========================
export async function smartAxios(method, path, data, options = {}) {
  const cfg = { timeout: TIMEOUT_MS, ...options };
  try {
    return await axios({ method, url: `${PRIMARY_BASE}${path}`, data, ...cfg });
  } catch (err) {
    // err.response means the server answered (e.g. 400/401/500) — trust that, don't retry.
    if (err.response) throw err;
    console.warn(`⚠️ ${PRIMARY_BASE} unreachable, falling back to ${FALLBACK_BASE}`, err?.message || err);
    return axios({ method, url: `${FALLBACK_BASE}${path}`, data, ...cfg });
  }
}

export const smartGet = (path, options) => smartAxios("get", path, undefined, options);
export const smartPost = (path, data, options) => smartAxios("post", path, data, options);
