import { useState, useEffect } from "react";

import { smartFetch } from "../config";

// Paystack Ghana fee: 1.95% + GH₵ 0.25 (capped at GH₵ 2000)
// Agent pays the fee on top → they pay: amount + fee
const calcFee = (amount) => {
  const pct = amount * 0.0195;
  const flat = 0.25;
  const fee = pct + flat;
  return Math.min(parseFloat(fee.toFixed(2)), 2000);
};

const QUICK_AMOUNTS = [10, 20, 50, 100, 200, 500];

export default function AgentDeposit({ user, setPage, authLoading }) {
  const [amount, setAmount]             = useState("");
  const [walletBalance, setWalletBalance] = useState(0);
  const [loading, setLoading]           = useState(true);
  const [submitting, setSubmitting]     = useState(false);
  const [error, setError]               = useState("");

  const numAmount  = parseFloat(amount) || 0;
  const fee        = numAmount >= 1 ? calcFee(numAmount) : 0;
  const totalCharge = parseFloat((numAmount + fee).toFixed(2));
  const isValid    = numAmount >= 1;

  // ── Retrieve the agent token saved at login ──
  const agentToken = sessionStorage.getItem("agentToken") || localStorage.getItem("agentToken") || "";

  useEffect(() => {
    if (authLoading) return;
    if (!user) { setPage("login"); return; }
    if (user.role !== "agent" || user.agent_status !== "approved") {
      setPage("dashboard");
      return;
    }

    const loadBalance = async () => {
      try {
        const res = await smartFetch(`/agent/dashboard/${user.id}`, {
          headers: { "X-Agent-Token": agentToken },
        });
        const data = await res.json();
        if (res.status === 403) {
          setError("Session expired. Please log in again.");
          setPage("login");
          return;
        }
        setWalletBalance(Number(data.wallet_balance || 0));
      } catch {
        // non-fatal — balance stays 0
      } finally {
        setLoading(false);
      }
    };

    loadBalance();
  }, [user, authLoading, setPage, agentToken]);

  // Don't render until auth is confirmed — prevents redirect flash
  if (authLoading) return null;

  const handleDeposit = async () => {
    if (!isValid || submitting) return;
    setSubmitting(true);
    setError("");
    try {
      const res = await smartFetch(`/agent/deposit/initiate`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Agent-Token": agentToken,
        },
        body: JSON.stringify({
          agent_id:     user.id,
          amount:       numAmount,     // wallet credit amount
          total_charge: totalCharge,   // what Paystack charges
          fee,
        }),
      });

      if (res.status === 403) {
        setError("Session expired. Please log in again.");
        setPage("login");
        return;
      }

      const data = await res.json();
      if (data.payment_url) {
        window.location.href = data.payment_url;
      } else {
        setError(data.error || data.message || "Failed to initiate payment");
      }
    } catch {
      setError("Network error. Please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div style={s.page}>

      {/* ── HEADER ── */}
      <div style={s.header}>
        <button style={s.backBtn} onClick={() => setPage("agent-dashboard")}>←</button>
        <div style={s.headerMid}>
          <div style={s.headerTitle}>Top Up Wallet</div>
          <div style={s.headerSub}>Instant credit via Paystack</div>
        </div>
        <div style={s.walletPill}>
          <span style={s.walletPillLabel}>Balance</span>
          <span style={s.walletPillVal}>
            {loading ? "—" : `GH₵ ${walletBalance.toFixed(2)}`}
          </span>
        </div>
      </div>

      <div style={s.main}>

        {/* ── HERO CARD ── */}
        <div style={s.heroCard}>
          <div style={s.heroIcon}>💳</div>
          <div style={s.heroText}>
            <div style={s.heroTitle}>Add Funds to Your Wallet</div>
            <div style={s.heroSub}>Pay with MoMo, card or bank · Secured by Paystack</div>
          </div>
        </div>

        {/* ── AMOUNT INPUT ── */}
        <div style={s.card}>
          <div style={s.cardLabel}>Enter Amount (GH₵)</div>

          {/* Quick select */}
          <div style={s.quickGrid}>
            {QUICK_AMOUNTS.map((q) => (
              <button
                key={q}
                style={{
                  ...s.quickBtn,
                  background: numAmount === q
                    ? "linear-gradient(135deg, #c8ff3e, #8fe600)"
                    : "rgba(255,255,255,0.05)",
                  border: numAmount === q
                    ? "1px solid #c8ff3e"
                    : "1px solid rgba(255,255,255,0.08)",
                  color:      numAmount === q ? "#000" : "#b4acd0",
                  fontWeight: numAmount === q ? 900 : 600,
                }}
                onClick={() => setAmount(String(q))}
              >
                {q}
              </button>
            ))}
          </div>

          {/* Manual input */}
          <div style={s.inputWrap}>
            <span style={s.inputPrefix}>GH₵</span>
            <input
              type="number"
              min="1"
              step="1"
              placeholder="Enter custom amount"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              style={s.input}
            />
          </div>

          {/* Fee breakdown */}
          {numAmount >= 1 && (
            <div style={s.breakdown}>
              <div style={s.breakdownRow}>
                <span style={s.breakdownLabel}>Wallet credit</span>
                <span style={s.breakdownVal}>GH₵ {numAmount.toFixed(2)}</span>
              </div>
              <div style={s.breakdownRow}>
                <span style={s.breakdownLabel}>Paystack fee (1.95% + GH₵ 0.25)</span>
                <span style={{ ...s.breakdownVal, color: "#f59e0b" }}>+ GH₵ {fee.toFixed(2)}</span>
              </div>
              <div style={s.breakdownDivider} />
              <div style={s.breakdownRow}>
                <span style={{ ...s.breakdownLabel, color: "#f3f0fb", fontWeight: 800 }}>
                  You pay
                </span>
                <span style={{ ...s.breakdownVal, color: "#22c55e", fontSize: 18, fontWeight: 900 }}>
                  GH₵ {totalCharge.toFixed(2)}
                </span>
              </div>
              <div style={s.breakdownNote}>
                💡 GH₵ {numAmount.toFixed(2)} will be credited to your wallet
              </div>
            </div>
          )}

          {error && <div style={s.errorBox}>⚠️ {error}</div>}

          <button
            onClick={handleDeposit}
            disabled={!isValid || submitting}
            style={{
              ...s.payBtn,
              opacity: isValid && !submitting ? 1 : 0.4,
              cursor:  isValid && !submitting ? "pointer" : "not-allowed",
            }}
          >
            {submitting
              ? "⏳ Redirecting..."
              : isValid
              ? `💳 Pay GH₵ ${totalCharge.toFixed(2)} via Paystack`
              : "Enter an amount to continue"}
          </button>

          <p style={s.secureNote}>🔒 Payments secured & encrypted by Paystack</p>
        </div>

        {/* ── HOW IT WORKS ── */}
        <div style={s.stepsCard}>
          <div style={s.stepsTitle}>How it works</div>
          {[
            { icon: "1️⃣", text: "Enter the amount you want in your wallet" },
            { icon: "2️⃣", text: "Pay securely via Paystack (MoMo, card, bank)" },
            { icon: "3️⃣", text: "Wallet credited instantly on payment success" },
          ].map((step, i) => (
            <div key={i} style={s.stepRow}>
              <span style={s.stepIcon}>{step.icon}</span>
              <span style={s.stepText}>{step.text}</span>
            </div>
          ))}
        </div>

      </div>
    </div>
  );
}

