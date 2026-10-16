// Bridge between the Hub session and the EVOS Data session.
//
// Inside the Hub (evoshub.xyz/evosdata) both apps share one browser origin, so
// the Hub's session token (localStorage "xera_evos_token") is visible here. We
// never treat that value as proof of identity to the Evosdata API. Instead:
// the backend verifies the Hub token itself (POST /api/evosdata/auth/hub-session)
// and every protected Evosdata endpoint re-verifies it. A local flag/ID alone can
// never authenticate anything.
import { PRIMARY_BASE, HUB_API_BASE } from "../config";
import { IS_HUB_MOUNT } from "./basePath";

export const HUB_TOKEN_KEY = "xera_evos_token";
export const HUB_USER_KEY = "xera_evos_user";

// Keys the Evosdata app owns. We remove exactly these — never localStorage.clear(),
// which on the Hub origin would also destroy the Hub/XERA session and settings.
const EVOSDATA_KEYS = ["user", "email", "username", "user_id", "userToken", "agentToken"];

export function clearEvosdataSession() {
  EVOSDATA_KEYS.forEach((k) => { try { localStorage.removeItem(k); } catch { /* ignore */ } });
  try { sessionStorage.removeItem("agentToken"); } catch { /* ignore */ }
}

export function hubToken() {
  try { return localStorage.getItem(HUB_TOKEN_KEY) || ""; } catch { return ""; }
}

export const hubSignInUrl = (next) =>
  `/xera?next=${encodeURIComponent(next || window.location.pathname + window.location.search)}`;

async function postJson(base, path, body, headers = {}) {
  const res = await fetch(`${base}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
    body: JSON.stringify(body || {}),
  });
  let data = null;
  try { data = await res.json(); } catch { /* non-JSON */ }
  return { ok: res.ok, status: res.status, data };
}

function saveUser(user) {
  const u = { ...user, id: user.id || user.user_id };
  localStorage.setItem("user", JSON.stringify(u));
  localStorage.setItem("email", u.email || "");
  localStorage.setItem("username", u.username || "");
  localStorage.setItem("user_id", u.id);
  if (u.user_token) localStorage.setItem("userToken", u.user_token);
  if (u.agent_token) {
    localStorage.setItem("agentToken", u.agent_token);
    sessionStorage.setItem("agentToken", u.agent_token);
  }
  return u;
}

/**
 * Turns the Hub session into the signed-in EVOS Data account. The Hub token is
 * sent to the (same) backend, which verifies it server-side and reads role /
 * agent status from the database. The token itself is then the user/agent token,
 * so there is one session for the whole ecosystem. Returns the user or null.
 */
export async function ssoFromHub() {
  if (!IS_HUB_MOUNT) return null;
  const token = hubToken();
  if (!token) return null;
  try {
    const r = await postJson(PRIMARY_BASE, "/auth/hub-session", {}, { Authorization: `Bearer ${token}` });
    if (!r.ok || r.data?.status !== "ok") return null;
    return saveUser(r.data.user);
  } catch {
    return null;
  }
}

/**
 * Hub-mount login: the Hub is the only place credentials are checked.
 * Same response shape as the standalone /auth/login so Login.jsx is unchanged.
 */
export async function loginViaHub({ username, password }) {
  const r = await postJson(HUB_API_BASE, "/api/xera/auth/login", { identifier: username, password });
  if (!r.ok || !r.data?.token) return { data: { status: "error" } };
  try {
    localStorage.setItem(HUB_TOKEN_KEY, r.data.token);
    localStorage.setItem(HUB_USER_KEY, JSON.stringify(r.data.user || {}));
  } catch { /* storage unavailable */ }
  const u = await ssoFromHub();
  return u ? { data: { status: "ok", user: u } } : { data: { status: "error" } };
}

/** True if the Hub session is gone but an Evosdata user is still stored here. */
export function hubSessionEnded() {
  if (!IS_HUB_MOUNT) return false;
  try { return !hubToken() && !!localStorage.getItem("user"); } catch { return false; }
}
