import { useEffect, useState } from "react";

import { smartFetch } from "../config";

const STATUS_CONFIG = {
  pending:  { color: "#f59e0b", bg: "rgba(245,158,11,0.12)", border: "rgba(245,158,11,0.3)", label: "⏳ Pending"  },
  paid:     { color: "#22c55e", bg: "rgba(34,197,94,0.12)",  border: "rgba(34,197,94,0.3)",  label: "✅ Paid"     },
  rejected: { color: "#ef4444", bg: "rgba(239,68,68,0.12)",  border: "rgba(239,68,68,0.3)",  label: "❌ Rejected" },
};

export default function AdminWithdrawals() {
  const [withdrawals, setWithdrawals] = useState([]);
  const [loading, setLoading] = useState(true);
  const [processingId, setProcessingId] = useState(null);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("all");

  const loadWithdrawals = async () => {
    try {
      setLoading(true);
      setError("");
      const res = await smartFetch(`/admin/withdrawals`);
      const data = await res.json();
      setWithdrawals(data.withdrawals || []);
    } catch (err) {
      console.log(err);
      setError("Failed to load withdrawals");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadWithdrawals(); }, []);

  const markPaid = async (id) => {
    setProcessingId(id);
    try {
      const res = await smartFetch(`/admin/withdrawals/${id}/paid`, { method: "POST" });
      const data = await res.json();
      if (data.status === "paid") {
        setWithdrawals((prev) => prev.map((w) => w.id === id ? { ...w, status: "paid" } : w));
      }
    } catch (err) { console.log(err); }
    finally { setProcessingId(null); }
  };

  const reject = async (id) => {
    setProcessingId(id);
    try {
      const res = await smartFetch(`/admin/withdrawals/${id}/reject`, { method: "POST" });
      const data = await res.json();
      if (data.status === "rejected") {
        setWithdrawals((prev) => prev.map((w) => w.id === id ? { ...w, status: "rejected" } : w));
      }
    } catch (err) { console.log(err); }
    finally { setProcessingId(null); }
  };

  const filtered = filter === "all" ? withdrawals : withdrawals.filter((w) => (w.status || "pending") === filter);
  const counts = {
    all: withdrawals.length,
    pending: withdrawals.filter((w) => (w.status || "pending") === "pending").length,
    paid: withdrawals.filter((w) => w.status === "paid").length,
    rejected: withdrawals.filter((w) => w.status === "rejected").length,
  };
  const totalPending = withdrawals
    .filter((w) => (w.status || "pending") === "pending")
    .reduce((sum, w) => sum + Number(w.amount || 0), 0);

  return (
    <div style={styles.container}>

      {/* HEADER */}
      <div style={styles.header}>
        <div style={styles.headerBadge}>🛠 Admin Panel</div>
        <h1 style={styles.title}>Withdrawal Requests</h1>
        <p style={styles.subtitle}>Review and process agent withdrawal requests</p>
      </div>

      {/* STATS ROW */}
      <div style={styles.statsRow}>
        <div style={styles.statCard}>
          <div style={styles.statIcon}>📋</div>
          <div style={styles.statVal}>{counts.all}</div>
          <div style={styles.statLabel}>Total</div>
        </div>
        <div style={{ ...styles.statCard, borderColor: "rgba(245,158,11,0.3)" }}>
          <div style={styles.statIcon}>⏳</div>
          <div style={{ ...styles.statVal, color: "#f59e0b" }}>{counts.pending}</div>
          <div style={styles.statLabel}>Pending</div>
        </div>
        <div style={{ ...styles.statCard, borderColor: "rgba(34,197,94,0.3)" }}>
          <div style={styles.statIcon}>✅</div>
          <div style={{ ...styles.statVal, color: "#22c55e" }}>{counts.paid}</div>
          <div style={styles.statLabel}>Paid</div>
        </div>
        <div style={{ ...styles.statCard, borderColor: "rgba(239,68,68,0.3)" }}>
          <div style={styles.statIcon}>❌</div>
          <div style={{ ...styles.statVal, color: "#ef4444" }}>{counts.rejected}</div>
          <div style={styles.statLabel}>Rejected</div>
        </div>
      </div>

      {/* PENDING TOTAL */}
      {totalPending > 0 && (
        <div style={styles.pendingBanner}>
          <span>⚠️ Total pending payout:</span>
          <span style={styles.pendingAmt}>GH₵ {totalPending.toFixed(2)}</span>
        </div>
      )}

      {/* FILTER + REFRESH ROW */}
      <div style={styles.filterRow}>
        <div style={styles.filterTabs}>
          {["all", "pending", "paid", "rejected"].map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              style={{
                ...styles.filterTab,
                background: filter === f ? "rgba(200,255,62,0.15)" : "rgba(255,255,255,0.04)",
                color: filter === f ? "#c8ff3e" : "#9189b5",
                border: filter === f ? "1px solid rgba(200,255,62,0.4)" : "1px solid rgba(255,255,255,0.06)",
                fontWeight: filter === f ? 800 : 600,
              }}
            >
              {f.charAt(0).toUpperCase() + f.slice(1)}
              <span style={{
                ...styles.filterCount,
                background: filter === f ? "rgba(200,255,62,0.2)" : "rgba(255,255,255,0.06)",
                color: filter === f ? "#c8ff3e" : "#7a6fa3",
              }}>
                {counts[f]}
              </span>
            </button>
          ))}
        </div>
        <button onClick={loadWithdrawals} style={styles.refreshBtn}>
          🔄 Refresh
        </button>
      </div>

      {/* ERROR */}
      {error && (
        <div style={styles.errorBox}>⚠️ {error}</div>
      )}

      {/* CONTENT */}
      {loading ? (
        <div style={styles.centerBox}>
          <div style={{ fontSize: 36, marginBottom: 10 }}>⏳</div>
          <p style={styles.centerText}>Loading withdrawals...</p>
        </div>
      ) : filtered.length === 0 ? (
        <div style={styles.centerBox}>
          <div style={{ fontSize: 40, marginBottom: 10 }}>📭</div>
          <p style={styles.centerText}>No {filter === "all" ? "" : filter} withdrawal requests</p>
        </div>
      ) : (
        <div style={styles.cardList}>
          {filtered.map((w) => {
            const status = w.status || "pending";
            const sc = STATUS_CONFIG[status] || STATUS_CONFIG.pending;
            const isProcessing = processingId === w.id;

            return (
              <div key={w.id} style={styles.card}>

                {/* CARD HEADER */}
                <div style={styles.cardHeader}>
                  <div style={styles.agentInfo}>
                    <div style={styles.agentAvatar}>
                      {String(w.agent_id || "?").charAt(0).toUpperCase()}
                    </div>
                    <div>
                      <div style={styles.agentId}>Agent #{w.agent_id}</div>
                      <div style={styles.cardId}>Request #{w.id}</div>
                    </div>
                  </div>
                  <div style={{
                    ...styles.statusBadge,
                    background: sc.bg, color: sc.color, border: `1px solid ${sc.border}`,
                  }}>
                    {sc.label}
                  </div>
                </div>

                {/* AMOUNT HIGHLIGHT */}
                <div style={styles.amountRow}>
                  <span style={styles.amountLabel}>Withdrawal Amount</span>
                  <span style={styles.amountVal}>GH₵ {Number(w.amount).toFixed(2)}</span>
                </div>

                {/* BANK DETAILS */}
                <div style={styles.detailsGrid}>
                  <div style={styles.detailItem}>
                    <span style={styles.detailLabel}>🏦 Bank</span>
                    <span style={styles.detailVal}>{w.bank_name || "—"}</span>
                  </div>
                  <div style={styles.detailItem}>
                    <span style={styles.detailLabel}>💳 Account</span>
                    <span style={styles.detailVal}>{w.account_number || "—"}</span>
                  </div>
                  {w.account_name && (
                    <div style={{ ...styles.detailItem, gridColumn: "1 / -1" }}>
                      <span style={styles.detailLabel}>👤 Name</span>
                      <span style={styles.detailVal}>{w.account_name}</span>
                    </div>
                  )}
                  {w.created_at && (
                    <div style={{ ...styles.detailItem, gridColumn: "1 / -1" }}>
                      <span style={styles.detailLabel}>📅 Requested</span>
                      <span style={styles.detailVal}>{new Date(w.created_at).toLocaleString()}</span>
                    </div>
                  )}
                </div>

                {/* ACTIONS */}
                {status === "pending" && (
                  <div style={styles.actions}>
                    <button
                      onClick={() => markPaid(w.id)}
                      disabled={isProcessing}
                      style={{ ...styles.approveBtn, opacity: isProcessing ? 0.6 : 1 }}
                    >
                      {isProcessing ? "⏳ Processing..." : "✅ Mark as Paid"}
                    </button>
                    <button
                      onClick={() => reject(w.id)}
                      disabled={isProcessing}
                      style={{ ...styles.rejectBtn, opacity: isProcessing ? 0.6 : 1 }}
                    >
                      ❌ Reject
                    </button>
                  </div>
                )}

                {status !== "pending" && (
                  <div style={styles.resolvedNote}>
                    {status === "paid" ? "✅ This request has been paid out." : "❌ This request was rejected."}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

const styles = {
  container: {
    padding: "28px 18px 80px",
    maxWidth: 680,
    margin: "0 auto",
    color: "#e5e7eb",
    fontFamily: "ui-sans-serif, system-ui, Arial",
  },

  // HEADER
  header: { textAlign: "center", marginBottom: 24 },
  headerBadge: {
    display: "inline-block", padding: "5px 18px", borderRadius: 50,
    background: "rgba(200,255,62,0.15)", border: "1px solid rgba(200,255,62,0.3)",
    color: "#c8ff3e", fontSize: 12, fontWeight: 800, marginBottom: 10, letterSpacing: "0.5px",
  },
  title: { fontSize: 26, fontWeight: 900, color: "#f3f0fb", margin: "0 0 6px" },
  subtitle: { fontSize: 13, color: "#9189b5", margin: 0, fontWeight: 600 },

  // STATS
  statsRow: { display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 10, marginBottom: 16 },
  statCard: {
    background: "rgba(22,17,38,0.8)", border: "1px solid rgba(255,255,255,0.07)",
    borderRadius: 16, padding: "14px 10px", textAlign: "center",
  },
  statIcon: { fontSize: 20, marginBottom: 6 },
  statVal: { fontWeight: 900, fontSize: 20, color: "#f3f0fb", marginBottom: 2 },
  statLabel: { fontSize: 11, color: "#7a6fa3", fontWeight: 700 },

  // PENDING BANNER
  pendingBanner: {
    display: "flex", justifyContent: "space-between", alignItems: "center",
    background: "rgba(245,158,11,0.08)", border: "1px solid rgba(245,158,11,0.25)",
    borderRadius: 14, padding: "12px 16px", marginBottom: 16,
    fontSize: 13, color: "#f59e0b", fontWeight: 700,
  },
  pendingAmt: { fontSize: 18, fontWeight: 900 },

  // FILTER ROW
  filterRow: { display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, marginBottom: 16, flexWrap: "wrap" },
  filterTabs: { display: "flex", gap: 6, flexWrap: "wrap" },
  filterTab: {
    padding: "7px 12px", borderRadius: 50, fontSize: 12,
    cursor: "pointer", display: "flex", alignItems: "center", gap: 6, transition: "all 0.2s",
  },
  filterCount: { fontSize: 11, fontWeight: 800, padding: "1px 6px", borderRadius: 50 },
  refreshBtn: {
    padding: "8px 16px", borderRadius: 10,
    background: "rgba(200,255,62,0.12)", border: "1px solid rgba(200,255,62,0.25)",
    color: "#c8ff3e", fontWeight: 800, fontSize: 13, cursor: "pointer",
  },

  // ERROR
  errorBox: {
    background: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.3)",
    color: "#f87171", padding: "12px 16px", borderRadius: 12,
    marginBottom: 16, fontSize: 14, fontWeight: 600, textAlign: "center",
  },

  // EMPTY / LOADING
  centerBox: { textAlign: "center", padding: "48px 0" },
  centerText: { fontSize: 14, color: "#7a6fa3", fontWeight: 600, margin: 0 },

  // CARDS
  cardList: { display: "flex", flexDirection: "column", gap: 14 },
  card: {
    background: "rgba(22,17,38,0.9)", backdropFilter: "blur(16px)",
    WebkitBackdropFilter: "blur(16px)", borderRadius: 20,
    border: "1px solid rgba(255,255,255,0.07)",
    boxShadow: "0 4px 24px rgba(0,0,0,0.3)", overflow: "hidden",
  },

  cardHeader: {
    display: "flex", justifyContent: "space-between", alignItems: "center",
    padding: "16px 18px 12px", borderBottom: "1px solid rgba(255,255,255,0.05)",
  },
  agentInfo: { display: "flex", alignItems: "center", gap: 12 },
  agentAvatar: {
    width: 40, height: 40, borderRadius: "50%",
    background: "linear-gradient(135deg, #c8ff3e, #8b5cf6)",
    display: "flex", alignItems: "center", justifyContent: "center",
    fontWeight: 900, fontSize: 16, color: "white",
  },
  agentId: { fontWeight: 800, fontSize: 15, color: "#f3f0fb" },
  cardId: { fontSize: 11, color: "#7a6fa3", fontWeight: 600, marginTop: 2 },
  statusBadge: { fontSize: 12, fontWeight: 800, padding: "4px 12px", borderRadius: 50 },

  amountRow: {
    display: "flex", justifyContent: "space-between", alignItems: "center",
    padding: "14px 18px", background: "rgba(10,8,20,0.4)",
    borderBottom: "1px solid rgba(255,255,255,0.05)",
  },
  amountLabel: { fontSize: 12, color: "#9189b5", fontWeight: 700 },
  amountVal: { fontSize: 22, fontWeight: 900, color: "#c8ff3e" },

  detailsGrid: {
    display: "grid", gridTemplateColumns: "1fr 1fr",
    gap: 0, padding: "4px 18px 10px",
  },
  detailItem: { padding: "8px 0", borderBottom: "1px solid rgba(255,255,255,0.04)" },
  detailLabel: { display: "block", fontSize: 11, color: "#7a6fa3", fontWeight: 700, marginBottom: 3 },
  detailVal: { fontSize: 13, color: "#e5e7eb", fontWeight: 600 },

  actions: { display: "flex", gap: 10, padding: "14px 18px 18px" },
  approveBtn: {
    flex: 1, padding: "12px", borderRadius: 12, border: "none",
    background: "linear-gradient(135deg, #22c55e, #16a34a)",
    color: "white", fontWeight: 900, fontSize: 14, cursor: "pointer",
    boxShadow: "0 4px 16px rgba(34,197,94,0.3)",
  },
  rejectBtn: {
    flex: 1, padding: "12px", borderRadius: 12,
    background: "rgba(239,68,68,0.1)", border: "1.5px solid rgba(239,68,68,0.3)",
    color: "#f87171", fontWeight: 900, fontSize: 14, cursor: "pointer",
  },

  resolvedNote: {
    padding: "12px 18px 16px", fontSize: 13, color: "#7a6fa3",
    fontWeight: 600, textAlign: "center",
  },
};
