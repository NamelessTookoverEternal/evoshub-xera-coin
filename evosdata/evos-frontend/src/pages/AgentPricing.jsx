import { useEffect, useState } from "react";

import { smartFetch } from "../config";

const agentHeaders = () => ({
  "Content-Type": "application/json",
  "X-Agent-Token": sessionStorage.getItem("agentToken") || "",
});

const NETWORK_CONFIG = {
  MTN: { emoji: "🟡", color: "#b45309", accentColor: "#f59e0b", bg: "linear-gradient(135deg, #fffbeb, #fef3c7)", border: "#fcd34d", shadow: "0 4px 20px rgba(245,158,11,0.2)" },
  TELECEL: { emoji: "🔴", color: "#991b1b", accentColor: "#ef4444", bg: "linear-gradient(135deg, #fff5f5, #fee2e2)", border: "#fca5a5", shadow: "0 4px 20px rgba(239,68,68,0.15)" },
  AIRTELTIGO: { emoji: "🔵", color: "#3730a3", accentColor: "#8b5cf6", bg: "linear-gradient(135deg, #f0f1ff, #e0e7ff)", border: "#a5b4fc", shadow: "0 4px 20px rgba(139,92,246,0.15)" },
};

const bundleAccents = [
  { bg: "#f0fdf4", border: "#86efac", accent: "#16a34a", text: "#14532d" },
  { bg: "#eff6ff", border: "#93c5fd", accent: "#2563eb", text: "#1e3a8a" },
  { bg: "#fdf4ff", border: "#d8b4fe", accent: "#9333ea", text: "#581c87" },
  { bg: "#fff7ed", border: "#fdba74", accent: "#ea580c", text: "#7c2d12" },
  { bg: "#f0fdfa", border: "#6ee7b7", accent: "#059669", text: "#064e3b" },
  { bg: "#fef2f2", border: "#fca5a5", accent: "#dc2626", text: "#7f1d1d" },
];

