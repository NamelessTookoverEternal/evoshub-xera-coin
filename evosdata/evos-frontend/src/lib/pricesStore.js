// Instant bundle prices for the shop.
//
// Order of truth on page open:
//   1. last copy saved in this browser (localStorage)   -> shown immediately
//   2. snapshot baked into the build (src/data)           -> first-ever visit, no network wait
//   3. fresh copy from the backend /prices (which itself is served from a server-side
//      cache refreshed every 2h)                           -> swapped in silently if anything changed
//
// The charged price is always decided by the server when the order is created, so a stale
// display price can never change what a customer pays.
import { getPrices } from "../api";
import snapshot from "../data/prices.snapshot.json";

const KEY = "evos_prices_v1";
const listeners = new Set();

const clean = (d) => (Array.isArray(d) ? d : []);

function readLocal() {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) || "null");
    if (raw && Array.isArray(raw.data) && raw.data.length) return raw;
  } catch { /* storage blocked or corrupt: ignore */ }
  return null;
}

function writeLocal(state) {
  try { localStorage.setItem(KEY, JSON.stringify(state)); } catch { /* ignore */ }
}

let state = readLocal() || { data: clean(snapshot?.data), version: snapshot?.version || "" };
let inflight = null;

export const getCachedPrices = () => state.data;

export function subscribePrices(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

// Fetch fresh prices in the background; notify subscribers only if something changed.
export function refreshPrices() {
  if (inflight) return inflight;
  inflight = getPrices()
    .then((res) => {
      const data = clean(res.data?.data);
      const version = res.data?.version || "";
      if (!data.length) return; // never wipe a good list with an empty answer
      if (version && version === state.version) return; // nothing changed
      state = { data, version };
      writeLocal(state);
      listeners.forEach((fn) => fn(state.data));
    })
    .catch(() => { /* offline or backend slow: keep showing what we have */ })
    .finally(() => { inflight = null; });
  return inflight;
}
