// EVOSHUB — shared helpers for the public (no-login) XERA information
// pages: landing, stats, tokenomics, and the ecosystem directory.
//
// These pages never send an Authorization header and never touch
// localStorage/sessionStorage tokens — they only call the /api/xera/public/*
// and /api/xera/ecosystem routes, which are deliberately unauthenticated
// and return aggregate/public data only.

export const XERA_API = window.XERA_API_BASE || ((location.hostname === 'localhost' || location.hostname === '127.0.0.1') ? 'http://localhost:8000' : 'https://api.evoshub.xyz');

export function fmtXera(n) {
  return Number(n || 0).toLocaleString('en-US', { maximumFractionDigits: 2 });
}

export async function fetchPublicJson(path) {
  const res = await fetch(XERA_API + path);
  if (!res.ok) throw new Error(`Request failed (${res.status})`);
  return res.json();
}

// A signed-in visitor still has their session token in localStorage from
// the app at /xera/dashboard — this only ever reads that key to decide
// whether to show a "Continue to your dashboard" shortcut; it never sends
// the token anywhere from a public page.
export function hasLocalXeraSession() {
  try {
    return !!localStorage.getItem('xera_evos_token');
  } catch {
    return false;
  }
}
