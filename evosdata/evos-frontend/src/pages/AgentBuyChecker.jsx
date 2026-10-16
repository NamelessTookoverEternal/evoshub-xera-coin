import { useEffect, useState } from "react";

import { smartFetch } from "../config";

const CHECKER_CONFIG = {
  WAEC: { emoji: "🟢", color: "#16a34a", accent: "#22c55e", bg: "rgba(34,197,94,0.1)", border: "rgba(34,197,94,0.35)", label: "WAEC", desc: "West African Senior School Certificate result checker" },
  BECE: { emoji: "📘", color: "#3b82f6", accent: "#3b82f6", bg: "rgba(59,130,246,0.1)", border: "rgba(59,130,246,0.35)", label: "BECE", desc: "Basic Education Certificate Examination result checker" },
};

export default function AgentBuyChecker({ user, setPage }) {
  const [loading, setLoading] = useState(true);
  const [basePrice, setBasePrice] = useState(16.80);
  const [walletBalance, setWalletBalance] = useState(0);
  const [checkerType, setCheckerType] = useState("");
  const [phone, setPhone] = useState("");
  const [quantity, setQuantity] = useState(1);
  const [processing, setProcessing] = useState(false);
  const [error, setError] = useState("");
  const [successMsg, setSuccessMsg] = useState("");

  useEffect(() => {
    if (!user) { setPage("login"); return; }
    if (user.role !== "agent" || user.agent_status !== "approved") setPage("dashboard");
  }, [user, setPage]);

  useEffect(() => {
    if (!user?.id) return;
    const load = async () => {
      try {
        setLoading(true);
        const agentToken = sessionStorage.getItem("agentToken");
        const [pricingRes, dashRes] = await Promise.all([
          smartFetch(`/agent/checker-pricing/${user.id}`, {
            headers: { "X-Agent-Token": agentToken },
          }),
          smartFetch(`/agent/dashboard/${user.id}`, {
            headers: { "X-Agent-Token": agentToken },
          }),
        ]);
        const pricingData = await pricingRes.json();
        const dashData = await dashRes.json();
        if (pricingData.prices?.[0]?.base_price) {
          setBasePrice(Number(pricingData.prices[0].base_price));
        }
        setWalletBalance(Number(dashData.wallet_balance || 0));
      } catch (err) {
        console.error(err);
        setError("Failed to load wallet info. Please refresh.");
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [user]);

  const totalCost = round2(basePrice * quantity);
  const hasFunds = walletBalance >= totalCost;
  const canSubmit = checkerType && phone.trim().length >= 9 && quantity >= 1 && !processing && hasFunds;

  const submit = async () => {
    setError("");
    if (!canSubmit) return;
    setProcessing(true);
    try {
      const agentToken = sessionStorage.getItem("agentToken");
      const res = await smartFetch(`/agent/buy-checker`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Agent-Token": agentToken,
        },
        body: JSON.stringify({
          agent_id: user.id,
          checker_type: checkerType,
          phone_number: phone.trim(),
          quantity,
        }),
      });
      const data = await res.json();
      if (data.status === "success") {
        setSuccessMsg(`✅ ${quantity}x ${checkerType} queued for ${phone.trim()}!`);
        setPhone("");
        setQuantity(1);
        setCheckerType("");
        if (typeof data.new_wallet_balance === "number") {
          setWalletBalance(data.new_wallet_balance);
        }
        setTimeout(() => setSuccessMsg(""), 5000);
      } else {
        setError(data.message || "Purchase failed. Please try again.");
      }
    } catch {
      setError("Network error. Please try again.");
    } finally {
      setProcessing(false);
    }
  };

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <div style={styles.headerBadge}>🎓 Buy Checker (Base Price)</div>
        <h2 style={styles.title}>Buy a Result Checker for a Customer</h2>
        <p style={styles.subtitle}>You pay your base price — GH₵ {basePrice.toFixed(2)} per card</p>
      </div>

      <div style={styles.wrapper}>
        <div style={styles.box}>
          <div style={styles.walletRow}>
            <span style={styles.walletLabel}>💳 Wallet Balance</span>
            <span style={styles.walletValue}>GH₵ {walletBalance.toFixed(2)}</span>
          </div>

          {successMsg && <div style={styles.successBanner}>{successMsg}</div>}
          {error && <div style={styles.errorBanner}>{error}</div>}

          {loading ? (
            <div style={styles.emptyBox}>
              <div style={{ fontSize: 32, marginBottom: 8 }}>⏳</div>
              <p style={styles.emptyText}>Loading...</p>
            </div>
          ) : (
            <>
              <p style={styles.stepLabel}>Checker Type</p>
              <div style={styles.checkerGrid}>
                {Object.entries(CHECKER_CONFIG).map(([type, cfg]) => (
                  <div
                    key={type}
                    onClick={() => setCheckerType(type)}
                    style={{
                      ...styles.checkerCard,
                      background: cfg.bg,
                      border: `2px solid ${checkerType === type ? cfg.accent : cfg.border}`,
                      boxShadow: checkerType === type ? `0 0 0 3px ${cfg.accent}33` : "none",
                    }}
                  >
                    <div style={{ fontSize: 26 }}>{cfg.emoji}</div>
                    <div style={{ ...styles.checkerName, color: cfg.color }}>{cfg.label}</div>
                    <div style={styles.checkerDesc}>{cfg.desc}</div>
                  </div>
                ))}
              </div>

              <p style={styles.stepLabel}>Recipient Phone Number</p>
              <input
                type="tel"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                placeholder="e.g. 0551234567"
                style={styles.input}
              />

              <p style={styles.stepLabel}>Quantity</p>
              <input
                type="number"
                min="1"
                max="20"
                value={quantity}
                onChange={(e) => setQuantity(Math.max(1, Math.min(20, Number(e.target.value) || 1)))}
                style={styles.input}
              />

              <div style={styles.totalRow}>
                <span>Total Cost</span>
                <strong style={{ color: hasFunds ? "#22c55e" : "#ef4444" }}>GH₵ {totalCost.toFixed(2)}</strong>
              </div>
              {!hasFunds && (
                <p style={styles.insufficientText}>Insufficient wallet balance for this order.</p>
              )}

              <button
                onClick={submit}
                disabled={!canSubmit}
                style={{ ...styles.submitBtn, opacity: canSubmit ? 1 : 0.5, cursor: canSubmit ? "pointer" : "not-allowed" }}
              >
                {processing ? "⏳ Processing..." : "Buy Checker →"}
              </button>
            </>
          )}

          <button style={styles.backDashBtn} onClick={() => setPage("agent-dashboard")}>← Back to Dashboard</button>
        </div>
      </div>
    </div>
  );
}

