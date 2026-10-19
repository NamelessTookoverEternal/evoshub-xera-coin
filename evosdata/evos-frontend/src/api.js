import axios from "axios";
import { PRIMARY_BASE, FALLBACK_BASE } from "./config";
import { IS_HUB_MOUNT } from "./lib/basePath";
import { loginViaHub } from "./lib/hubSession";

// =========================
// BASE CONFIG (primary + fallback)
// =========================
const baseHeaders = {
  "Content-Type": "application/json",
  Accept: "application/json",
};

const primaryClient = axios.create({
  baseURL: PRIMARY_BASE,
  timeout: 60000,
  headers: baseHeaders,
});

const fallbackClient = axios.create({
  baseURL: FALLBACK_BASE,
  timeout: 60000,
  headers: baseHeaders,
});

// =========================
// DEBUG INTERCEPTOR (both clients)
// =========================
const logError = (label) => (err) => {
  console.error(`🔥 API ERROR [${label}]:`, {
    url: err.config?.url,
    status: err.response?.status,
    data: err.response?.data,
    message: err.message,
  });
  return Promise.reject(err);
};
primaryClient.interceptors.response.use((res) => res, logError("primary"));
fallbackClient.interceptors.response.use((res) => res, logError("fallback"));

// =========================
// ORDER IDENTITY
// =========================
// A user_id in the body is only a claim: the backend attaches the order to the
// account only when a valid X-User-Token proves it. The token is sent only when
// it belongs to the same user_id, so a stale token can never cause a 403 for a
// customer who is buying as a guest.
const IDENTITY_ROUTES = ["/orders/create", "/checkers/create", "/afa/create"];
const attachUserToken = (config) => {
  try {
    const url = config.url || "";
    const body = config.data;
    if (IDENTITY_ROUTES.some((r) => url.endsWith(r)) && body && body.user_id) {
      const token = localStorage.getItem("userToken") || "";
      if (token && String(localStorage.getItem("user_id")) === String(body.user_id)) {
        config.headers = config.headers || {};
        config.headers["X-User-Token"] = token;
      }
    }
  } catch { /* storage unavailable: proceed as guest */ }
  return config;
};
primaryClient.interceptors.request.use(attachUserToken);
fallbackClient.interceptors.request.use(attachUserToken);

// =========================
// FAILOVER WRAPPER
// =========================
// Only retries on fallback if the primary never answered at all
// (timeout / DNS / connection refused). A real HTTP error response
// (4xx/5xx) from the primary is returned as-is, not retried.
async function request(method, url, data, config = {}) {
  try {
    return await primaryClient[method](url, ...(data !== undefined ? [data, config] : [config]));
  } catch (err) {
    if (err.response) throw err; // primary answered, just with an error — trust it
    console.warn(`⚠️ ${PRIMARY_BASE} unreachable, retrying via ${FALLBACK_BASE}`, err.message);
    return fallbackClient[method](url, ...(data !== undefined ? [data, config] : [config]));
  }
}

// =========================
// AUTH
// =========================
export const registerUser = (data) =>
  request("post", "/auth/register", {
    username: data.username?.trim().toLowerCase(),
    full_name: data.full_name,
    email: data.email?.trim().toLowerCase(),
    phone: data.phone,
    password: data.password,
    referred_by: data.referred_by || null,
  });

export const loginUser = (data) =>
  IS_HUB_MOUNT ? loginViaHub({ username: data.username?.trim().toLowerCase(), password: data.password }) :
  request("post", "/auth/login", {
    username: data.username?.trim().toLowerCase(),
    password: data.password,
  });

// =========================
// PRICES
// =========================
export const getPrices = () => request("get", "/prices");

// =========================
// ORDERS
// =========================
export const createOrder = (data) => request("post", "/orders/create", data);

export const getOrders = (user_id) =>
  request("get", `/orders/me?user_id=${user_id}`, undefined, {
    headers: { "X-User-Token": localStorage.getItem("userToken") || "" },
  });

// =========================
// VERIFY NUMBER (MTN pre-check, informational only)
// Backend's own DataMart call can take up to ~9s worst case (see main.py),
// so this needs real margin above that or we time out on the frontend
// while the backend is still legitimately waiting on a real answer.
// =========================
export const verifyNumber = (phoneNumber, network, timeout = 12000) =>
  request("post", "/verify-number", { phoneNumber, network }, { timeout });

// =========================
// RESULT CHECKERS (WAEC / BECE)
// =========================
export const getCheckerProducts = () => request("get", "/checkers/products");

export const createCheckerOrder = (data) =>
  request("post", "/checkers/create", {
    user_id: data.user_id || null,
    checker_type: data.checker_type,
    phone_number: data.phone_number,
    quantity: data.quantity || 1,
    email: data.email || undefined,
  });

export const getCheckerStatus = (reference) =>
  request("get", `/checkers/status/${reference}`);

export const trackCheckers = (phone) =>
  request("get", `/checkers/track?phone=${encodeURIComponent(phone)}`);

// =========================
// AFA REGISTRATION (MTN)
// =========================
export const getAfaInfo = () => request("get", "/afa/info");

export const createAfaRegistration = (data) => request("post", "/afa/create", data);

export const getAfaStatus = (reference) => request("get", `/afa/status/${reference}`);

export const trackAfa = (phone) => request("get", `/afa/track?phone=${encodeURIComponent(phone)}`);

export default primaryClient;
