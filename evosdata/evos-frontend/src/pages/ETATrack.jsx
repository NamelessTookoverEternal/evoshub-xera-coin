import { useState } from "react";
import { withBase } from "../lib/basePath";

import { smartFetch } from "../config";

const SESSION_KEY = "evos_store_state";

const STATUS_CONFIG = {
  pending_payment: {
    label: "Awaiting Payment",
    color: "#f59e0b",
    bg: "rgba(245,158,11,0.1)",
    border: "rgba(245,158,11,0.3)",
    eta: "Complete your payment to proceed.",
    icon: "⏳",
  },
  paid: {
    label: "Payment Confirmed",
    color: "#c8ff3e",
    bg: "rgba(200,255,62,0.1)",
    border: "rgba(200,255,62,0.3)",
    eta: "Your order is queued for delivery. Usually starts within 1-2 minutes.",
    icon: "✅",
  },
  processing: {
    label: "Processing",
    color: "#a78bfa",
    bg: "rgba(167,139,250,0.1)",
    border: "rgba(167,139,250,0.3)",
    eta: "Data bundle is being delivered. Usually arrives within 5-30 minutes.",
    icon: "📡",
  },
  successful: {
    label: "Delivered",
    color: "#22c55e",
    bg: "rgba(34,197,94,0.1)",
    border: "rgba(34,197,94,0.3)",
    eta: "Your data bundle has been delivered successfully.",
    icon: "🎉",
  },
  failed: {
    label: "Failed",
    color: "#ef4444",
    bg: "rgba(239,68,68,0.1)",
    border: "rgba(239,68,68,0.3)",
    eta: "Delivery attempt failed. The system will automatically retry delivery within 24 hours. No action needed.",
    icon: "❌",
  },
};