function round2(n) {
  return Math.round((Number(n) + Number.EPSILON) * 100) / 100;
}

const styles = {
  container: { padding: "28px 18px 80px", minHeight: "auto", fontFamily: "'Nunito', 'Poppins', ui-rounded, system-ui, Arial", color: "#241c3d" },
  header: { textAlign: "center", marginBottom: 20 },
  headerBadge: { display: "inline-block", padding: "5px 18px", borderRadius: 50, background: "linear-gradient(135deg, #dcfce7, #bbf7d0)", border: "1px solid #86efac", color: "#15803d", fontSize: 12, fontWeight: 800, marginBottom: 10, letterSpacing: "0.5px" },
  title: { fontSize: 24, fontWeight: 900, color: "#f3f0fb", margin: "0 0 6px", letterSpacing: "-0.5px" },
  subtitle: { fontSize: 13, color: "#9189b5", margin: 0, fontWeight: 600 },
  wrapper: { maxWidth: 480, margin: "0 auto" },
  box: { background: "rgba(22,17,38,0.85)", backdropFilter: "blur(20px)", WebkitBackdropFilter: "blur(20px)", padding: "24px 20px", borderRadius: 24, border: "1px solid rgba(255,255,255,0.07)", boxShadow: "0 8px 40px rgba(0,0,0,0.3)" },
  walletRow: { display: "flex", justifyContent: "space-between", alignItems: "center", background: "rgba(255,255,255,0.05)", borderRadius: 14, padding: "12px 16px", marginBottom: 16 },
  walletLabel: { fontSize: 13, color: "#b4acd0", fontWeight: 700 },
  walletValue: { fontSize: 16, color: "#22c55e", fontWeight: 900 },
  successBanner: { background: "rgba(34,197,94,0.12)", border: "1px solid rgba(34,197,94,0.35)", color: "#22c55e", borderRadius: 12, padding: "10px 14px", fontSize: 13, fontWeight: 700, marginBottom: 14 },
  errorBanner: { background: "rgba(239,68,68,0.12)", border: "1px solid rgba(239,68,68,0.35)", color: "#f87171", borderRadius: 12, padding: "10px 14px", fontSize: 13, fontWeight: 700, marginBottom: 14 },
  emptyBox: { textAlign: "center", padding: "30px 0" },
  emptyText: { color: "#9189b5", fontSize: 14, margin: 0, fontWeight: 600 },
  stepLabel: { fontSize: 11, color: "#8b5cf6", fontWeight: 800, textTransform: "uppercase", letterSpacing: "1px", margin: "16px 0 10px" },
  checkerGrid: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 },
  checkerCard: { borderRadius: 16, padding: "14px 10px", textAlign: "center", cursor: "pointer", transition: "all 0.15s" },
  checkerName: { fontWeight: 900, fontSize: 14, margin: "4px 0 2px" },
  checkerDesc: { fontSize: 10, color: "#b4acd0", fontWeight: 600, lineHeight: 1.4 },
  input: { width: "100%", padding: "12px 14px", borderRadius: 12, background: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.12)", color: "#f3f0fb", fontSize: 14, fontWeight: 700, boxSizing: "border-box", outline: "none" },
  totalRow: { display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 18, fontSize: 14, fontWeight: 800, color: "#d9d4ec" },
  insufficientText: { color: "#f87171", fontSize: 12, fontWeight: 700, marginTop: 6 },
  submitBtn: { width: "100%", padding: "15px", borderRadius: 16, border: "none", color: "white", fontWeight: 900, fontSize: 15, marginTop: 16, background: "linear-gradient(135deg, #22c55e, #16a34a)", boxShadow: "0 6px 24px rgba(34,197,94,0.3)" },
  backDashBtn: { width: "100%", padding: "12px", borderRadius: 14, background: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.1)", color: "#b4acd0", fontWeight: 700, fontSize: 13, cursor: "pointer", marginTop: 12 },
};
