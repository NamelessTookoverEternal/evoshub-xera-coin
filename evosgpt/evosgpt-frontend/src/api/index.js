import axios from "axios";
import { API_BASE, HUB_TOKEN_KEY, IS_HUB_MOUNT } from "../config";

export const TOKEN_KEY = "evosgpt_token";
export const LOGOUT_EVENT = "evosgpt:logout";

const API = axios.create({ baseURL: API_BASE });

const readKey = (k) => { try { return localStorage.getItem(k) || ""; } catch { return ""; } };

// Inside the Hub the LIVE Hub session comes first. Our own saved copy (evosgpt_token) is only a fallback:
// it is written once when the person opens EVOSGPT and goes stale after the Hub token (24h) is replaced.
export const getToken = () => (IS_HUB_MOUNT
  ? readKey(HUB_TOKEN_KEY) || readKey(TOKEN_KEY)
  : readKey(TOKEN_KEY) || readKey(HUB_TOKEN_KEY));

// Every request carries the session token (the Hub backend checks it matches the user_id).
// The standalone backend simply ignores the header.
API.interceptors.request.use((cfg) => {
  const t = cfg._token || getToken();
  if (t) cfg.headers.Authorization = `Bearer ${t}`;
  return cfg;
});

// A rejected/expired session: first retry ONCE with the other saved token (the Hub may have a newer one than the
// one that was sent); only when that also fails is the person sent back to login.
API.interceptors.response.use(
  (r) => r,
  (err) => {
    const s = err.response?.status;
    const detail = String(err.response?.data?.detail || "");
    const rejected = (s === 403 && /sign in again/i.test(detail)) || s === 401;
    if (!rejected) return Promise.reject(err);
    const cfg = err.config;
    if (cfg && !cfg._retried) {
      const sent = String(cfg.headers?.Authorization || "").replace(/^Bearer\s+/i, "");
      const other = [readKey(HUB_TOKEN_KEY), readKey(TOKEN_KEY)].find((t) => t && t !== sent);
      if (other) {
        cfg._retried = true;
        cfg._token = other;
        return API.request(cfg);
      }
    }
    try { window.dispatchEvent(new CustomEvent(LOGOUT_EVENT)); } catch { /* ignore */ }
    return Promise.reject(err);
  }
);

export const registerUser = (d)  => API.post("/auth/register", d);
export const loginUser    = (d)  => API.post("/auth/login", d);
export const hubSession   = (token) => axios.post(`${API_BASE}/auth/hub-session`, {}, { headers: { Authorization: `Bearer ${token}` } });
export const sendMessage  = (d)  => API.post("/chat", d);
export const generateImage = (d) => API.post("/image/generate", d);
export const editImage     = (d) => API.post("/image/edit", d);
export const generateDocument = (d) => API.post("/document/generate", d);
export const getMemory    = (id) => API.get(`/memory/${id}`);
export const clearMemory  = (id) => API.delete(`/memory/${id}`);
export const getUser      = (id) => API.get(`/user/${id}`);
export const initUpgrade  = (d)  => API.post("/upgrade/init", d);
export const getUpgradeMethods = () => API.get("/upgrade/methods");
export const getXeraQuote = (userId, tier) => API.get("/xera-discount/quote", { params: { user_id: userId, tier } });
export const verifyUpgrade = (ref) => API.get(`/upgrade/verify/${encodeURIComponent(ref)}`);
export const redeemCoupon = (d)  => API.post("/coupon/redeem", d);
export const getReferral  = (id) => API.get(`/referral/${id}`);
export const getCurrency  = (country) => API.get("/currency", { params: country ? { country } : {} });

export default API;
