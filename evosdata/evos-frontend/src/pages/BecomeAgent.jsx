import { useEffect, useRef, useState } from "react";
import { userApi, errorText } from "../lib/userApi";

const FEE = 50, WAS = 100;
const PERKS = [
  ["🏪", "Your own store link", "Share one link where customers buy from you."],
  ["💰", "Set your own prices", "Add your markup on every bundle and keep the profit."],
  ["📡", "Base-price data", "Buy data for customers from your wallet at agent prices."],
  ["💳", "Withdraw your earnings", "Send your profit to your MoMo."],
];

const mmss = (iso, now) => {
  const ms = Math.max(0, new Date(iso).getTime() - now);
  return `${Math.floor(ms / 60000)}:${String(Math.floor((ms % 60000) / 1000)).padStart(2, "0")}`;
};

export default function BecomeAgent({ user, setUser, setPage }) {
  const [state, setState] = useState("loading");   // loading | none | pending | paid | activated | failed | expired
  const [info, setInfo] = useState(null);          // status payload
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [now, setNow] = useState(Date.now());
  const upgraded = useRef(false);

  useEffect(() => { if (!user) setPage("login"); }, [user, setPage]);
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t); }, []);

  const params = new URLSearchParams(window.location.search);
  const reference = params.get("reference") || undefined;

  const check = async () => {
    const q = `/agent-fee/status?user_id=${user.id}` + (reference ? `&reference=${encodeURIComponent(reference)}` : "");
    const r = await userApi(user, q);
    if (r.needsLogin) { setError("Please sign out and sign in again to continue."); setState("none"); return; }
    if (!r.ok) { setError(errorText(r, "Could not check your payment.")); return; }
    setInfo(r.data);
    setState(r.data.state || "none");
    if (r.data.is_agent && r.data.agent_token && !upgraded.current) {
      upgraded.current = true;
      // The saved login predates the upgrade: refresh it so the Agent Hub opens without signing in again.
      const nu = { ...user, role: "agent", agent_status: "approved", agent_token: r.data.agent_token };
      try {
        localStorage.setItem("user", JSON.stringify(nu));
        localStorage.setItem("agentToken", nu.agent_token);
        sessionStorage.setItem("agentToken", nu.agent_token);
      } catch { /* storage blocked */ }
      setUser(nu);
    }
  };

  useEffect(() => { if (user?.id) check(); /* eslint-disable-next-line */ }, [user?.id]);
  // While a payment is waiting, look again every 30 seconds (the server activates it by itself).
  useEffect(() => {
    if (state !== "paid" && state !== "pending") return;
    const t = setInterval(check, 30000);
    return () => clearInterval(t);
    // eslint-disable-next-line
  }, [state]);

  const pay = async () => {
    setBusy(true); setError("");
    const r = await userApi(user, "/agent-fee/initiate", { method: "POST", body: { user_id: user.id } });
    setBusy(false);
    if (r.needsLogin) { setError("Please sign out and sign in again to continue."); return; }
    if (!r.ok) { setError(errorText(r)); return; }
    if (r.data.status === "created" && r.data.payment_url) { window.location.href = r.data.payment_url; return; }
    if (r.data.status === "already_agent" || r.data.status === "waiting") { check(); return; }
    setError("Could not start the payment. Please try again.");
  };

  if (!user) return null;

  return (
    <div style={s.page}>
      <div style={s.card}>
        <div style={{ fontSize: 46 }}>🚀</div>
        <h1 style={s.title}>Become an Agent</h1>

        {state === "loading" && <p style={s.muted}>Checking your account…</p>}

        {state === "activated" && (
          <>
            <div style={s.okBox}>✅ You are an agent. Your Agent Hub is ready.</div>
            <button style={s.primary} onClick={() => setPage("agent-dashboard")}>Open Agent Hub</button>
          </>
        )}

        {state === "paid" && (
          <>
            <div style={s.okBox}>
              ✅ Payment received.<br />
              We confirm it with Paystack about 30 minutes after you pay, then your account becomes an agent account automatically.
            </div>
            {info?.activate_after && (
              <div style={s.timer}>
                <div style={s.timerLabel}>Activating in about</div>
                <div style={s.timerNum}>{mmss(info.activate_after, now)}</div>
              </div>
            )}
            <p style={s.muted}>You can close this page. It will be done on its own.</p>
          </>
        )}

        {state === "pending" && (
          <>
            <div style={s.warnBox}>Waiting for your payment to show up on Paystack…</div>
            <button style={s.primary} disabled={busy} onClick={check}>I have paid, check again</button>
            <button style={s.ghost} disabled={busy} onClick={pay}>Start a new payment</button>
          </>
        )}

        {(state === "none" || state === "failed" || state === "expired") && (
          <>
            {state === "failed" && <div style={s.errBox}>The last payment could not be confirmed. If money left your account, contact support with your payment reference.</div>}
            <div style={s.priceRow}>
              <span style={s.was}>GH₵{WAS}</span>
              <span style={s.now}>GH₵{FEE}</span>
            </div>
            <div style={s.once}>One-time fee</div>

            <div style={s.perks}>
              {PERKS.map(([ico, t, d]) => (
                <div key={t} style={s.perk}>
                  <span style={{ fontSize: 22 }}>{ico}</span>
                  <div><div style={s.perkT}>{t}</div><div style={s.perkD}>{d}</div></div>
                </div>
              ))}
            </div>

            <button style={{ ...s.primary, opacity: busy ? 0.6 : 1 }} disabled={busy} onClick={pay}>
              {busy ? "Opening Paystack…" : `Pay GH₵${FEE} with Paystack`}
            </button>
            <p style={s.fine}>After you pay, we confirm the payment about 30 minutes later and upgrade your account automatically.</p>
          </>
        )}

        {error && <div style={s.errBox}>{error}</div>}
      </div>
    </div>
  );
}

