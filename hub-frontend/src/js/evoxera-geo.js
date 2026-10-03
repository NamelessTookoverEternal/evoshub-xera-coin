// EVOXERA — country lookup for UX gating (e.g. EvosData is Ghana-only).
//
// This is a *convenience* signal, not access control: it reads the country the
// hosting edge derived from the request IP (/api/country), never browser
// geolocation, so there is no permission prompt. Anyone can bypass it with a
// VPN, so real enforcement must happen server-side in the EvosData backend.

const CACHE_KEY = 'evx-country'
const TIMEOUT_MS = 2500

/** Resolves to an upper-case ISO country code like "GH", or null if unknown. */
export async function detectCountry() {
  try {
    const cached = sessionStorage.getItem(CACHE_KEY)
    if (cached) return cached
  } catch { /* storage unavailable */ }

  const ctrl = new AbortController()
  const t = window.setTimeout(() => ctrl.abort(), TIMEOUT_MS)
  try {
    const res = await fetch('/api/country', { cache: 'no-store', signal: ctrl.signal })
    if (!res.ok) return null
    const data = await res.json()
    const code = typeof data.country === 'string' ? data.country.trim().toUpperCase() : ''
    if (!/^[A-Z]{2}$/.test(code)) return null
    try { sessionStorage.setItem(CACHE_KEY, code) } catch { /* ignore */ }
    return code
  } catch {
    return null
  } finally {
    window.clearTimeout(t)
  }
}
