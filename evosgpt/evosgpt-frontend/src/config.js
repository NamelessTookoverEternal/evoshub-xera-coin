// Mount-point + API configuration.
// Hub build (VITE_BASE_PATH=/evosgpt/): talks to the Hub backend at /api/evosgpt, shares the Hub login.
// Standalone build: unchanged behaviour (VITE_API_URL, default the old EVOSGPT backend).
export const IS_HUB_MOUNT = __HUB_MOUNT__;

const HUB_API_BASE = (import.meta.env.VITE_HUB_API_URL || "https://api.evoshub.xyz").replace(/\/$/, "");

export const API_BASE = IS_HUB_MOUNT
  ? `${HUB_API_BASE}/api/evosgpt`
  : (import.meta.env.VITE_API_URL || "https://evosgpt-rebirth.fly.dev");

// Inside the Hub these are same-origin pages (no outside link); standalone keeps the public URLs.
export const EVOSDATA_URL = IS_HUB_MOUNT ? "/evosdata" : "https://evosdata.xyz";
export const HUB_URL      = IS_HUB_MOUNT ? "/home"     : "https://evoshub.xyz";

// The Hub's own session (written by the /xera login screens, read by every Hub-mounted app).
export const HUB_TOKEN_KEY = "xera_evos_token";

// Inside the Hub, ecosystem links (EvosData, XERA, the Hub itself) stay in the same tab so they land on the
// in-Hub app (the Hub's back tab returns here). Standalone keeps opening the public sites in a new tab.
export const XERA_URL = IS_HUB_MOUNT ? "/xera" : "https://evoshub.xyz/xera";
export function openProduct(url) {
  if (IS_HUB_MOUNT) window.location.assign(url);
  else window.open(url, "_blank");
}