export default function AgentPricing({ user, setPage }) {
  const [loading, setLoading] = useState(true);
  const [rows, setRows] = useState([]);
  const [savingIndex, setSavingIndex] = useState(null);
  const [savedIndex, setSavedIndex] = useState(null);
  const [savingAll, setSavingAll] = useState(false);
  const [savedAll, setSavedAll] = useState(false);
  const [step, setStep] = useState(1);
  const [selectedNetwork, setSelectedNetwork] = useState("");

  useEffect(() => {
    if (!user) { setPage("login"); return; }
    if (user.role !== "agent" || user.agent_status !== "approved") setPage("dashboard");
  }, [user, setPage]);

  const loadPricing = async () => {
    if (!user?.id) return;
    try {
      setLoading(true);
      const res = await smartFetch(`/agent/pricing/${user.id}`, {
        headers: agentHeaders(),
      });
      if (!res.ok) throw new Error("Failed to fetch pricing");
      const data = await res.json();
      const normalized = (data.prices || []).map((item) => {
        const base = Number(item.base_price || 0);
        const markup = Number(item.markup || 0);
        return { ...item, markup, final_price: base + markup };
      });
      setRows(normalized);
    } catch (err) {
      console.log("Pricing load error:", err);
      setRows([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadPricing(); }, [user]);

  const updateMarkup = (index, value) => {
    const copy = [...rows];
    let markup = Number(value || 0);
    if (markup < 0) markup = 0;
    copy[index].markup = markup;
    copy[index].final_price = Number(copy[index].base_price || 0) + markup;
    setRows(copy);
  };

  const saveSingle = async (index) => {
    const item = rows[index];
    try {
      setSavingIndex(index);
      const res = await smartFetch(`/agent/pricing/save`, {
        method: "POST",
        headers: agentHeaders(),
        body: JSON.stringify({ agent_id: user.id, prices: [item] }),
      });
      const data = await res.json();
      if (data.status === "success") {
        setSavedIndex(index);
        setTimeout(() => setSavedIndex(null), 2000);
      } else {
        alert(data.message || "Failed to save");
      }
    } catch { alert("Network error"); }
    finally { setSavingIndex(null); }
  };

  const saveAll = async () => {
    try {
      setSavingAll(true);
      const res = await smartFetch(`/agent/pricing/save`, {
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

  const availableNetworks = [...new Set(rows.map((r) => r.network))];
  const networkBundles = rows
    .map((r, originalIndex) => ({ ...r, originalIndex }))
    .filter((r) => r.network === selectedNetwork)
    .sort((a, b) => Number(a.base_price) - Number(b.base_price));
  const cfg = NETWORK_CONFIG[selectedNetwork] || {};

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <div style={styles.headerBadge}>💰 Agent Pricing</div>
        <h2 style={styles.title}>Set Your Bundle Prices</h2>
        <p style={styles.subtitle}>Base Price + Your Markup = Customer Price</p>
      </div>

      <div style={styles.infoBanner}>
        <span style={styles.infoIcon}>ℹ️</span>
        <span style={styles.infoText}>
          Bundles with <strong>no markup set</strong> will be{" "}
          <strong style={{ color: "#dc2626" }}>hidden</strong> from your store.
        </span>
      </div>

      <div style={styles.progressWrap}>
        {["Network", "Set Prices"].map((label, i) => {
          const active = step === i + 1;
          const done = step > i + 1;
          return (
            <div key={i} style={styles.progressItem}>
              <div style={{ ...styles.progressDot, background: done ? "linear-gradient(135deg, #22c55e, #16a34a)" : active ? "linear-gradient(135deg, #8b5cf6, #8b5cf6)" : "#e5e7eb", boxShadow: active ? "0 0 0 4px rgba(139,92,246,0.2)" : done ? "0 0 0 4px rgba(34,197,94,0.15)" : "none", color: done || active ? "white" : "#9ca3af" }}>
                {done ? "✓" : i + 1}
              </div>
              <span style={{ ...styles.progressLabel, color: active ? "#8b5cf6" : done ? "#22c55e" : "#9ca3af", fontWeight: active || done ? 800 : 600 }}>{label}</span>
            </div>
          );
        })}
        <div style={styles.progressLine}>
          <div style={{ ...styles.progressLineFill, width: step === 1 ? "0%" : "100%" }} />
        </div>
      </div>

      <div style={styles.wrapper}>
        {step === 1 && (
          <div style={styles.box}>
            <p style={styles.stepLabel}>Step 1 of 2 · Select Network to Configure</p>
            {loading ? (
              <div style={styles.emptyBox}>
                <div style={{ fontSize: 32, marginBottom: 8 }}>⏳</div>
                <p style={styles.emptyText}>Loading your pricing...</p>
              </div>
            ) : availableNetworks.length === 0 ? (
              <div style={styles.emptyBox}>
                <div style={{ fontSize: 32, marginBottom: 8 }}>📭</div>
                <p style={styles.emptyText}>No bundles found. Contact admin.</p>
              </div>
            ) : (
              <div style={styles.networkGrid}>
                {availableNetworks.map((netKey) => {
                  const c = NETWORK_CONFIG[netKey] || { emoji: "📡", color: "#7a6fa3", accentColor: "#9189b5", bg: "linear-gradient(135deg, #f8fafc, #f3f0fb)", border: "#d9d4ec", shadow: "none" };
                  const netBundles = rows.filter((r) => r.network === netKey);
                  const setPrices = netBundles.filter((r) => Number(r.markup) > 0).length;
                  return (
                    <div key={netKey} style={{ ...styles.networkCard, background: c.bg, border: `2px solid ${c.border}`, boxShadow: c.shadow }} onClick={() => { setSelectedNetwork(netKey); setStep(2); }}>
                      <div style={styles.networkLeft}>
                        <div style={styles.networkEmoji}>{c.emoji}</div>
                        <div>
                          <div style={{ ...styles.networkName, color: c.color }}>{netKey}</div>
                          <div style={styles.networkDesc}>{setPrices}/{netBundles.length} bundles priced</div>
                        </div>
                      </div>
                      <div style={{ ...styles.networkBadge, background: setPrices === netBundles.length ? "#dcfce7" : "#fef9c3", color: setPrices === netBundles.length ? "#16a34a" : "#ca8a04", border: `1px solid ${setPrices === netBundles.length ? "#86efac" : "#fde047"}` }}>
                        {setPrices === netBundles.length ? "✓ All set" : "⚠ Incomplete"}
                      </div>
                      <div style={{ ...styles.networkArrow, color: c.accentColor }}>→</div>
                    </div>
                  );
                })}
              </div>
            )}
            <button style={styles.backDashBtn} onClick={() => setPage("agent-dashboard")}>← Back to Dashboard</button>
          </div>
        )}

        {step === 2 && (
          <div style={styles.box}>
            <button style={styles.backBtn} onClick={() => setStep(1)}>← Back</button>
            <p style={styles.stepLabel}>Step 2 of 2 · Set Markup for {selectedNetwork}</p>
            <div style={{ ...styles.networkPill, background: cfg.bg, border: `2px solid ${cfg.border}`, color: cfg.color }}>
              {cfg.emoji} {selectedNetwork}
            </div>
            <div style={styles.bundleGrid}>
              {networkBundles.map((item, i) => {
                const accent = bundleAccents[i % bundleAccents.length];
                const hasMarkup = Number(item.markup) > 0;
                const isSaving = savingIndex === item.originalIndex;
                const isSaved = savedIndex === item.originalIndex;
                return (
                  <div key={`${item.network}-${item.bundle}`} style={{ ...styles.bundleCard, background: accent.bg, border: `2px solid ${hasMarkup ? accent.border : "#e5e7eb"}` }}>
                    <div style={{ ...styles.visibilityBadge, background: hasMarkup ? "#dcfce7" : "#fef2f2", color: hasMarkup ? "#16a34a" : "#dc2626", border: `1px solid ${hasMarkup ? "#86efac" : "#fca5a5"}` }}>
                      {hasMarkup ? "👁 Visible" : "🚫 Hidden"}
                    </div>
                    <div style={{ ...styles.bundleSize, color: accent.text }}>{item.bundle}</div>
                    <div style={styles.basePrice}>Base: GH₵ {Number(item.base_price).toFixed(2)}</div>
                    <div style={{ ...styles.bundleDivider, background: accent.border }} />
                    <label style={{ ...styles.markupLabel, color: accent.accent }}>Your Markup (GH₵)</label>
                    <input type="number" min="0" step="0.01" value={item.markup} onChange={(e) => updateMarkup(item.originalIndex, e.target.value)} style={{ ...styles.markupInput, border: `1.5px solid ${accent.border}` }} placeholder="0.00" />
                    <div style={{ ...styles.finalPrice, color: accent.accent }}>
                      Customer pays: <strong>GH₵ {Number(item.final_price).toFixed(2)}</strong>
                    </div>
                    <button onClick={() => saveSingle(item.originalIndex)} disabled={isSaving} style={{ ...styles.saveSingleBtn, background: isSaved ? "linear-gradient(135deg, #22c55e, #16a34a)" : `linear-gradient(135deg, ${accent.accent}, ${accent.accent}cc)`, opacity: isSaving ? 0.6 : 1 }}>
                      {isSaving ? "⏳ Saving..." : isSaved ? "✓ Saved!" : "Save →"}
                    </button>
                  </div>
                );
              })}
            </div>
            <button onClick={saveAll} disabled={savingAll} style={{ ...styles.saveAllBtn, opacity: savingAll ? 0.65 : 1, background: savedAll ? "linear-gradient(135deg, #22c55e, #16a34a)" : "linear-gradient(135deg, #c8ff3e, #8fe600)" }}>
              {savingAll ? "⏳ Saving All..." : savedAll ? "✓ All Prices Saved!" : "💾 Save All Prices"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

const styles = {
  container: { padding: "28px 18px 80px", minHeight: "auto", fontFamily: "'Nunito', 'Poppins', ui-rounded, system-ui, Arial", color: "#241c3d" },
  header: { textAlign: "center", marginBottom: 20 },
  headerBadge: { display: "inline-block", padding: "5px 18px", borderRadius: 50, background: "linear-gradient(135deg, #e0e7ff, #ddd6fe)", border: "1px solid #c4b5fd", color: "#6d28d9", fontSize: 12, fontWeight: 800, marginBottom: 10, letterSpacing: "0.5px" },
  title: { fontSize: 26, fontWeight: 900, color: "#f3f0fb", margin: "0 0 6px", letterSpacing: "-0.5px" },
  subtitle: { fontSize: 13, color: "#9189b5", margin: 0, fontWeight: 600 },
  infoBanner: { display: "flex", alignItems: "flex-start", gap: 10, background: "rgba(234,179,8,0.1)", border: "1.5px solid rgba(234,179,8,0.3)", borderRadius: 14, padding: "12px 16px", maxWidth: 480, margin: "0 auto 20px", fontSize: 13, color: "#ca8a04" },
  infoIcon: { fontSize: 16, flexShrink: 0, marginTop: 1 },
  infoText: { lineHeight: 1.55, fontWeight: 600 },
  progressWrap: { display: "flex", justifyContent: "center", alignItems: "center", position: "relative", maxWidth: 300, margin: "0 auto 24px" },
  progressItem: { display: "flex", flexDirection: "column", alignItems: "center", gap: 6, flex: 1, position: "relative", zIndex: 1 },
  progressDot: { width: 34, height: 34, borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 13, fontWeight: 800, transition: "all 0.35s" },
  progressLabel: { fontSize: 11, transition: "color 0.3s" },
  progressLine: { position: "absolute", top: 17, left: "20%", right: "20%", height: 3, background: "#e5e7eb", zIndex: 0, borderRadius: 10, overflow: "hidden" },
  progressLineFill: { height: "100%", background: "linear-gradient(90deg, #22c55e, #8b5cf6)", borderRadius: 10, transition: "width 0.4s ease" },
  wrapper: { maxWidth: 520, margin: "0 auto" },
  box: { background: "rgba(22,17,38,0.85)", backdropFilter: "blur(20px)", WebkitBackdropFilter: "blur(20px)", padding: "24px 20px", borderRadius: 24, border: "1px solid rgba(255,255,255,0.07)", boxShadow: "0 8px 40px rgba(0,0,0,0.3)" },
  stepLabel: { fontSize: 11, color: "#8b5cf6", fontWeight: 800, textTransform: "uppercase", letterSpacing: "1px", margin: "0 0 18px" },
  emptyBox: { textAlign: "center", padding: "30px 0" },
  emptyText: { color: "#9189b5", fontSize: 14, margin: 0, fontWeight: 600 },
  networkGrid: { display: "flex", flexDirection: "column", gap: 12, marginBottom: 16 },
  networkCard: { padding: "16px 18px", borderRadius: 18, cursor: "pointer", display: "flex", alignItems: "center", transition: "transform 0.15s" },
  networkLeft: { display: "flex", alignItems: "center", gap: 14, flex: 1 },
  networkEmoji: { fontSize: 28, flexShrink: 0 },
  networkName: { fontWeight: 900, fontSize: 16, marginBottom: 2 },
  networkDesc: { fontSize: 12, color: "#9189b5", fontWeight: 600 },
  networkBadge: { fontSize: 11, fontWeight: 800, padding: "3px 10px", borderRadius: 50, marginRight: 10 },
  networkArrow: { fontSize: 18, fontWeight: 900, flexShrink: 0 },
  backDashBtn: { width: "100%", padding: "12px", borderRadius: 14, background: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.1)", color: "#b4acd0", fontWeight: 700, fontSize: 13, cursor: "pointer", marginTop: 4 },
  backBtn: { background: "rgba(255,255,255,0.08)", border: "1px solid rgba(255,255,255,0.1)", color: "#b4acd0", fontSize: 13, fontWeight: 800, cursor: "pointer", padding: "6px 14px", borderRadius: 50, marginBottom: 16, display: "inline-block" },
  networkPill: { display: "inline-flex", alignItems: "center", gap: 6, padding: "7px 18px", borderRadius: 50, fontSize: 13, fontWeight: 900, marginBottom: 20 },
  bundleGrid: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 },
  bundleCard: { borderRadius: 18, padding: "16px 14px 14px", display: "flex", flexDirection: "column", alignItems: "center", gap: 0, textAlign: "center", transition: "transform 0.15s", position: "relative" },
  visibilityBadge: { fontSize: 10, fontWeight: 800, padding: "3px 8px", borderRadius: 50, marginBottom: 10, letterSpacing: "0.3px" },
  bundleSize: { fontWeight: 900, fontSize: 18, marginBottom: 4, letterSpacing: "-0.3px" },
  basePrice: { fontSize: 11, color: "#9189b5", fontWeight: 600, marginBottom: 8 },
  bundleDivider: { width: "50%", height: 2, borderRadius: 10, marginBottom: 10, opacity: 0.4 },
  markupLabel: { fontSize: 11, fontWeight: 800, marginBottom: 4, letterSpacing: "0.3px", alignSelf: "flex-start" },
  markupInput: { width: "100%", padding: "10px 12px", borderRadius: 12, background: "white", color: "#161126", fontSize: 14, fontWeight: 700, marginBottom: 8, boxSizing: "border-box", outline: "none", textAlign: "center" },
  finalPrice: { fontSize: 12, fontWeight: 700, marginBottom: 12 },
  saveAllBtn: { width: "100%", padding: "15px", borderRadius: 16, border: "none", color: "white", fontWeight: 900, fontSize: 15, cursor: "pointer", boxShadow: "0 6px 24px rgba(200,255,62,0.3)", marginTop: 16, letterSpacing: "0.2px", transition: "all 0.3s" },
  saveSingleBtn: { width: "100%", padding: "10px", borderRadius: 12, border: "none", color: "white", fontWeight: 900, fontSize: 13, cursor: "pointer", boxShadow: "0 4px 12px rgba(0,0,0,0.2)", transition: "all 0.3s" },
};
