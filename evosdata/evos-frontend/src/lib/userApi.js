import { smartFetch } from "../config";

// Customer-session token, issued at login (see /auth/login -> user.user_token).
// Different from the agent token: it only works on /spin/* and /agent-fee/*.
export const getUserToken = (user) =>
  user?.user_token || localStorage.getItem("userToken") || "";

/**
 * Authenticated call to the API. Always resolves (never throws on HTTP errors):
 *   { ok, status, data, needsLogin }
 * needsLogin is true when this browser has no token yet (a session saved before
 * this feature existed) or the server rejected it, so the page can ask for a fresh sign-in.
 */
export async function userApi(user, path, { method = "GET", body } = {}) {
  const token = getUserToken(user);
  if (!token) return { ok: false, status: 403, data: {}, needsLogin: true };
  try {
    const res = await smartFetch(path, {
      method,
      headers: { "Content-Type": "application/json", "X-User-Token": token },
      body: body ? JSON.stringify(body) : undefined,
    });
    let data = {};
    try { data = await res.json(); } catch { /* empty body */ }
    return { ok: res.ok, status: res.status, data, needsLogin: res.status === 403 };
  } catch {
    return { ok: false, status: 0, data: { detail: "Network problem. Check your connection and try again." }, needsLogin: false };
  }
}

export const errorText = (r, fallback = "Something went wrong. Please try again.") => {
  const d = r?.data?.detail;
  return typeof d === "string" ? d : fallback;
};
