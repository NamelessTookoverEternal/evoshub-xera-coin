// Bundles Ghana proxy for the EVOS Data service (moved here from the standalone
// evosdata.xyz site so the Hub deployment has no dependency on it).
//
// Called server-to-server by the Hub backend (services/evosdata/core.py ->
// call_bundles_ghana). Set on THIS Netlify site: BUNDLES_GHANA_API_KEY,
// BUNDLES_GHANA_API_SECRET and (recommended) BUNDLES_PROXY_SECRET, with the same
// BUNDLES_PROXY_SECRET value on the Hub backend. When a proxy secret is configured,
// requests without it are rejected, so this is no longer an open relay for the
// provider credentials.
import { timingSafeEqual } from "node:crypto";

const json = (statusCode, obj) => ({ statusCode, body: JSON.stringify(obj) });

function secretOk(given, expected) {
  const a = Buffer.from(String(given || ""));
  const b = Buffer.from(String(expected));
  return a.length === b.length && timingSafeEqual(a, b);
}

export async function handler(event) {
  try {
    const PROXY_SECRET = process.env.BUNDLES_PROXY_SECRET;
    if (PROXY_SECRET) {
      const given = event.headers?.["x-proxy-secret"] || event.headers?.["X-Proxy-Secret"];
      if (!secretOk(given, PROXY_SECRET)) return json(403, { success: false, error: "Forbidden" });
    }

    const parsed = JSON.parse(event.body || "{}");
    const { method = "GET", body } = parsed;
    const path = parsed.path;
    if (!path || typeof path !== "string") return json(400, { success: false, error: "Missing path" });

    const API_KEY = process.env.BUNDLES_GHANA_API_KEY;
    const API_SECRET = process.env.BUNDLES_GHANA_API_SECRET;
    if (!API_KEY || !API_SECRET) return json(500, { success: false, error: "API credentials not configured" });

    const res = await fetch(`https://fripalconnectgh.com/api/v1${path}`, {
      method,
      headers: {
        "X-API-Key": API_KEY,
        "X-API-Secret": API_SECRET,
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: method === "POST" ? JSON.stringify(body) : undefined,
    });

    const text = await res.text();
    if (!text || text.trim().startsWith("<")) {
      return json(res.status, { success: false, error: `Bundles Ghana returned non-JSON response (status ${res.status})` });
    }
    return { statusCode: res.status, body: text };
  } catch (err) {
    return json(500, { success: false, error: err.message });
  }
}
