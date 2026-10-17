import axios from "axios";
import { API_BASE, HUB_TOKEN_KEY } from "../config";

export const TOKEN_KEY = "evosgpt_token";
export const LOGOUT_EVENT = "evosgpt:logout";

const API = axios.create({ baseURL: API_BASE });

export const getToken = () => {
  try { return localStorage.getItem(TOKEN_KEY) || localStorage.getItem(HUB_TOKEN_KEY) || ""; }
  catch { return ""; }
};

// Every request carries the session token (the Hub backend checks it matches the user_id).
// The standalone backend simply ignores the header.
API.interceptors.request.use((cfg) => {
  const t = getToken();
  if (t) cfg.headers.Authorization = `Bearer ${t}`;
  return cfg;
});

// A rejected/expired session sends the person back to login instead of failing silently.
API.interceptors.response.use(
  (r) => r,
  (err) => {
    const s = err.response?.status;
    const detail = String(err.response?.data?.detail || "");
    if ((s === 403 && /sign in again/i.test(detail)) || s === 401) {
      try { window.dispatchEvent(new CustomEvent(LOGOUT_EVENT)); } catch { /* ignore */ }
    }
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
export const verifyUpgrade = (ref) => API.get(`/upgrade/verify/${encodeURIComponent(ref)}`);
export const redeemCoupon = (d)  => API.post("/coupon/redeem", d);
export const getReferral  = (id) => API.get(`/referral/${id}`);
export const getCurrency  = (country) => API.get("/currency", { params: country ? { country } : {} });

export default API;
