import { useEffect, useState } from "react";
import { withBase, IS_HUB_MOUNT } from "../lib/basePath";

import { smartFetch } from "../config";
import { userApi } from "../lib/userApi";

export default function Success() {
  const [status, setStatus] = useState("verifying");
  const [checkerData, setCheckerData] = useState(null);
  const [afaData, setAfaData] = useState(null);
  const [copiedKey, setCopiedKey] = useState("");
  const [spinReady, setSpinReady] = useState(false);

  const params    = new URLSearchParams(window.location.search);
  const reference = params.get("reference");
  const type      = params.get("type");

  const copyToClipboard = (text, key) => {
    if (!text) return;
    navigator.clipboard?.writeText(text).then(() => {
      setCopiedKey(key);
      setTimeout(() => setCopiedKey(""), 1500);
    });
  };

  useEffect(() => {
    if (!reference) {
      setStatus("order_success"); // Paystack sent them here = paid
      return;
    }

    if (type === "agent-fee") {
      // No work to do here: the server confirms the payment and upgrades the account on its own.
      setStatus("agent_fee_success");
    } else if (type === "deposit") {
      // fire-and-forget
      smartFetch(`/agent/deposit/verify`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reference }),
      }).catch(console.error);

      setStatus("deposit_success");
    } else if (type === "checker") {
      // Checker purchases need the actual serial + PIN before we can show
      // a real success screen, so this one is NOT fire-and-forget — it
      // verifies payment (dispatching to DataMart inline if the webhook
      // hasn't landed yet) and waits for the response.
      setStatus("checker_verifying");
      smartFetch(`/checkers/status/${reference}`)
        .then((res) => res.json())
        .then((data) => {
          setCheckerData(data);
          setStatus(data?.status === "successful" ? "checker_success" : "checker_pending");
        })
        .catch(() => setStatus("checker_pending"));
    } else if (type === "afa") {
      setStatus("afa_verifying");
      smartFetch(`/afa/status/${reference}`)
        .then((res) => res.json())
        .then((data) => {
          setAfaData(data);
          setStatus(data?.status === "rejected" ? "afa_rejected" : "afa_success");
        })
        .catch(() => setStatus("afa_success"));
    } else {
      // fire-and-forget
      smartFetch(`/orders/sync/${reference}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      }).catch(console.error);

      setStatus("order_success");
    }
  }, [reference, type]);

  // After a paid data order, remind a signed-in customer that today's free spin is waiting.
  useEffect(() => {
    if (status !== "order_success") return;
    let u = null;
    try { u = JSON.parse(localStorage.getItem("user") || "null"); } catch { /* ignore */ }
    if (!u?.id || !u?.user_token) return;
    userApi(u, `/spin/status?user_id=${u.id}`).then((r) => {
      if (r.ok && r.data.can_spin) setSpinReady(true);
    });
  }, [status]);

  return (
    <div style={s.page}>
      <div style={s.card}>

        {/* ── VERIFYING ── */}
        {status === "verifying" && (
          <>
            <div style={s.spinner}>⏳</div>
            <h2 style={s.title}>Verifying Payment</h2>
            <p style={s.sub}>Please wait, this takes a few seconds...</p>
          </>
        )}

        {/* ── AGENT FEE ── */}
        {status === "agent_fee_success" && (
          <>
            <div style={{ ...s.iconCircle, background: "rgba(200,255,62,0.12)", border: "2px solid rgba(200,255,62,0.35)" }}>🚀</div>
            <h2 style={{ ...s.title, color: "#c8ff3e" }}>Payment Received</h2>
            <p style={s.sub}>
              We confirm your GH₵50 payment about 30 minutes from now, then your account becomes an agent account automatically.
              You can close this page.
            </p>
            <div style={s.btnGroup}>
              <button style={s.primaryBtn} onClick={() => window.location.href = withBase(`/become-agent${reference ? `?reference=${encodeURIComponent(reference)}` : ""}`)}>
                ⏱ See activation status
              </button>
              <button style={s.secondaryBtn} onClick={() => window.location.href = withBase("/dashboard")}>🏠 Dashboard</button>
            </div>
          </>
        )}

        {/* ── DEPOSIT SUCCESS ── */}
        {status === "deposit_success" && (
          <>
            <div style={{ ...s.iconCircle, background: "rgba(34,197,94,0.15)", border: "2px solid rgba(34,197,94,0.3)" }}>
              💰
            </div>
            <h2 style={{ ...s.title, color: "#22c55e" }}>Wallet Topped Up!</h2>
            <p style={s.sub}>Your payment was successful</p>

            <div style={s.btnGroup}>
              <button style={s.primaryBtn} onClick={() => window.location.href = withBase("/agent-buy-data")}>
                📡 Buy Data Now
              </button>
              <button style={s.secondaryBtn} onClick={() => window.location.href = withBase("/agent-dashboard")}>
                🏠 Dashboard
              </button>
            </div>
          </>
        )}

        {/* ── AFA ── */}
        {status === "afa_verifying" && (
          <>
            <div style={s.spinner}>⏳</div>
            <h2 style={s.title}>Verifying Payment</h2>
            <p style={s.sub}>Submitting your AFA registration, this takes a few seconds...</p>
          </>
        )}
        {status === "afa_success" && (
          <>
            <div style={{ ...s.iconCircle, background: "rgba(34,197,94,0.15)", border: "2px solid rgba(34,197,94,0.3)" }}>📝</div>
            <h2 style={{ ...s.title, color: "#22c55e" }}>AFA Registration Submitted</h2>
            <p style={s.sub}>
              {afaData?.phone_number ? `${afaData.phone_number} is being registered. ` : ""}
              Approval can take a little while. Check progress anytime on the AFA page with the MTN number.
            </p>
            <div style={s.btnGroup}>
              <button style={s.primaryBtn} onClick={() => window.location.href = withBase("/afa")}>🔎 Check Status</button>
              <button style={s.secondaryBtn} onClick={() => window.location.href = withBase("/")}>🏠 Go Home</button>
            </div>
          </>
        )}
        {status === "afa_rejected" && (
          <>
            <div style={{ ...s.iconCircle, background: "rgba(239,68,68,0.15)", border: "2px solid rgba(239,68,68,0.3)" }}>⚠️</div>
            <h2 style={{ ...s.title, color: "#f87171" }}>Registration Rejected</h2>
            <p style={s.sub}>{afaData?.failure_reason || "The details could not be accepted."} Contact support with your payment reference for a refund or correction.</p>
            <div style={s.btnGroup}>
              <button style={s.secondaryBtn} onClick={() => window.location.href = withBase("/")}>🏠 Go Home</button>
            </div>
          </>
        )}

        {/* ── CHECKER: VERIFYING ── */}
        {status === "checker_verifying" && (
          <>
            <div style={s.spinner}>⏳</div>
            <h2 style={s.title}>Verifying Payment</h2>
            <p style={s.sub}>Fetching your serial number and PIN, this takes a few seconds...</p>
          </>
        )}

        {/* ── CHECKER: SUCCESS (serial + pin) ── */}
        {status === "checker_success" && (
          <>
            <div style={{ ...s.iconCircle, background: "rgba(34,197,94,0.15)", border: "2px solid rgba(34,197,94,0.3)" }}>
              🎓
            </div>
            <h2 style={{ ...s.title, color: "#22c55e" }}>Checker Purchased!</h2>
            <p style={s.sub}>Your {checkerData?.checker_type} card{checkerData?.quantity > 1 ? "s are" : " is"} ready ✅</p>

            <div style={s.checkerCardList}>
              {(checkerData?.serial_numbers || []).map((card, i) => (
                <div key={i} style={s.checkerCardBox}>
                  <div style={s.checkerCardRow}>
                    <span style={s.checkerCardLabel}>Serial</span>
                    <span style={s.checkerCardValue}>{card.serialNumber}</span>
                    <button
                      style={s.checkerCopyBtn}
                      onClick={() => copyToClipboard(card.serialNumber, `s-${i}`)}
                    >
                      {copiedKey === `s-${i}` ? "✓" : "Copy"}
                    </button>
                  </div>
                  <div style={s.checkerCardRow}>
                    <span style={s.checkerCardLabel}>PIN</span>
                    <span style={s.checkerCardValue}>{card.pin}</span>
                    <button
                      style={s.checkerCopyBtn}
                      onClick={() => copyToClipboard(card.pin, `p-${i}`)}
                    >
                      {copiedKey === `p-${i}` ? "✓" : "Copy"}
                    </button>
                  </div>
                </div>
              ))}
            </div>
            <p style={{ ...s.sub, margin: "0 0 20px", fontSize: 12 }}>
              📩 We've also sent this by SMS to {checkerData?.phone_number}. Save it somewhere safe.
            </p>

            <div style={s.btnGroup}>
              <button style={s.primaryBtn} onClick={() => window.location.href = withBase("/checkers")}>
                🎓 Buy Another Checker
              </button>
              <button style={s.secondaryBtn} onClick={() => window.location.href = withBase("/")}>
                🏠 Go Home
              </button>
            </div>
          </>
        )}

        {/* ── CHECKER: STILL PROCESSING ── */}
        {status === "checker_pending" && (
          <>
            <div style={{ ...s.iconCircle, background: "rgba(251,191,36,0.15)", border: "2px solid rgba(251,191,36,0.3)" }}>
              ⏳
            </div>
            <h2 style={{ ...s.title, color: "#fbbf24" }}>Payment Received</h2>
            <p style={s.sub}>
              Your checker is still being processed — this can take a minute.
              Use "Find your checker" on the Checkers page with your phone number to retrieve it shortly.
            </p>

            <div style={s.btnGroup}>
              <button style={s.primaryBtn} onClick={() => window.location.href = withBase("/checkers")}>
                🔎 Go to Checkers Page
              </button>
              <button style={s.secondaryBtn} onClick={() => window.location.href = withBase("/")}>
                🏠 Go Home
              </button>
            </div>
          </>
        )}

        {/* ── ORDER SUCCESS ── */}
        {status === "order_success" && (
          <>
            <div style={{ ...s.iconCircle, background: "rgba(200,255,62,0.15)", border: "2px solid rgba(200,255,62,0.3)" }}>
              📦
            </div>
            <h2 style={{ ...s.title, color: "#c8ff3e" }}>Order Placed!</h2>
            <p style={s.sub}>Your data bundle is being processed ✅</p>

            <div style={s.summaryBox}>
              <div style={{ ...s.summaryRow, borderBottom: "none" }}>
                <span style={s.summaryLabel}>Status</span>
                <span style={{ ...s.summaryVal, color: "#22c55e", fontWeight: 800 }}>
                  ✅ Processing
                </span>
              </div>
            </div>

            {spinReady && (
              <div style={{ margin: "0 0 14px", padding: "14px", borderRadius: 16, textAlign: "center",
                            background: "linear-gradient(135deg, rgba(200,255,62,0.16), rgba(255,77,141,0.12))",
                            border: "1px solid rgba(200,255,62,0.4)" }}>
                <div style={{ fontSize: 28 }}>🎡</div>
                <div style={{ fontWeight: 900, color: "#f3f0fb", fontSize: 16 }}>Your free spin is ready!</div>
                <div style={{ fontSize: 13, color: "#b4acd0", margin: "4px 0 10px" }}>Win free data from 1GB up to 10GB.</div>
                <button style={s.primaryBtn} onClick={() => window.location.href = withBase("/spin")}>Spin to Win</button>
              </div>
            )}

            {/* ── EVOSGPT PROMO BLOCK ── */}
            <div style={s.promoBox}>
              <div style={s.promoBadge}>🚀 Bonus Unlocked</div>
              <p style={s.promoHeadline}>
                Your EvosData account unlocks more than data.
              </p>
              <p style={s.promoBody}>
                Need help with CVs, business plans, school work, coding, or ideas?
                Meet <strong style={{ color: "#f3f0fb" }}>EVOSGPT</strong> — your AI assistant.
              </p>
              <p style={s.promoSub}>
                Login with your EvosData details and start for free.
              </p>
              <a href={IS_HUB_MOUNT ? "/evosgpt" : "https://evoshub.xyz/evosgpt"} style={s.promoBtn}>
                Try EVOSGPT →
              </a>
            </div>

            <div style={s.btnGroup}>
              <button style={s.primaryBtn} onClick={() => window.location.href = withBase("/eta-track")}>
                📍 Track Order
              </button>
              <button style={s.secondaryBtn} onClick={() => window.location.href = withBase("/")}>
                🏠 Go Home
              </button>
            </div>
          </>
        )}

      </div>
    </div>
  );
}

const s = {
  page: {
    display: "flex", justifyContent: "center", alignItems: "center",
    minHeight: "80vh", padding: "20px 16px",
    fontFamily: "ui-sans-serif, system-ui, Arial",
    color: "#e5e7eb",
  },
  card: {
    width: "100%", maxWidth: 400,
    background: "rgba(22,17,38,0.95)",
    backdropFilter: "blur(20px)",
    borderRadius: 24, padding: "32px 24px",
    border: "1px solid rgba(255,255,255,0.08)",
    boxShadow: "0 25px 60px rgba(0,0,0,0.5)",
    textAlign: "center",
  },
  spinner: { fontSize: 48, marginBottom: 16, display: "block" },
  iconCircle: {
    width: 72, height: 72, borderRadius: "50%",
    display: "flex", alignItems: "center", justifyContent: "center",
    fontSize: 32, margin: "0 auto 18px",
  },
  title: { fontSize: 22, fontWeight: 900, color: "#f3f0fb", margin: "0 0 8px" },
  sub: { fontSize: 14, color: "#9189b5", fontWeight: 600, margin: "0 0 20px", lineHeight: 1.5 },
  summaryBox: {
    background: "rgba(10,8,20,0.5)",
    border: "1px solid rgba(255,255,255,0.06)",
    borderRadius: 16, padding: "4px 16px", marginBottom: 22,
  },
  summaryRow: {
    display: "flex", justifyContent: "space-between", alignItems: "center",
    padding: "12px 0", borderBottom: "1px solid rgba(255,255,255,0.05)",
  },
  summaryLabel: { fontSize: 13, color: "#9189b5", fontWeight: 600 },
  summaryVal: { fontSize: 15, fontWeight: 700, color: "#e5e7eb" },

  /* ── EVOSGPT PROMO BLOCK STYLES ── */
  promoBox: {
    background: "linear-gradient(135deg, rgba(124,58,237,0.15), rgba(200,255,62,0.1))",
    border: "1px solid rgba(124,58,237,0.3)",
    borderRadius: 18,
    padding: "20px 18px",
    marginBottom: 22,
    textAlign: "center",
  },
  promoBadge: {
    display: "inline-block",
    fontSize: 11,
    fontWeight: 800,
    letterSpacing: 0.5,
    color: "#c4b5fd",
    background: "rgba(124,58,237,0.15)",
    border: "1px solid rgba(124,58,237,0.35)",
    borderRadius: 999,
    padding: "4px 12px",
    marginBottom: 12,
  },
  promoHeadline: {
    fontSize: 15,
    fontWeight: 800,
    color: "#f3f0fb",
    margin: "0 0 8px",
    lineHeight: 1.4,
  },
  promoBody: {
    fontSize: 13.5,
    fontWeight: 600,
    color: "#d9d4ec",
    margin: "0 0 6px",
    lineHeight: 1.5,
  },
  promoSub: {
    fontSize: 12.5,
    fontWeight: 600,
    color: "#9189b5",
    margin: "0 0 16px",
    lineHeight: 1.4,
  },
  promoBtn: {
    display: "inline-block",
    width: "100%",
    boxSizing: "border-box",
    padding: "13px",
    borderRadius: 14,
    border: "none",
    background: "linear-gradient(135deg, #7c3aed, #4f46e5)",
    color: "white",
    fontWeight: 900,
    fontSize: 14,
    cursor: "pointer",
    boxShadow: "0 4px 16px rgba(124,58,237,0.35)",
    textDecoration: "none",
    fontFamily: "inherit",
  },

  checkerCardList: { display: "flex", flexDirection: "column", gap: 10, marginBottom: 10 },
  checkerCardBox: {
    background: "rgba(34,197,94,0.06)", border: "1px solid rgba(34,197,94,0.25)",
    borderRadius: 12, padding: "10px 12px", textAlign: "left",
  },
  checkerCardRow: { display: "flex", alignItems: "center", gap: 8, padding: "4px 0" },
  checkerCardLabel: { fontSize: 11, color: "#9189b5", fontWeight: 700, width: 44, flexShrink: 0 },
  checkerCardValue: {
    fontSize: 13, color: "#f3f0fb", fontWeight: 800, fontFamily: "monospace",
    flex: 1, wordBreak: "break-all",
  },
  checkerCopyBtn: {
    fontSize: 11, fontWeight: 800, color: "#22c55e", background: "rgba(34,197,94,0.12)",
    border: "1px solid rgba(34,197,94,0.3)", borderRadius: 8, padding: "4px 10px",
    cursor: "pointer", flexShrink: 0, fontFamily: "inherit",
  },

  btnGroup: { display: "flex", flexDirection: "column", gap: 10 },
  primaryBtn: {
    width: "100%", padding: "13px", borderRadius: 14, border: "none",
    background: "linear-gradient(135deg, #22c55e, #16a34a)",
    color: "white", fontWeight: 900, fontSize: 14, cursor: "pointer",
    boxShadow: "0 4px 16px rgba(34,197,94,0.3)",
    fontFamily: "inherit",
  },
  secondaryBtn: {
    width: "100%", padding: "13px", borderRadius: 14,
    border: "1px solid rgba(255,255,255,0.1)",
    background: "rgba(255,255,255,0.05)",
    color: "#b4acd0", fontWeight: 700, fontSize: 14, cursor: "pointer",
    fontFamily: "inherit",
  },
};
