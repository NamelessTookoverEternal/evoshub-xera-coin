import { useState } from "react";
import { initUpgrade, redeemCoupon } from "../api";
import { useCurrency } from "../lib/currency";

const TIERS = [
  {
    name: "Pro", icon: "⚡", ghs: 20, period: "/month", color: "#38bdf8",
    model: "GPT-4o",
    perks: ["Unlimited chats", "100 message memory", "Code & dev expert mode", "Design & flyer briefs", "Letter & document writing", "Evolving long-term memory"],
  },
  {
    name: "Core", icon: "🔥", ghs: 70, period: "/month", color: "#a78bfa",
    model: "GPT-4o (Max Power)",
    perks: ["Everything in Pro", "300 message memory", "Deepest, most thorough responses", "Priority processing", "Full persona calibration", "Best for power users"],
  },
];

export default function Upgrade({ setPage, user }) {
  const { format, note } = useCurrency();
  const [loadingTier, setLoadingTier] = useState(null);
  const [coupon, setCoupon]   = useState("");
  const [couponMsg, setCMsg]  = useState("");
  const [couponOk, setCOk]    = useState(false);
  const [redeeming, setRedeeming] = useState(false);

  if (!user) { setPage("login"); return null; }

  const upgrade = async (tier) => {
    try {
      setLoadingTier(tier);
      const { data } = await initUpgrade({ user_id: user.id, tier, email: user.email });
      if (data.payment_url) window.location.href = data.payment_url;
    } catch (e) {
      alert(e.response?.data?.detail || "Upgrade failed. Please try again.");
    } finally { setLoadingTier(null); }
  };

  const submitCoupon = async () => {
    if (!coupon.trim()) return;
    setCMsg(""); setCOk(false);
    try {
      setRedeeming(true);
      const { data } = await redeemCoupon({ user_id: user.id, code: coupon.trim() });
      setCMsg(data.message);
      if (data.status === "ok") {
        setCOk(true);
        setTimeout(() => setPage("chat"), 1500);
      }
    } catch (e) {
      setCMsg("Failed to redeem coupon.");
    } finally { setRedeeming(false); }
  };

  return (
    <div style={S.page}>
      <header style={S.header}>
        <div onClick={() => setPage("chat")} style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
          <span style={{ fontSize: 22 }}>⚡</span>
          <span style={S.brand}>EVOSGPT</span>
        </div>
        <button style={S.ghostBtn} onClick={() => setPage("chat")}>← Back to Chat</button>
      </header>

      <main style={S.main}>
        <div style={{ textAlign: "center", marginBottom: 40 }}>
          <h1 style={S.title}>Upgrade Your EVOSGPT</h1>
          <p style={S.sub}>Unlock unlimited chats and expert-level AI responses.</p>
        </div>

        <div style={S.grid}>
          {TIERS.map(t => (
            <div key={t.name} style={{ ...S.card, border: `1px solid ${t.color}33`, background: `${t.color}10` }}>
              <div style={{ fontSize: 34, marginBottom: 8 }}>{t.icon}</div>
              <div style={{ fontSize: 22, fontWeight: 900, color: t.color }}>{t.name}</div>
              <div style={{ fontSize: 12, color: "#475569", marginBottom: 14 }}>{t.model}</div>
              <div style={{ marginBottom: 22 }}>
                <span style={{ fontSize: 28, fontWeight: 900, color: t.color }}>{format(t.ghs)}</span>
                <span style={{ fontSize: 13, color: "#64748b" }}>{t.period}</span>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 9, marginBottom: 26 }}>
                {t.perks.map(p => (
                  <div key={p} style={{ fontSize: 13, color: "#94a3b8", display: "flex", gap: 8 }}>
                    <span style={{ color: t.color, fontWeight: 700 }}>✓</span> {p}
                  </div>
                ))}
              </div>
              <button
                style={{ ...S.upgradeBtn, background: t.color, opacity: loadingTier === t.name ? 0.6 : 1 }}
                onClick={() => upgrade(t.name)}
                disabled={loadingTier !== null}
              >
                {loadingTier === t.name ? "Redirecting..." : `Upgrade to ${t.name} →`}
              </button>
            </div>
          ))}
        </div>

        {/* COUPON */}
        <div style={S.couponBox}>
          <div style={{ fontWeight: 800, fontSize: 14, color: "#f1f5f9", marginBottom: 10 }}>🎟️ Have a coupon code?</div>
          <div style={{ display: "flex", gap: 10 }}>
            <input
              style={S.couponInput}
              placeholder="Enter coupon code"
              value={coupon}
              onChange={e => setCoupon(e.target.value)}
              onKeyDown={e => e.key === "Enter" && submitCoupon()}
            />
            <button style={S.couponBtn} onClick={submitCoupon} disabled={redeeming}>
              {redeeming ? "..." : "Redeem"}
            </button>
          </div>
          {couponMsg && (
            <div style={{ marginTop: 10, fontSize: 13, color: couponOk ? "#4ade80" : "#f87171" }}>{couponMsg}</div>
          )}
        </div>

        {note && <p style={{ ...S.secureNote, color: "#64748b", marginBottom: 8 }}>{note}</p>}
        <p style={S.secureNote}>🔒 Payments secured by Paystack</p>
      </main>
    </div>
  );
}

const S = {
  page:   { minHeight: "100vh", background: "#070d1a", color: "#e2e8f0" },
  header: { display: "flex", justifyContent: "space-between", alignItems: "center", padding: "16px 20px", borderBottom: "1px solid rgba(255,255,255,0.06)" },
  brand:  { fontWeight: 900, fontSize: 17, color: "#38bdf8" },
  ghostBtn: { padding: "9px 16px", borderRadius: 10, border: "1px solid rgba(255,255,255,0.12)", background: "transparent", color: "#e2e8f0", fontWeight: 700, fontSize: 13, cursor: "pointer" },
  main:   { maxWidth: 760, margin: "0 auto", padding: "48px 20px 60px" },
  title:  { fontSize: "clamp(26px,4vw,38px)", fontWeight: 900, color: "#f1f5f9", marginBottom: 10 },
  sub:    { color: "#94a3b8", fontSize: 15 },
  grid:   { display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(280px,1fr))", gap: 20, marginBottom: 36 },
  card:   { borderRadius: 22, padding: "28px 24px" },
  upgradeBtn: { width: "100%", padding: 13, borderRadius: 12, border: "none", color: "#000", fontWeight: 900, fontSize: 14, cursor: "pointer" },
  couponBox: { background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.07)", borderRadius: 18, padding: "20px", marginBottom: 24 },
  couponInput: { flex: 1, padding: "11px 14px", borderRadius: 10, border: "1px solid rgba(255,255,255,0.1)", background: "rgba(0,0,0,0.3)", color: "#f1f5f9", fontSize: 14, outline: "none" },
  couponBtn: { padding: "11px 20px", borderRadius: 10, border: "none", background: "#a78bfa", color: "#000", fontWeight: 800, fontSize: 13, cursor: "pointer" },
  secureNote: { textAlign: "center", color: "#334155", fontSize: 13 },
};