function formatDate(dateStr) {
  if (!dateStr) return "—";
  const d = new Date(dateStr);
  return d.toLocaleString("en-GH", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// Read saved store session
function getStoreSession() {
  try {
    const raw = sessionStorage.getItem(SESSION_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch (_) {
    return null;
  }
}

export default function ETATrack({ setPage, backTo = "home" }) {
  const [phone, setPhone] = useState("");
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [searched, setSearched] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);

  // Read store session — used to build the correct back label and action
  const storeSession = getStoreSession();
  const hasStoreSession = !!storeSession?.agentId;

  const search = async () => {
    setError("");
    setOrders([]);
    setSearched(false);

    const cleaned = phone.trim();
    if (!cleaned || cleaned.length < 9) {
      setError("Enter a valid phone number");
      return;
    }

    setLoading(true);
    try {
      const res = await smartFetch(`/orders/track?phone=${encodeURIComponent(cleaned)}`);
      const data = await res.json();

      if (data.orders && data.orders.length > 0) {
        setOrders(data.orders);
      } else {
        setError("No orders found for this number.");
      }
      setSearched(true);
    } catch (e) {
      setError("Network error. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  const handleBack = () => {
    if (hasStoreSession) {
      // Restore exact URL and page — StorePage will read the session and restore step/network
      const { agentId } = storeSession;
      window.history.pushState({}, "", withBase(`/store/${agentId}`));
      setPage("store");
    } else {
      // No store session — fall back to home or whatever backTo says
      setPage(backTo === "store" ? "home" : backTo);
    }
  };

  // Build a meaningful back label
  const backLabel = hasStoreSession
    ? "← Back to Store"
    : backTo === "home"
    ? "← Back to Home"
    : backTo === "dashboard"
    ? "← Back to Dashboard"
    : "← Back";

  return (
    <div style={styles.wrap}>
      <h2 style={styles.title}>Track Your Order</h2>
      <p style={styles.sub}>Enter the phone number used during purchase</p>

      {/* BACK + NEED HELP */}
      <div style={styles.topActions}>
        {setPage && (
          <button style={styles.backBtnTop} onClick={handleBack}>
            {backLabel}
          </button>
        )}
        <button
          style={styles.helpBtnTop}
          onClick={() => setChatOpen(!chatOpen)}
        >
          💬 Need Help?
        </button>
      </div>

      {/* SEARCH */}
      <div style={styles.searchBox}>
        <input
          type="tel"
          placeholder="e.g. 0244000000"
          value={phone}
          onChange={(e) => setPhone(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && search()}
          style={styles.input}
        />
        <button
          onClick={search}
          disabled={loading}
          style={{ ...styles.searchBtn, opacity: loading ? 0.6 : 1 }}
        >
          {loading ? "..." : "Track"}
        </button>
      </div>

      {/* ERROR */}
      {error && <div style={styles.errorBox}>{error}</div>}

      {/* RESULTS */}
      {orders.map((order, i) => {
        const status = order.status || "processing";
        const cfg = STATUS_CONFIG[status] || STATUS_CONFIG.processing;

        return (
          <div key={i} style={styles.card}>

            {/* STATUS BADGE */}
            <div style={{
              ...styles.statusBadge,
              background: cfg.bg,
              border: `1px solid ${cfg.border}`,
              color: cfg.color,
            }}>
              <span style={styles.statusIcon}>{cfg.icon}</span>
              <span style={styles.statusLabel}>{cfg.label}</span>
            </div>

            {/* ORDER DETAILS */}
            <div style={styles.detailGrid}>
              <div style={styles.detailRow}>
                <span style={styles.detailLabel}>Network</span>
                <span style={styles.detailVal}>{order.network}</span>
              </div>
              <div style={styles.detailRow}>
                <span style={styles.detailLabel}>Bundle</span>
                <span style={styles.detailVal}>{order.bundle}</span>
              </div>
              <div style={styles.detailRow}>
                <span style={styles.detailLabel}>Amount Paid</span>
                <span style={{ ...styles.detailVal, color: "#c8ff3e", fontWeight: 800 }}>
                  GH&#8373; {Number(order.price || 0).toFixed(2)}
                </span>
              </div>
              <div style={styles.detailRow}>
                <span style={styles.detailLabel}>Phone</span>
                <span style={styles.detailVal}>{order.phone_number}</span>
              </div>
              <div style={styles.detailRow}>
                <span style={styles.detailLabel}>Time Placed</span>
                <span style={styles.detailVal}>{formatDate(order.created_at)}</span>
              </div>
              <div style={{ ...styles.detailRow, borderBottom: "none" }}>
                <span style={styles.detailLabel}>Reference</span>
                <span style={{ ...styles.detailVal, fontSize: 11, color: "#9189b5" }}>
                  {order.evosdata_ref || order.paystack_ref || "—"}
                </span>
              </div>
            </div>

            {/* ETA */}
            <div style={{
              ...styles.etaBox,
              background: cfg.bg,
              border: `1px solid ${cfg.border}`,
            }}>
              <p style={{ ...styles.etaText, color: cfg.color }}>
                {cfg.eta}
              </p>
            </div>

          </div>
        );
      })}

      {/* FLOATING WHATSAPP SUPPORT */}
      <div style={styles.floatWrap}>
        {chatOpen && (
          <div style={styles.chatPopup}>
            <div style={styles.chatHeader}>
              <span>💬 EVOS Support</span>
              <button style={styles.chatClose} onClick={() => setChatOpen(false)}>
                ✕
              </button>
            </div>
            <p style={styles.chatMsg}>
              Hi! Need help with your order? Chat with us on WhatsApp and we'll sort it out quickly. 👇
            </p>
            <button
              style={styles.chatBtn}
              onClick={() => window.open("https://wa.me/233537314125", "_blank")}
            >
              Open WhatsApp Chat
            </button>
          </div>
        )}

        <button
          style={styles.floatBtn}
          onClick={() => setChatOpen(!chatOpen)}
        >
          {chatOpen ? "✕" : "💬"}
        </button>
      </div>
    </div>
  );
}

const styles = {
  wrap: {
    maxWidth: 480,
    margin: "0 auto",
    padding: "24px 18px 80px",
    color: "#e5e7eb",
    fontFamily: "ui-sans-serif, system-ui, Arial",
  },
  title: {
    fontSize: 24,
    fontWeight: 900,
    margin: "0 0 6px",
    textAlign: "center",
  },
  sub: {
    color: "#b4acd0",
    fontSize: 13,
    textAlign: "center",
    marginBottom: 16,
  },
  topActions: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 14,
    gap: 10,
  },
  backBtnTop: {
    background: "none",
    border: "none",
    color: "#c8ff3e",
    fontSize: 13,
    fontWeight: 700,
    cursor: "pointer",
    padding: 0,
  },
  helpBtnTop: {
    background: "rgba(37,211,102,0.1)",
    border: "1px solid rgba(37,211,102,0.3)",
    color: "#25D366",
    fontSize: 13,
    fontWeight: 700,
    cursor: "pointer",
    padding: "6px 12px",
    borderRadius: 8,
  },
  searchBox: {
    display: "flex",
    gap: 10,
    marginBottom: 16,
  },
  input: {
    flex: 1,
    padding: "13px 14px",
    borderRadius: 12,
    border: "1px solid rgba(255,255,255,0.1)",
    background: "rgba(10,8,20,0.75)",
    color: "white",
    fontSize: 15,
    outline: "none",
  },
  searchBtn: {
    padding: "13px 20px",
    borderRadius: 12,
    border: "none",
    background: "linear-gradient(135deg,#c8ff3e,#8fe600)",
    color: "#000",
    fontWeight: 900,
    fontSize: 14,
    cursor: "pointer",
    flexShrink: 0,
  },
  errorBox: {
    background: "rgba(239,68,68,0.1)",
    border: "1px solid rgba(239,68,68,0.3)",
    color: "#f87171",
    padding: "12px 14px",
    borderRadius: 10,
    fontSize: 13,
    marginBottom: 14,
  },
  card: {
    background: "rgba(22,17,38,0.88)",
    backdropFilter: "blur(16px)",
    WebkitBackdropFilter: "blur(16px)",
    borderRadius: 18,
    padding: "18px 16px",
    border: "1px solid rgba(255,255,255,0.07)",
    marginBottom: 16,
    boxShadow: "0 8px 32px rgba(0,0,0,0.3)",
  },
  statusBadge: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    padding: "10px 14px",
    borderRadius: 10,
    marginBottom: 16,
  },
  statusIcon: { fontSize: 18 },
  statusLabel: { fontWeight: 800, fontSize: 14 },
  detailGrid: {
    background: "rgba(10,8,20,0.5)",
    borderRadius: 12,
    padding: "4px 14px",
    marginBottom: 14,
    border: "1px solid rgba(255,255,255,0.05)",
  },
  detailRow: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    padding: "10px 0",
    borderBottom: "1px solid rgba(255,255,255,0.05)",
  },
  detailLabel: { fontSize: 12, color: "#9189b5" },
  detailVal: { fontSize: 13, fontWeight: 600, color: "#e5e7eb" },
  etaBox: { padding: "10px 14px", borderRadius: 10 },
  etaText: { fontSize: 12, margin: 0, lineHeight: 1.55, fontWeight: 500 },
  floatWrap: {
    position: "fixed",
    bottom: 24,
    right: 20,
    zIndex: 9999,
    display: "flex",
    flexDirection: "column",
    alignItems: "flex-end",
    gap: 10,
  },
  chatPopup: {
    background: "#161126",
    border: "1px solid rgba(255,255,255,0.1)",
    borderRadius: 16,
    padding: "16px",
    width: 260,
    boxShadow: "0 8px 32px rgba(0,0,0,0.5)",
  },
  chatHeader: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 10,
    fontWeight: 700,
    fontSize: 14,
    color: "#e5e7eb",
  },
  chatClose: {
    background: "none",
    border: "none",
    color: "#9189b5",
    cursor: "pointer",
    fontSize: 14,
    padding: "2px 6px",
  },
  chatMsg: {
    fontSize: 13,
    color: "#b4acd0",
    lineHeight: 1.55,
    margin: "0 0 14px",
  },
  chatBtn: {
    width: "100%",
    padding: "10px",
    borderRadius: 10,
    border: "none",
    background: "linear-gradient(135deg,#25D366,#128C7E)",
    color: "white",
    fontWeight: 800,
    fontSize: 13,
    cursor: "pointer",
  },
  floatBtn: {
    width: 52,
    height: 52,
    borderRadius: "50%",
    background: "linear-gradient(135deg,#25D366,#128C7E)",
    border: "none",
    color: "white",
    fontSize: 22,
    cursor: "pointer",
    boxShadow: "0 4px 20px rgba(37,211,102,0.5)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
  },
};
