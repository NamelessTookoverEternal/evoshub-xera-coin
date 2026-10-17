import { useEffect, useState } from "react";
import { getCurrency } from "../api";
import { IS_HUB_MOUNT } from "../config";

// Default is GHS. If the visitor's country (by IP, so a VPN exit country counts) uses another
// currency, prices are DISPLAYED in it. Billing stays in GHS.
const CACHE_KEY = "evosgpt_currency_v1";
const TTL_MS = 60 * 60 * 1000;
const GHS = { currency: "GHS", rate: 1, converted: false, country: "" };

function readCache() {
  try {
    const c = JSON.parse(sessionStorage.getItem(CACHE_KEY) || "null");
    if (c && Date.now() - c.at < TTL_MS) return c.info;
  } catch { /* ignore */ }
  return null;
}

// The Hub's hosting edge already knows the visitor's country (/api/country); asking it first
// avoids a server-side IP lookup. If it is unavailable the backend looks the IP up itself.
async function edgeCountry() {
  if (!IS_HUB_MOUNT) return "";
  try {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), 2500);
    const res = await fetch("/api/country", { cache: "no-store", signal: ctrl.signal });
    clearTimeout(t);
    if (!res.ok) return "";
    const code = String((await res.json()).country || "").trim().toUpperCase();
    return /^[A-Z]{2}$/.test(code) ? code : "";
  } catch { return ""; }
}

let inflight = null;
export function loadCurrency() {
  const cached = readCache();
  if (cached) return Promise.resolve(cached);
  if (!inflight) {
    inflight = (async () => {
      try {
        const { data } = await getCurrency(await edgeCountry());
        const info = data && data.rate > 0 && data.currency
          ? { currency: data.currency, rate: data.rate, converted: !!data.converted, country: data.country || "" }
          : GHS;
        try { sessionStorage.setItem(CACHE_KEY, JSON.stringify({ at: Date.now(), info })); } catch { /* ignore */ }
        return info;
      } catch {
        return GHS;   // standalone backend without /currency, offline, etc.: stay on cedis
      } finally { inflight = null; }
    })();
  }
  return inflight;
}

export function formatPrice(ghsAmount, info = GHS) {
  if (!info.converted || info.currency === "GHS") return `GH₵${ghsAmount}`;
  try {
    const v = ghsAmount * info.rate;
    return "≈ " + new Intl.NumberFormat(undefined, {
      style: "currency", currency: info.currency,
      maximumFractionDigits: v >= 100 ? 0 : 2,
    }).format(v);
  } catch {
    return `GH₵${ghsAmount}`;
  }
}

export function useCurrency() {
  const [info, setInfo] = useState(readCache() || GHS);
  useEffect(() => {
    let alive = true;
    loadCurrency().then((i) => { if (alive) setInfo(i); });
    return () => { alive = false; };
  }, []);
  return {
    info,
    format: (ghs) => formatPrice(ghs, info),
    note: info.converted
      ? `Shown in ${info.currency} for reference. You are billed in Ghana cedis (GHS); your bank converts at its own rate.`
      : "",
  };
}
