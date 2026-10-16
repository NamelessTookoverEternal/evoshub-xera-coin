import { useEffect, useState } from "react";

import { smartFetch } from "../config";

const agentHeaders = () => ({
  "Content-Type": "application/json",
  "X-Agent-Token": sessionStorage.getItem("agentToken") || "",
});

const CHECKER_CONFIG = {
  WAEC: { emoji: "🟢", color: "#16a34a", accent: "#22c55e", bg: "#f0fdf4", border: "#86efac", label: "WAEC", desc: "West African Senior School Certificate result checker" },
  BECE: { emoji: "📘", color: "#1d4ed8", accent: "#3b82f6", bg: "#eff6ff", border: "#93c5fd", label: "BECE", desc: "Basic Education Certificate Examination result checker" },
};

export default function AgentCheckerPricing({ user, setPage }) {
  const [loading, setLoading] = useState(true);
  const [rows, setRows] = useState([]);
  const [savingType, setSavingType] = useState(null);
  const [savedType, setSavedType] = useState(null);
  const [savingAll, setSavingAll] = useState(false);
  const [savedAll, setSavedAll] = useState(false);

  useEffect(() => {
    if (!user) { setPage("login"); return; }
    if (user.role !== "agent" || user.agent_status !== "approved") setPage("dashboard");
  }, [user, setPage]);

  const loadPricing = async () => {
    if (!user?.id) return;
    try {
      setLoading(true);
      const res = await smartFetch(`/agent/checker-pricing/${user.id}`, {
        headers: agentHeaders(),
      });
      if (!res.ok) throw new Error("Failed to fetch checker pricing");
      const data = await res.json();
      setRows(data.prices || []);
    } catch (err) {
      console.log("Checker pricing load error:", err);
      setRows([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadPricing(); }, [user]);

  const updateMarkup = (checkerType, value) => {
    let markup = Number(value || 0);
    if (markup < 0) markup = 0;
    setRows((prev) =>
      prev.map((r) =>
        r.checker_type === checkerType
          ? { ...r, markup, final_price: Number(r.base_price || 0) + markup }
          : r
      )
    );
  };

  const saveOne = async (item) => {
    try {
      setSavingType(item.checker_type);
      const res = await smartFetch(`/agent/checker-pricing/save`, {
        method: "POST",
        headers: agentHeaders(),
        body: JSON.stringify({ agent_id: user.id, prices: [item] }),
      });
      const data = await res.json();
      if (data.status === "success") {
        setSavedType(item.checker_type);
        setTimeout(() => setSavedType(null), 2000);
      } else {
        alert(data.message || "Failed to save");
      }
    } catch { alert("Network error"); }
    finally { setSavingType(null); }
  };

  const saveAll = async () => {
    try {
      setSavingAll(true);
      const res = await smartFetch(`/agent/checker-pricing/save`, {
        method: "POST",
        headers: agentHeaders(),
        body: JSON.stringify({ agent_id: user.id, prices: rows }),
      });
      const data = await res.json();
      if (data.status === "success") {
        setSavedAll(true);
        setTimeout(() => setSavedAll(false), 2500);
      } else {
        alert(data.message || "Failed to save pricing");
      }
    } catch { alert("Network error"); }
    finally { setSavingAll(false); }
  };

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <div style={styles.headerBadge}>🎓 Checker Pricing</div>
        <h2 style={styles.title}>Set Your Checker Prices</h2>
        <p style={styles.subtitle}>Base Price + Your Markup = Customer Price</p>
      </div>

      <div style={styles.infoBanner}>
        <span style={styles.infoIcon}>ℹ️</span>
        <span style={styles.infoText}>
          You pay <strong>GH₵ {rows[0] ? Number(rows[0].base_price).toFixed(2) : "16.80"}</strong> per card.
          Set your markup to earn a margin when you sell to customers.
        </span>
      </div>

      <div style={styles.wrapper}>
        <div style={styles.box}>
          {loading ? (
            <div style={styles.emptyBox}>
              <div style={{ fontSize: 32, marginBottom: 8 }}>⏳</div>
              <p style={styles.emptyText}>Loading your pricing...</p>
            </div>
          ) : (
            <div style={styles.checkerGrid}>
              {rows.map((item) => {
                const cfg = CHECKER_CONFIG[item.checker_type] || {};
                const hasMarkup = Number(item.markup) > 0;
                const isSaving = savingType === item.checker_type;
                const isSaved = savedType === item.checker_type;
                return (
                  <div key={item.checker_type} style={{ ...styles.checkerCard, background: cfg.bg, border: `2px solid ${hasMarkup ? cfg.border : "#e5e7eb"}` }}>
                    <div style={{ ...styles.visibilityBadge, background: hasMarkup ? "#dcfce7" : "#fef2f2", color: hasMarkup ? "#16a34a" : "#dc2626", border: `1px solid ${hasMarkup ? "#86efac" : "#fca5a5"}` }}>
                      {hasMarkup ? "👁 Visible" : "🚫 Hidden"}
                    </div>
                    <div style={{ fontSize: 30 }}>{cfg.emoji}</div>
                    <div style={{ ...styles.checkerName, color: cfg.color }}>{cfg.label}</div>
                    <div style={styles.checkerDesc}>{cfg.desc}</div>
                    <div style={styles.basePrice}>Base: GH₵ {Number(item.base_price).toFixed(2)}</div>
                    <div style={{ ...styles.divider, background: cfg.border }} />
                    <label style={{ ...styles.markupLabel, color: cfg.accent }}>Your Markup (GH₵)</label>
                    <input
                      type="number" min="0" step="0.01" value={item.markup}
                      onChange={(e) => updateMarkup(item.checker_type, e.target.value)}
                      style={{ ...styles.markupInput, border: `1.5px solid ${cfg.border}` }}
                      placeholder="0.00"
                    />
                    <div style={{ ...styles.finalPrice, color: cfg.accent }}>
                      Customer pays: <strong>GH₵ {Number(item.final_price).toFixed(2)}</strong>
                    </div>
                    <button
                      onClick={() => saveOne(item)}
                      disabled={isSaving}
                      style={{ ...styles.saveSingleBtn, background: isSaved ? "linear-gradient(135deg, #22c55e, #16a34a)" : `linear-gradient(135deg, ${cfg.accent}, ${cfg.accent}cc)`, opacity: isSaving ? 0.6 : 1 }}
                    >
                      {isSaving ? "⏳ Saving..." : isSaved ? "✓ Saved!" : "Save →"}
                    </button>
                  </div>
                );
              })}
            </div>
          )}

          <button onClick={saveAll} disabled={savingAll || loading} style={{ ...styles.saveAllBtn, opacity: savingAll ? 0.65 : 1, background: savedAll ? "linear-gradient(135deg, #22c55e, #16a34a)" : "linear-gradient(135deg, #c8ff3e, #8fe600)" }}>
            {savingAll ? "⏳ Saving All..." : savedAll ? "✓ All Prices Saved!" : "💾 Save All Prices"}
          </button>

          <button style={styles.backDashBtn} onClick={() => setPage("agent-dashboard")}>← Back to Dashboard</button>
        </div>
      </div>
    </div>
  );
}

const styles = {
  container: { padding: "28px 18px 80px", minHeight: "auto", fontFamily: "'Nunito', 'Poppins', ui-rounded, system-ui, Arial", color: "#241c3d" },
  header: { textAlign: "center", marginBottom: 20 },
  headerBadge: { display: "inline-block", padding: "5px 18px", borderRadius: 50, background: "linear-gradient(135deg, #dcfce7, #bbf7d0)", border: "1px solid #86efac", color: "#15803d", fontSize: 12, fontWeight: 800, marginBottom: 10, letterSpacing: "0.5px" },
  title: { fontSize: 26, fontWeight: 900, color: "#f3f0fb", margin: "0 0 6px", letterSpacing: "-0.5px" },
  subtitle: { fontSize: 13, color: "#9189b5", margin: 0, fontWeight: 600 },
  infoBanner: { display: "flex", alignItems: "flex-start", gap: 10, background: "rgba(234,179,8,0.1)", border: "1.5px solid rgba(234,179,8,0.3)", borderRadius: 14, padding: "12px 16px", maxWidth: 480, margin: "0 auto 20px", fontSize: 13, color: "#ca8a04" },
  infoIcon: { fontSize: 16, flexShrink: 0, marginTop: 1 },
  infoText: { lineHeight: 1.55, fontWeight: 600 },
  wrapper: { maxWidth: 520, margin: "0 auto" },
  box: { background: "rgba(22,17,38,0.85)", backdropFilter: "blur(20px)", WebkitBackdropFilter: "blur(20px)", padding: "24px 20px", borderRadius: 24, border: "1px solid rgba(255,255,255,0.07)", boxShadow: "0 8px 40px rgba(0,0,0,0.3)" },
  emptyBox: { textAlign: "center", padding: "30px 0" },
  emptyText: { color: "#9189b5", fontSize: 14, margin: 0, fontWeight: 600 },
  checkerGrid: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 16 },
  checkerCard: { borderRadius: 18, padding: "16px 14px 14px", display: "flex", flexDirection: "column", alignItems: "center", gap: 0, textAlign: "center", position: "relative" },
  visibilityBadge: { fontSize: 10, fontWeight: 800, padding: "3px 8px", borderRadius: 50, marginBottom: 8, letterSpacing: "0.3px" },
  checkerName: { fontWeight: 900, fontSize: 17, margin: "4px 0 2px", letterSpacing: "-0.3px" },
  checkerDesc: { fontSize: 10.5, color: "#9189b5", fontWeight: 600, marginBottom: 8, lineHeight: 1.4 },
  basePrice: { fontSize: 11, color: "#9189b5", fontWeight: 600, marginBottom: 8 },
  divider: { width: "50%", height: 2, borderRadius: 10, marginBottom: 10, opacity: 0.4 },
  markupLabel: { fontSize: 11, fontWeight: 800, marginBottom: 4, letterSpacing: "0.3px", alignSelf: "flex-start" },
  markupInput: { width: "100%", padding: "10px 12px", borderRadius: 12, background: "white", color: "#161126", fontSize: 14, fontWeight: 700, marginBottom: 8, boxSizing: "border-box", outline: "none", textAlign: "center" },
  finalPrice: { fontSize: 12, fontWeight: 700, marginBottom: 12 },
  saveAllBtn: { width: "100%", padding: "15px", borderRadius: 16, border: "none", color: "white", fontWeight: 900, fontSize: 15, cursor: "pointer", boxShadow: "0 6px 24px rgba(200,255,62,0.3)", marginTop: 4, letterSpacing: "0.2px", transition: "all 0.3s" },
  saveSingleBtn: { width: "100%", padding: "10px", borderRadius: 12, border: "none", color: "white", fontWeight: 900, fontSize: 13, cursor: "pointer", boxShadow: "0 4px 12px rgba(0,0,0,0.2)", transition: "all 0.3s" },
  backDashBtn: { width: "100%", padding: "12px", borderRadius: 14, background: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.1)", color: "#b4acd0", fontWeight: 700, fontSize: 13, cursor: "pointer", marginTop: 12 },
};