const s = {
  page: {
    minHeight: "auto",
    color: "#e5e7eb",
    fontFamily: "ui-sans-serif, system-ui, Arial",
  },

  header: {
    display: "flex",
    alignItems: "center",
    gap: 12,
    padding: "14px 18px",
    borderBottom: "1px solid rgba(255,255,255,0.06)",
    background: "rgba(22,17,38,0.9)",
    backdropFilter: "blur(12px)",
    position: "sticky",
    top: 0,
    zIndex: 100,
  },
  backBtn: {
    width: 36, height: 36, borderRadius: 10,
    border: "1px solid rgba(255,255,255,0.08)",
    background: "rgba(255,255,255,0.05)",
    color: "#b4acd0", fontSize: 16, cursor: "pointer",
    fontWeight: 800, display: "flex", alignItems: "center", justifyContent: "center",
    flexShrink: 0,
  },
  headerMid:   { flex: 1 },
  headerTitle: { fontSize: 16, fontWeight: 900, color: "#f3f0fb" },
  headerSub:   { fontSize: 11, color: "#7a6fa3", fontWeight: 600, marginTop: 1 },
  walletPill: {
    display: "flex", flexDirection: "column", alignItems: "flex-end",
    background: "rgba(34,197,94,0.08)", border: "1px solid rgba(34,197,94,0.2)",
    borderRadius: 12, padding: "6px 12px", flexShrink: 0,
  },
  walletPillLabel: { fontSize: 10, color: "#9189b5", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.5px" },
  walletPillVal:   { fontSize: 14, fontWeight: 900, color: "#22c55e" },

  main: { maxWidth: 480, margin: "0 auto", padding: "20px 16px 80px" },

  heroCard: {
    display: "flex", alignItems: "center", gap: 16,
    background: "linear-gradient(135deg, rgba(200,255,62,0.12), rgba(139,92,246,0.08))",
    border: "1px solid rgba(200,255,62,0.2)",
    borderRadius: 20, padding: "18px 20px", marginBottom: 18,
  },
  heroIcon:  { fontSize: 36, flexShrink: 0 },
  heroText:  { flex: 1 },
  heroTitle: { fontSize: 16, fontWeight: 900, color: "#f3f0fb", marginBottom: 4 },
  heroSub:   { fontSize: 12, color: "#9189b5", fontWeight: 600 },

  card: {
    background: "rgba(22,17,38,0.9)",
    backdropFilter: "blur(20px)",
    borderRadius: 22,
    border: "1px solid rgba(255,255,255,0.07)",
    padding: "22px 18px",
    marginBottom: 16,
    boxShadow: "0 20px 50px rgba(0,0,0,0.3)",
  },
  cardLabel: {
    fontSize: 11, color: "#c8ff3e", fontWeight: 800,
    textTransform: "uppercase", letterSpacing: "0.8px", marginBottom: 14,
  },

  quickGrid: {
    display: "grid", gridTemplateColumns: "repeat(3, 1fr)",
    gap: 8, marginBottom: 16,
  },
  quickBtn: {
    padding: "10px 6px", borderRadius: 12,
    fontSize: 14, cursor: "pointer",
    transition: "all 0.15s", fontFamily: "inherit",
  },

  inputWrap: {
    display: "flex", alignItems: "center",
    background: "rgba(10,8,20,0.75)",
    border: "1px solid rgba(255,255,255,0.1)",
    borderRadius: 14, overflow: "hidden", marginBottom: 16,
  },
  inputPrefix: {
    padding: "0 14px", fontSize: 14, fontWeight: 900,
    color: "#c8ff3e", borderRight: "1px solid rgba(255,255,255,0.08)",
    height: "100%", display: "flex", alignItems: "center",
    background: "rgba(200,255,62,0.06)", whiteSpace: "nowrap",
    lineHeight: "48px",
  },
  input: {
    flex: 1, padding: "14px 14px", border: "none",
    background: "transparent", color: "#f3f0fb",
    fontSize: 18, fontWeight: 800, outline: "none",
    fontFamily: "inherit",
  },

  breakdown: {
    background: "rgba(10,8,20,0.5)",
    border: "1px solid rgba(255,255,255,0.06)",
    borderRadius: 16, padding: "14px 16px", marginBottom: 18,
  },
  breakdownRow: {
    display: "flex", justifyContent: "space-between",
    alignItems: "center", padding: "5px 0",
  },
  breakdownLabel: { fontSize: 13, color: "#9189b5", fontWeight: 600 },
  breakdownVal:   { fontSize: 14, fontWeight: 800, color: "#e5e7eb" },
  breakdownDivider: {
    height: 1, background: "rgba(255,255,255,0.07)", margin: "8px 0",
  },
  breakdownNote: {
    fontSize: 11, color: "#7a6fa3", fontWeight: 600,
    marginTop: 10, textAlign: "center",
  },

  errorBox: {
    background: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.3)",
    color: "#f87171", padding: "12px 14px", borderRadius: 12,
    fontSize: 13, fontWeight: 700, marginBottom: 14,
  },

  payBtn: {
    width: "100%", padding: "15px", borderRadius: 16, border: "none",
    background: "linear-gradient(135deg, #22c55e, #16a34a)",
    color: "white", fontWeight: 900, fontSize: 15,
    boxShadow: "0 6px 24px rgba(34,197,94,0.3)",
    marginBottom: 10, fontFamily: "inherit", transition: "opacity 0.2s",
  },
  secureNote: {
    textAlign: "center", fontSize: 11, color: "#7a6fa3",
    margin: 0, fontWeight: 600,
  },

  stepsCard: {
    background: "rgba(22,17,38,0.6)",
    border: "1px solid rgba(255,255,255,0.05)",
    borderRadius: 18, padding: "18px 16px",
  },
  stepsTitle: {
    fontSize: 12, color: "#7a6fa3", fontWeight: 800,
    textTransform: "uppercase", letterSpacing: "0.8px", marginBottom: 14,
  },
  stepRow: {
    display: "flex", alignItems: "flex-start", gap: 12,
    padding: "8px 0", borderBottom: "1px solid rgba(255,255,255,0.04)",
  },
  stepIcon: { fontSize: 16, flexShrink: 0, marginTop: 1 },
  stepText: { fontSize: 13, color: "#9189b5", fontWeight: 600, lineHeight: 1.5 },
};
