/**
 * Agent Sign In — EVOS Business Hub
 *
 * Calls the EvosHub backend's password-based admin login
 * (POST /api/admin/login), which validates against the same
 * public.users credentials used across EVOSDATA/EVOSGPT, and only
 * succeeds if the account also has an active admin_agents row.
 *
 * On success, stores the returned session token and redirects to the
 * agent dashboard. The token is re-validated live by the backend on every
 * /api/admin/me call — it carries no authority by itself.
 */

const API_BASE = "https://evoshub-xera-coin.onrender.com";
const DASHBOARD_URL = "admin-website-chat.html";
const TOKEN_STORAGE_KEY = "evoshub_admin_token";

const form = document.getElementById("admin-login-form");
const emailInput = document.getElementById("al-email");
const passwordInput = document.getElementById("al-password");
const errorEl = document.getElementById("al-error");
const submitBtn = document.getElementById("al-submit");

function showError(message) {
  errorEl.textContent = message;
  errorEl.style.display = "block";
}

function hideError() {
  errorEl.style.display = "none";
  errorEl.textContent = "";
}

function setLoading(isLoading) {
  submitBtn.disabled = isLoading;
  submitBtn.textContent = isLoading ? "Signing in…" : "Sign in";
}

// If a still-valid session already exists, skip the login form entirely.
(async function redirectIfAlreadySignedIn() {
  const existingToken = sessionStorage.getItem(TOKEN_STORAGE_KEY);
  if (!existingToken) return;

  try {
    const res = await fetch(`${API_BASE}/api/admin/me`, {
      headers: { Authorization: `Bearer ${existingToken}` },
    });
    if (res.ok) {
      window.location.href = DASHBOARD_URL;
    } else {
      sessionStorage.removeItem(TOKEN_STORAGE_KEY);
    }
  } catch {
    // Network error on this background check shouldn't block the login
    // form from rendering — just leave the stale token in place; the
    // next real login attempt will overwrite it.
  }
})();

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  hideError();

  const identifier = emailInput.value.trim();
  const password = passwordInput.value;

  if (!identifier || !password) {
    showError("Enter your email and password.");
    return;
  }

  setLoading(true);

  let response;
  try {
    response = await fetch(`${API_BASE}/api/admin/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ identifier, password }),
    });
  } catch {
    setLoading(false);
    showError("Couldn't reach the server. Check your connection and try again.");
    return;
  }

  // 429 = brute-force lockout, returned with a plain-text detail message
  // rather than the {status: ...} shape the other cases use.
  if (response.status === 429) {
    setLoading(false);
    let detail = "Too many attempts. Please wait and try again.";
    try {
      const body = await response.json();
      if (body.detail) detail = body.detail;
    } catch {
      // fall back to the default message above
    }
    showError(detail);
    return;
  }

  let data;
  try {
    data = await response.json();
  } catch {
    setLoading(false);
    showError("Unexpected response from the server. Please try again.");
    return;
  }

  setLoading(false);

  if (data.status === "ok" && data.token) {
    // sessionStorage, not localStorage — the session clears when the tab
    // closes rather than persisting indefinitely on a shared/public
    // machine. Swap to localStorage only if "remember me" is a
    // requirement, and add an explicit opt-in checkbox for it.
    sessionStorage.setItem(TOKEN_STORAGE_KEY, data.token);
    window.location.href = DASHBOARD_URL;
    return;
  }

  if (data.status === "not_authorized") {
    showError("This account doesn't have admin access.");
    return;
  }

  // Covers "invalid_credentials" and any unrecognized status — deliberately
  // generic, matching the backend's own refusal to distinguish "wrong
  // password" from "unknown account".
  showError("Incorrect email or password.");
});
