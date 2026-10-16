import { useEffect, useState } from "react";
import { IS_HUB_MOUNT } from "../lib/basePath";

// Points at the existing XERA page; this component never implements XERA itself.
const XERA_URL = IS_HUB_MOUNT ? "/xera" : "https://evoshub.xyz/xera";
const DISMISS_KEY = "evosXeraPromoDismissedAt";
const REPEAT_MS = 7 * 24 * 3600 * 1000;           // at most once a week
const SAFE_PAGES = ["home", "dashboard"];          // never on buy/pay/auth/agent pages

const TITLE = "XERA Token — Coming Soon";
const BODY = "Something new is evolving. XERA is coming to the EVOS community soon. Stay connected for updates.";

const recentlyDismissed = () => {
  try { return Date.now() - Number(localStorage.getItem(DISMISS_KEY) || 0) < REPEAT_MS; } catch { return false; }
};

function Card() {
  return (
    <div data-no-community style={{
      margin: "12px 16px", padding: "14px 16px", borderRadius: 16,
      background: "linear-gradient(135deg, rgba(124,58,237,.18), rgba(14,165,233,.12))",
      border: "1px solid rgba(167,139,250,.35)", display: "flex", gap: 12,
      alignItems: "center", justifyContent: "space-between", flexWrap: "wrap",
    }}>
      <div style={{ minWidth: 200, flex: 1 }}>
        <div style={{ fontWeight: 700, fontSize: 15 }}>{TITLE}</div>
        <div style={{ fontSize: 13, opacity: 0.8, marginTop: 2 }}>{BODY}</div>
      </div>
      <a href={XERA_URL} style={{
        padding: "8px 14px", borderRadius: 10, background: "#7c3aed", color: "#fff",
        fontWeight: 600, fontSize: 13, textDecoration: "none", whiteSpace: "nowrap",
      }}>Learn about XERA</a>
    </div>
  );
}

function Popup({ page }) {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!SAFE_PAGES.includes(page) || recentlyDismissed()) { setOpen(false); return; }
    // Once per session, a few seconds after arriving, only on safe pages.
    try { if (sessionStorage.getItem("evosXeraPromoShown")) return; } catch { /* ignore */ }
    const t = setTimeout(() => {
      try { sessionStorage.setItem("evosXeraPromoShown", "1"); } catch { /* ignore */ }
      setOpen(true);
    }, 8000);
    return () => clearTimeout(t);
  }, [page]);

  // Leaving a safe page (e.g. to start a purchase) closes it immediately.
  useEffect(() => { if (!SAFE_PAGES.includes(page)) setOpen(false); }, [page]);

  if (!open) return null;
  const dismiss = () => {
    try { localStorage.setItem(DISMISS_KEY, String(Date.now())); } catch { /* ignore */ }
    setOpen(false);
  };
  return (
    <div data-no-community role="dialog" aria-label={TITLE} style={{
      position: "fixed", right: 16, bottom: 96, zIndex: 9000, maxWidth: 320,
      padding: 16, borderRadius: 16, background: "#14102a", color: "#fff",
      border: "1px solid rgba(167,139,250,.45)", boxShadow: "0 10px 30px rgba(0,0,0,.45)",
    }}>
      <div style={{ fontWeight: 700 }}>{TITLE}</div>
      <div style={{ fontSize: 13, opacity: 0.85, margin: "6px 0 12px" }}>{BODY}</div>
      <div style={{ display: "flex", gap: 8 }}>
        <a href={XERA_URL} onClick={dismiss} style={{ flex: 1, textAlign: "center", padding: "8px 0", borderRadius: 10, background: "#7c3aed", color: "#fff", fontWeight: 600, fontSize: 13, textDecoration: "none" }}>Learn more</a>
        <button onClick={dismiss} aria-label="Dismiss XERA announcement" style={{ padding: "8px 12px", borderRadius: 10, background: "transparent", color: "#fff", border: "1px solid rgba(255,255,255,.25)", fontSize: 13, cursor: "pointer" }}>Not now</button>
      </div>
    </div>
  );
}

export default { Card, Popup };
