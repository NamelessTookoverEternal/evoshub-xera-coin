import { useState, useEffect } from "react";
import { initUpgrade, redeemCoupon, getXeraQuote, getUpgradeMethods } from "../api";
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
  const { info, format, note } = useCurrency();
  const [crypto, setCrypto]   = useState({ enabled: false, usd: {} });   // USDT option, from the server
  const [method, setMethod]   = useState({});                           // { Pro: "paystack" | "crypto" } (user's own choice)
  const [loadingTier, setLoadingTier] = useState(null);
  const [coupon, setCoupon]   = useState("");
  const [couponMsg, setCMsg]  = useState("");
  const [couponOk, setCOk]    = useState(false);
  const [redeeming, setRedeeming] = useState(false);
  const [quotes, setQuotes]   = useState({});   // { Pro: serverQuote, Core: serverQuote } (only when the discount is switched on)
  const [useX, setUseX]       = useState({});   // { Pro: true }
  const [err, setErr]         = useState("");

  useEffect(() => {
    if (!user) return undefined;
    let cancelled = false;
    TIERS.forEach(async (t) => {
      try {
        const { data } = await getXeraQuote(user.id, t.name);
        if (!cancelled && data?.enabled) setQuotes((q) => ({ ...q, [t.name]: data }));
      } catch { /* the quote is optional: the normal price still works */ }
    });
    return () => { cancelled = true; };
  }, [user?.id]);

  useEffect(() => {
    let cancelled = false;
    getUpgradeMethods()
      .then(({ data }) => { if (!cancelled && data?.crypto?.enabled) setCrypto(data.crypto); })
      .catch(() => { /* no crypto option: card / mobile money still works */ });
    return () => { cancelled = true; };
  }, []);

  if (!user) { setPage("login"); return null; }

  // Outside Ghana, USDT is offered first (a Ghana cedi card charge is the awkward option there).
  const abroad = !!(info?.country && info.country !== "GH");
  const methodFor = (tier) => (crypto.enabled ? (method[tier] || (abroad ? "crypto" : "paystack")) : "paystack");
  const awaiting = (() => { try { return !!sessionStorage.getItem("evosgpt_pending_ref"); } catch { return false; } })();

  const upgrade = async (tier) => {
    setErr("");
    try {
      setLoadingTier(tier);
      const pay = methodFor(tier);
      const wantX = pay === "paystack" && !!(useX[tier] && quotes[tier]?.eligible);
      const { data } = await initUpgrade({ user_id: user.id, tier, email: user.email, method: pay, ...(wantX ? { use_xera: true } : {}) });
      if (data.payment_url) {
        // Remember the order: after the customer returns the app asks the server whether it is confirmed.
        if (pay === "crypto" && data.reference) { try { sessionStorage.setItem("evosgpt_pending_ref", data.reference); } catch { /* ignore */ } }
        window.location.href = data.payment_url;
      }
    } catch (e) {
      setErr(e.response?.data?.detail || "Upgrade failed. Please try again.");
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
    <div className="hm" style={{ maxWidth: 860 }}>
      <header className="hm-top">
        <div className="hm-brand"><span className="orb sm" /> <span className="grad-text">EVOSGPT</span></div>
        <button className="btn btn-ghost" style={{ padding: "9px 16px" }} onClick={() => setPage("chat")}>← Chat</button>
      </header>

      <div style={{ textAlign: "center", margin: "10px 0 26px" }}>
        <h1 className="display" style={{ fontSize: "clamp(26px,5vw,38px)", fontWeight: 700, margin: "0 0 8px", letterSpacing: "-0.03em" }}>
          Upgrade your <span className="grad-text">EVOSGPT</span>
        </h1>
        <p style={{ color: "var(--muted)", fontSize: 14.5, margin: 0 }}>Unlimited chats, images, documents and deeper answers.</p>
      </div>

      {awaiting && <div className="glass" role="status" style={{ padding: "12px 16px", borderRadius: 14, marginBottom: 14, fontSize: 13.5, color: "var(--muted)" }}>
        Waiting for your payment to confirm. If you have paid in USDT, your plan switches on by itself within a few minutes. You can stay here or come back later.
      </div>}

      {err && <div className="glass" role="alert" style={{ padding: "12px 16px", borderRadius: 14, color: "#fca5a5", borderColor: "rgba(248,113,113,.35)", marginBottom: 14, fontSize: 13.5 }}>{err}</div>}

      <div className="plans" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(260px,1fr))" }}>
        {TIERS.map((t) => {
          const q = quotes[t.name];
          const pay = methodFor(t.name);
          const usd = crypto.usd?.[t.name];
          const on = pay === "paystack" && !!(useX[t.name] && q?.eligible);
          return (
            <div key={t.name} className="plan glass" style={{ borderColor: `${t.color}55`, background: `linear-gradient(160deg, ${t.color}14, rgba(255,255,255,.03))` }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, fontWeight: 800, fontSize: 20, color: t.color }}>
                <span style={{ fontSize: 24 }}>{t.icon}</span>{t.name}
              </div>
              <div style={{ fontSize: 11.5, color: "var(--dim)", marginTop: 2 }}>{t.model}</div>
              <div className="price" style={{ color: t.color }}>
                {on && <s style={{ fontSize: 16, color: "var(--dim)", marginRight: 8, fontWeight: 500 }}>{format(t.ghs)}</s>}
                {format(on ? q.final_price : t.ghs)}
                <span style={{ fontSize: 13, color: "var(--muted)", fontWeight: 500 }}>{t.period}</span>
              </div>
              <ul>{t.perks.map((p) => <li key={p}>{p}</li>)}</ul>

              {crypto.enabled && (
                <div role="group" aria-label="Payment method" style={{ display: "flex", gap: 8, marginBottom: 14 }}>
                  {[["paystack", "Card / MoMo"], ["crypto", "USDT"]].map(([m, label]) => (
                    <button key={m} type="button" className="btn btn-ghost" aria-pressed={pay === m}
                            onClick={() => setMethod((s) => ({ ...s, [t.name]: m }))}
                            style={{ flex: 1, padding: "9px 10px", fontSize: 13, ...(pay === m ? { borderColor: t.color, color: t.color } : {}) }}>
                      {label}
                    </button>
                  ))}
                </div>
              )}
              {pay === "crypto" && usd > 0 && (
                <p style={{ fontSize: 12.5, color: "var(--muted)", margin: "0 0 14px", lineHeight: 1.45 }}>
                  Pay <b>{usd.toFixed(2)} USDT</b> (BEP-20). Same price for everyone, anywhere. Your plan switches on automatically once the network confirms, usually within a few minutes.
                </p>
              )}

              {pay === "paystack" && q && (q.eligible ? (
                <label style={{ display: "flex", gap: 10, alignItems: "flex-start", cursor: "pointer", padding: "10px 12px", marginBottom: 14, borderRadius: 14, border: "1px solid rgba(251,191,36,.35)", background: "rgba(251,191,36,.07)" }}>
                  <input type="checkbox" checked={!!useX[t.name]} onChange={(e) => setUseX((u) => ({ ...u, [t.name]: e.target.checked }))} style={{ marginTop: 3 }} />
                  <span style={{ fontSize: 13, lineHeight: 1.45 }}>
                    Use <b>{Number(q.xera_amount)} XERA</b> for <b>{format(Number(q.discount_ghs))} off</b>
                    <span style={{ display: "block", color: "var(--muted)", fontSize: 11.5 }}>
                      Promotional discount. Your XERA balance: {Number(q.spendable)}. Complete payment within {Number(q.hold_minutes) || 60} minutes.
                    </span>
                    {q.verified === false && Number(q.xera_if_verified) < Number(q.xera_amount) && (
                      <span style={{ display: "block", color: "var(--muted)", fontSize: 11.5, marginTop: 2 }}>
                        Verify your identity in the XERA app to pay only {Number(q.xera_if_verified)} XERA.
                      </span>
                    )}
                  </span>
                </label>
              ) : (q.message && q.reason !== "disabled" && q.reason !== "no_discount") ? (
                <p style={{ fontSize: 12, color: "var(--muted)", margin: "0 0 14px" }}>🪙 {q.message}</p>
              ) : null)}

              <button className="btn btn-primary" style={{ width: "100%", background: t.color, boxShadow: "none" }}
                      onClick={() => upgrade(t.name)} disabled={loadingTier !== null}>
                {loadingTier === t.name ? "Redirecting…" : pay === "crypto" ? `Pay with USDT →` : `Upgrade to ${t.name} →`}
              </button>
            </div>
          );
        })}
      </div>

      <div className="glass" style={{ borderRadius: 20, padding: 18, marginTop: 18 }}>
        <div style={{ fontWeight: 800, fontSize: 14, marginBottom: 10 }}>🎟️ Have a coupon code?</div>
        <div style={{ display: "flex", gap: 10 }}>
          <input
            style={{ flex: 1, minWidth: 0, padding: "12px 14px", borderRadius: 12, border: "1px solid var(--line)", background: "rgba(0,0,0,.25)", color: "var(--text)", fontSize: 14, outline: "none" }}
            placeholder="Enter coupon code" value={coupon}
            onChange={(e) => setCoupon(e.target.value)} onKeyDown={(e) => e.key === "Enter" && submitCoupon()}
          />
          <button className="btn btn-ghost" onClick={submitCoupon} disabled={redeeming}>{redeeming ? "…" : "Redeem"}</button>
        </div>
        {couponMsg && <div style={{ marginTop: 10, fontSize: 13, color: couponOk ? "#4ade80" : "#f87171" }}>{couponMsg}</div>}
      </div>

      {note && TIERS.some((t) => methodFor(t.name) === "paystack") && <p style={{ color: "var(--dim)", fontSize: 12, textAlign: "center", margin: "16px 0 4px" }}>{note}</p>}
      <p style={{ color: "var(--dim)", fontSize: 12, textAlign: "center", margin: "8px 0" }}>🔒 Card and mobile money secured by Paystack{crypto.enabled ? ". USDT payments processed by NOWPayments." : ""}</p>
    </div>
  );
}
