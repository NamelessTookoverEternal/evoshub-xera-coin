import { useEffect, useState } from "react";
import { clearEvosdataSession } from "../lib/hubSession";

import { smartFetch } from "../config";

export default function AgentDashboard({ user, setPage }) {
    const [loading, setLoading]             = useState(true);
    const [error, setError]                 = useState("");
    const [stats, setStats]                 = useState({
        wallet_balance: 0, total_sales: 0, total_profit: 0,
        total_orders: 0, transactions: [],
    });
    // FIX: read token from user prop first (available immediately after login),
    // fall back to storage for page refreshes where user is rehydrated from storage
    const getToken = () =>
        user?.agent_token
        || sessionStorage.getItem("agentToken")
        || localStorage.getItem("agentToken")
        || "";

    const agentHeaders = () => ({
        "Content-Type": "application/json",
        "X-Agent-Token": getToken(),
    });

    useEffect(() => {
        if (!user) { setPage("login"); return; }
        if (user.role !== "agent" || user.agent_status !== "approved") {
            setPage("dashboard");
        }
    }, [user, setPage]);

    useEffect(() => {
        if (!user?.id) return;

        // FIX: also persist token to storage here so page refreshes work
        if (user.agent_token) {
            sessionStorage.setItem("agentToken", user.agent_token);
            localStorage.setItem("agentToken", user.agent_token);
        }

        const loadDashboard = async () => {
            try {
                setLoading(true);
                setError("");
                const headers = agentHeaders();
                const [dashRes, txRes] = await Promise.all([
                    smartFetch(`/agent/dashboard/${user.id}`, { headers }),
                    smartFetch(`/agent/transactions/${user.id}`, { headers }),
                ]);

                // FIX: if any request is 403, token is missing — send back to login
                if (dashRes.status === 403 || txRes.status === 403) {
                    sessionStorage.removeItem("agentToken");
                    localStorage.removeItem("agentToken");
                    setPage("login");
                    return;
                }

                const data   = await dashRes.json();
                const txData = await txRes.json();

                setStats({
                    wallet_balance: Number(data.wallet_balance  || 0),
                    total_sales:    Number(data.total_sales     || 0),
                    total_profit:   Number(data.total_profit    || 0),
                    total_orders:   Number(data.total_orders    || 0),
                    transactions:   txData.transactions || [],
                });
            } catch (err) {
                console.log(err);
                setError("Failed to load dashboard");
            } finally {
                setLoading(false);
            }
        };

        loadDashboard();
    }, [user]);

    const logout = () => {
        clearEvosdataSession();
        setPage("login");
    };

    return (
        <div style={styles.container}>
            <div style={styles.header}>
                <div style={styles.headerLeft}>
                    <div style={styles.brand}>🚀 Agent Hub</div>
                    <div style={styles.agentBadge}>Agent · Active</div>
                </div>
                <div style={styles.headerRight}>
                    <button style={styles.iconBtn} onClick={() => setPage("dashboard")} title="Home">🏠</button>
                    <button style={styles.logoutBtn} onClick={logout}>Sign Out</button>
                </div>
            </div>

            <div style={styles.main}>
                <div style={styles.welcomeRow}>
                    <div>
                        <h1 style={styles.title}>Welcome back 👋</h1>
                        <p style={styles.subtitle}>@{user?.username}</p>
                    </div>
                    <button style={styles.refreshBtn} onClick={() => window.location.reload()}>🔄 Refresh</button>
                </div>

                {error && <div style={styles.errorBox}>⚠️ {error}</div>}

                {loading ? (
                    <div style={styles.loadingWrap}>
                        <div style={{ fontSize: 36, marginBottom: 12 }}>⏳</div>
                        <p style={styles.loadingText}>Loading your dashboard...</p>
                    </div>
                ) : (
                    <>
                        <div style={styles.walletCard}>
                            <div style={styles.walletTop}>
                                <div>
                                    <p style={styles.walletLabel}>Available Balance</p>
                                    <h2 style={styles.walletAmount}>GH₵ {stats.wallet_balance.toFixed(2)}</h2>
                                </div>
                                <div style={styles.walletIcon}>💰</div>
                            </div>
                            <button style={styles.withdrawBtn} onClick={() => setPage("agent-withdraw")}>
                                💳 Withdraw Funds
                            </button>
                        </div>

                        <div style={styles.statsGrid}>
                            {[
                                { icon: "📈", label: "Total Profit",  val: `GH₵ ${stats.total_profit.toFixed(2)}`, color: "#22c55e", bg: "rgba(34,197,94,0.1)",   border: "rgba(34,197,94,0.25)"  },
                                { icon: "📦", label: "Total Orders",  val: stats.total_orders,                      color: "#c8ff3e", bg: "rgba(200,255,62,0.1)",  border: "rgba(200,255,62,0.25)" },
                                { icon: "🛒", label: "Total Sales",   val: stats.total_sales,                       color: "#a78bfa", bg: "rgba(167,139,250,0.1)", border: "rgba(167,139,250,0.25)"},
                                { icon: "⭐", label: "Status",        val: "Approved",                              color: "#f59e0b", bg: "rgba(245,158,11,0.1)",  border: "rgba(245,158,11,0.25)" },
                            ].map((s, i) => (
                                <div key={i} style={{ ...styles.statCard, background: s.bg, border: `1px solid ${s.border}` }}>
                                    <div style={styles.statIcon}>{s.icon}</div>
                                    <div style={{ ...styles.statVal, color: s.color }}>{s.val}</div>
                                    <div style={styles.statLabel}>{s.label}</div>
                                </div>
                            ))}
                        </div>

                        <div style={styles.actionsSection}>
                            <h3 style={styles.sectionTitle}>Quick Actions</h3>
                            <div style={styles.actionsGrid}>
                                {[
                                    { icon: "🎨", label: "Store Settings",  desc: "Link, name & logo",        page: "agent-store-settings", color: "#c8ff3e", bg: "rgba(200,255,62,0.1)", border: "rgba(200,255,62,0.25)" },
                                    { icon: "📡", label: "Buy Data",        desc: "Purchase at base price",   page: "agent-buy-data", color: "#a78bfa", bg: "rgba(167,139,250,0.1)", border: "rgba(167,139,250,0.25)" },
                                    { icon: "💰", label: "Manage Pricing",  desc: "Set your bundle markups",  page: "agent-pricing",  color: "#f59e0b", bg: "rgba(245,158,11,0.1)",  border: "rgba(245,158,11,0.25)"  },
                                    { icon: "💳", label: "Withdraw",        desc: "Send to your MoMo",        page: "agent-withdraw", color: "#22c55e", bg: "rgba(34,197,94,0.1)",   border: "rgba(34,197,94,0.25)"   },
                                    { icon: "🏠", label: "Dashboard",       desc: "Main account page",        page: "dashboard",      color: "#c8ff3e", bg: "rgba(200,255,62,0.1)",  border: "rgba(200,255,62,0.25)"  },
                                ].map((a, i) => (
                                    <div
                                        key={i}
                                        style={{ ...styles.actionCard, background: a.bg, border: `1px solid ${a.border}` }}
                                        onClick={() => setPage(a.page)}
                                    >
                                        <div style={{ ...styles.actionIcon, color: a.color }}>{a.icon}</div>
                                        <div style={{ ...styles.actionLabel, color: a.color }}>{a.label}</div>
                                        <div style={styles.actionDesc}>{a.desc}</div>
                                    </div>
                                ))}
                            </div>
                        </div>

                        <div style={styles.txSection}>
                            <div style={styles.txHeader}>
                                <h3 style={styles.sectionTitle}>Recent Transactions</h3>
                                <span style={styles.txCount}>{stats.transactions.length} total</span>
                            </div>
                            {stats.transactions.length === 0 ? (
                                <div style={styles.emptyTx}>
                                    <div style={{ fontSize: 36, marginBottom: 8 }}>📭</div>
                                    <p style={styles.emptyTxText}>No transactions yet</p>
                                    <p style={styles.emptyTxSub}>Your earnings will appear here</p>
                                </div>
                            ) : (
                                stats.transactions.slice(0, 10).map((tx, i) => {
                                    const isCredit     = tx.type === "credit";
                                    const isWithdrawal = tx.type === "withdrawal";
                                    return (
                                        <div key={i} style={styles.txCard}>
                                            <div style={{ ...styles.txIconWrap, background: isCredit ? "rgba(34,197,94,0.15)" : "rgba(239,68,68,0.15)" }}>
                                                <span style={{ fontSize: 18 }}>{isCredit ? "📥" : isWithdrawal ? "💸" : "📤"}</span>
                                            </div>
                                            <div style={styles.txInfo}>
                                                <div style={styles.txType}>{isCredit ? "Commission Earned" : isWithdrawal ? "Withdrawal" : "Debit"}</div>
                                                <div style={styles.txRef}>{tx.reference || "N/A"}</div>
                                            </div>
                                            <div style={{ ...styles.txAmount, color: isCredit ? "#22c55e" : "#ef4444" }}>
                                                {isCredit ? "+" : "-"}GH₵ {Math.abs(Number(tx.amount || 0)).toFixed(2)}
                                            </div>
                                        </div>
                                    );
                                })
                            )}
                        </div>
                    </>
                )}
            </div>
        </div>
    );
}

