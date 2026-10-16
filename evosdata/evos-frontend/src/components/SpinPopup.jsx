import { useEffect, useState } from "react";
import { userApi } from "../lib/userApi";

// Shows a friendly "your free spin is ready" popup at a random moment, at most once per
// browser session, and only to a signed-in customer who has not used today's spin.
const HIDE_ON = new Set(["spin", "login", "register", "success", "store", "forgot-password", "dashxera"]);

export default function SpinPopup({ user, page, setPage }) {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!user?.id || !user?.user_token) return;
    let shown = false;
    try { shown = sessionStorage.getItem("spinPopupShown") === "1"; } catch { /* storage blocked */ }
    if (shown) return;

    const delay = 12000 + Math.random() * 28000;   // 12 to 40 seconds after load
    const t = setTimeout(async () => {
      if (HIDE_ON.has(page)) return;
      const r = await userApi(user, `/spin/status?user_id=${user.id}`);
      if (!r.ok || !(r.data.can_spin || r.data.pending_prize)) return;
      try { sessionStorage.setItem("spinPopupShown", "1"); } catch { /* ignore */ }
      setOpen(true);
    }, delay);
    return () => clearTimeout(t);
    // Re-arm only when the signed-in user changes, not on every page change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.id, user?.user_token]);

  if (!open || HIDE_ON.has(page)) return null;

  return (
    <div style={s.scrim} role="dialog" aria-modal="true" aria-label="Spin to Win" onClick={() => setOpen(false)}>
      <div style={s.card} onClick={(e) => e.stopPropagation()}>
        <button style={s.x} onClick={() => setOpen(false)} aria-label="Close">✕</button>
        <div style={{ fontSize: 56 }}>🎡</div>
        <h3 style={s.h}>Your free spin is ready!</h3>
        <p style={s.p}>Spin the wheel today and win free data, from 1GB up to 10GB.</p>
        <button style={s.go} onClick={() => { setOpen(false); setPage("spin"); }}>Spin now</button>
        <button style={s.later} onClick={() => setOpen(false)}>Maybe later</button>
      </div>
    </div>
  );
}

const s = {
  scrim: { position: "fixed", inset: 0, zIndex: 1000, background: "rgba(5,3,12,0.7)", backdropFilter: "blur(4px)", display: "flex", alignItems: "center", justifyContent: "center", padding: 16 },
  card: { position: "relative", width: "100%", maxWidth: 340, textAlign: "center", background: "rgba(22,17,38,0.98)", border: "1px solid rgba(200,255,62,0.35)", borderRadius: 24, padding: "28px 22px 20px", color: "#e5e7eb", boxShadow: "0 30px 80px rgba(0,0,0,0.6)" },
  x: { position: "absolute", top: 10, right: 12, background: "none", border: "none", color: "#9189b5", fontSize: 18, cursor: "pointer" },
  h: { margin: "6px 0 6px", fontSize: 22, fontWeight: 900, color: "#c8ff3e" },
  p: { margin: "0 0 18px", fontSize: 14, color: "#b4acd0", lineHeight: 1.5 },
  go: { width: "100%", padding: 14, borderRadius: 14, border: "none", background: "linear-gradient(135deg,#c8ff3e,#8fe600)", color: "#000", fontWeight: 900, fontSize: 15, cursor: "pointer" },
  later: { width: "100%", marginTop: 6, background: "none", border: "none", color: "#9189b5", cursor: "pointer", fontSize: 13, padding: 8 },
};