const s = {
  page: { minHeight: "60vh", display: "flex", justifyContent: "center", padding: "22px 16px 70px" },
  card: { width: "100%", maxWidth: 430, textAlign: "center", color: "#e5e7eb", background: "rgba(22,17,38,0.92)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 24, padding: "28px 22px", alignSelf: "flex-start" },
  title: { fontSize: 26, fontWeight: 900, margin: "6px 0 16px", color: "#f3f0fb" },
  muted: { color: "#9189b5", fontSize: 13 },
  priceRow: { display: "flex", justifyContent: "center", alignItems: "baseline", gap: 14, marginTop: 4 },
  was: { fontSize: 22, color: "#7a6fa3", textDecoration: "line-through", fontWeight: 700 },
  now: { fontSize: 44, fontWeight: 900, color: "#c8ff3e" },
  once: { fontSize: 12, color: "#9189b5", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 18 },
  perks: { display: "grid", gap: 10, textAlign: "left", margin: "0 0 20px" },
  perk: { display: "flex", gap: 12, alignItems: "center", padding: "11px 12px", borderRadius: 14, background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.06)" },
  perkT: { fontWeight: 800, fontSize: 14, color: "#f3f0fb" },
  perkD: { fontSize: 12, color: "#9189b5" },
  primary: { width: "100%", padding: 15, borderRadius: 14, border: "none", cursor: "pointer", background: "linear-gradient(135deg,#c8ff3e,#8fe600)", color: "#000", fontWeight: 900, fontSize: 16, boxShadow: "0 8px 26px rgba(200,255,62,0.25)" },
  ghost: { width: "100%", marginTop: 10, padding: 13, borderRadius: 14, border: "1px solid rgba(255,255,255,0.12)", background: "transparent", color: "#e5e7eb", fontWeight: 700, cursor: "pointer" },
  fine: { fontSize: 12, color: "#7a6fa3", margin: "12px 0 0", lineHeight: 1.5 },
  okBox: { padding: "14px", borderRadius: 14, background: "rgba(34,197,94,0.12)", border: "1px solid rgba(34,197,94,0.35)", fontSize: 14, lineHeight: 1.55, marginBottom: 16 },
  warnBox: { padding: "14px", borderRadius: 14, background: "rgba(255,176,32,0.1)", border: "1px solid rgba(255,176,32,0.35)", fontSize: 14, marginBottom: 16, color: "#ffd27a" },
  errBox: { padding: "12px 14px", borderRadius: 12, background: "rgba(239,68,68,0.12)", border: "1px solid rgba(239,68,68,0.35)", color: "#f87171", fontSize: 13, margin: "14px 0 0" },
  timer: { margin: "0 0 14px" },
  timerLabel: { fontSize: 12, color: "#9189b5", textTransform: "uppercase", letterSpacing: "0.08em" },
  timerNum: { fontSize: 40, fontWeight: 900, color: "#c8ff3e", fontVariantNumeric: "tabular-nums" },
};