const styles = {
    container:       { minHeight: "auto", color: "#e5e7eb", fontFamily: "ui-sans-serif, system-ui, Arial" },
    header:          { display: "flex", justifyContent: "space-between", alignItems: "center", padding: "14px 18px", borderBottom: "1px solid rgba(255,255,255,0.06)", background: "rgba(22,17,38,0.8)", backdropFilter: "blur(12px)", position: "sticky", top: 0, zIndex: 100 },
    headerLeft:      { display: "flex", alignItems: "center", gap: 10 },
    brand:           { color: "#c8ff3e", fontSize: 18, fontWeight: 900 },
    agentBadge:      { fontSize: 11, fontWeight: 800, padding: "3px 10px", borderRadius: 50, background: "rgba(34,197,94,0.15)", border: "1px solid rgba(34,197,94,0.3)", color: "#22c55e" },
    headerRight:     { display: "flex", alignItems: "center", gap: 10 },
    iconBtn:         { width: 38, height: 38, border: "none", borderRadius: 10, background: "rgba(255,255,255,0.06)", cursor: "pointer", fontSize: 16 },
    logoutBtn:       { padding: "8px 14px", borderRadius: 10, border: "1px solid rgba(239,68,68,0.3)", background: "rgba(239,68,68,0.08)", color: "#ef4444", fontWeight: 700, fontSize: 13, cursor: "pointer" },
    main:            { maxWidth: 600, margin: "0 auto", padding: "24px 18px 60px" },
    welcomeRow:      { display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 24 },
    title:           { fontSize: 26, fontWeight: 900, color: "#f3f0fb", margin: "0 0 4px" },
    subtitle:        { fontSize: 14, color: "#9189b5", margin: 0 },
    refreshBtn:      { padding: "8px 14px", borderRadius: 10, border: "1px solid rgba(255,255,255,0.08)", background: "rgba(255,255,255,0.04)", color: "#b4acd0", fontSize: 13, fontWeight: 700, cursor: "pointer" },
    errorBox:        { background: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.3)", color: "#f87171", padding: "12px 16px", borderRadius: 12, fontSize: 14, marginBottom: 16 },
    loadingWrap:     { textAlign: "center", padding: "60px 0" },
    loadingText:     { fontSize: 15, color: "#9189b5", fontWeight: 600 },
    walletCard:      { background: "linear-gradient(135deg, rgba(200,255,62,0.15), rgba(167,139,250,0.1))", border: "1px solid rgba(200,255,62,0.25)", borderRadius: 22, padding: "22px 20px", marginBottom: 16 },
    walletTop:       { display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 18 },
    walletLabel:     { fontSize: 13, color: "#b4acd0", margin: "0 0 6px", fontWeight: 600 },
    walletAmount:    { fontSize: 34, fontWeight: 900, color: "#f3f0fb", margin: 0 },
    walletIcon:      { fontSize: 40 },
    withdrawBtn:     { width: "100%", padding: "13px", borderRadius: 14, border: "none", background: "linear-gradient(135deg, #22c55e, #16a34a)", color: "white", fontWeight: 900, fontSize: 15, cursor: "pointer", boxShadow: "0 4px 20px rgba(34,197,94,0.3)" },
    statsGrid:       { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 16 },
    statCard:        { padding: "16px 14px", borderRadius: 18, textAlign: "center" },
    statIcon:        { fontSize: 24, marginBottom: 8 },
    statVal:         { fontWeight: 900, fontSize: 18, marginBottom: 4 },
    statLabel:       { fontSize: 12, color: "#9189b5", fontWeight: 600 },
    actionsSection:  { marginBottom: 24 },
    sectionTitle:    { fontSize: 16, fontWeight: 900, color: "#f3f0fb", margin: "0 0 14px" },
    actionsGrid:     { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 },
    actionCard:      { padding: "16px 12px", borderRadius: 16, cursor: "pointer", textAlign: "center", transition: "transform 0.15s" },
    actionIcon:      { fontSize: 26, marginBottom: 8 },
    actionLabel:     { fontWeight: 800, fontSize: 13, marginBottom: 4 },
    actionDesc:      { fontSize: 11, color: "#9189b5" },
    txSection:       { marginBottom: 20 },
    txHeader:        { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 },
    txCount:         { fontSize: 12, color: "#9189b5", fontWeight: 700 },
    emptyTx:         { textAlign: "center", padding: "30px 0" },
    emptyTxText:     { fontSize: 15, color: "#7a6fa3", fontWeight: 700, margin: "0 0 4px" },
    emptyTxSub:      { fontSize: 13, color: "#3d3460", margin: 0 },
    txCard:          { display: "flex", alignItems: "center", gap: 14, padding: "14px 16px", borderRadius: 16, marginBottom: 10, background: "rgba(22,17,38,0.9)", border: "1px solid rgba(255,255,255,0.06)" },
    txIconWrap:      { width: 42, height: 42, borderRadius: 12, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 },
    txInfo:          { flex: 1 },
    txType:          { fontWeight: 700, fontSize: 14, color: "#e5e7eb", marginBottom: 3 },
    txRef:           { fontSize: 11, color: "#7a6fa3" },
    txAmount:        { fontWeight: 900, fontSize: 16, flexShrink: 0 },
};
