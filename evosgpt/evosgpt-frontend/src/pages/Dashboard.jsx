import { useState, useEffect } from "react";
import { getUser, getReferral } from "../api";
import { EVOSDATA_URL } from "../config";

const TIER_INFO = {
  Basic:   { icon: "🧊", color: "#64748b", label: "Basic" },
  Pro:     { icon: "⚡", color: "#38bdf8", label: "Pro" },
  Core:    { icon: "🔥", color: "#a78bfa", label: "Core" },
  Founder: { icon: "👑", color: "#f59e0b", label: "Founder" },
};

export default function Dashboard({ setPage, user, onLogout }) {
  const [profile, setProfile]   = useState(null);
  const [referral, setReferral] = useState(null);
  const [copied, setCopied]     = useState(false);
  const [loading, setLoading]   = useState(true);

  useEffect(() => {
    if (!user) { setPage("login"); return; }
    load();
  }, [user]);

  const load = async () => {
    try {
      setLoading(true);
      const [u, r] = await Promise.all([getUser(user.id), getReferral(user.id)]);
      setProfile(u.data.user);
      setReferral(r.data);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  };

  const copyLink = () => {
    navigator.clipboard.writeText(referral.referral_link);
    setCopied(true);
    setTimeout(() => setCopied(false), 1800);
  };

  if (loading || !profile) {
    return <div style={S.loadingWrap}>⏳ Loading your dashboard...</div>;
  }

  const tierInfo = TIER_INFO[profile.evosgpt_tier] || TIER_INFO.Basic;

  return (
    <div style={S.page}>
      {/* HEADER */}
      <header style={S.header}>
        <div onClick={() => setPage("chat")} style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
          <span style={{ fontSize: 22 }}>⚡</span>
          <span style={S.brand}>EVOSGPT</span>
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <button style={S.ghostBtn} onClick={() => setPage("chat")}>💬 Chat</button>
          <button style={S.dangerBtn} onClick={onLogout}>Sign Out</button>
        </div>
      </header>

      <main style={S.main}>
        {/* WELCOME */}
        <div style={S.welcomeCard}>
          <div>
            <div style={S.greeting}>Welcome back 👋</div>
            <h1 style={S.name}>{profile.full_name || profile.username}</h1>
            <div style={{ ...S.tierPill, color: tierInfo.color, borderColor: tierInfo.color + "55", background: tierInfo.color + "18" }}>
              {tierInfo.icon} {tierInfo.label} Tier
            </div>
          </div>
        </div>

        {/* STATS */}
        <div style={S.statsGrid}>
          {[
            ["💬", "Messages Sent", profile.mem_count ?? 0, "#38bdf8"],
            ["📅", "Chats Today", profile.today_count ?? 0, "#a78bfa"],
            ["🧠", "Memory", profile.has_long_mem ? "Active" : "Building", "#22c55e"],
            ["🎯", "Daily Limit", profile.day_limit ?? "Unlimited", "#f59e0b"],
          ].map(([icon, label, val, color]) => (
            <div key={label} style={S.statCard}>
              <div style={{ fontSize: 22 }}>{icon}</div>
              <div style={{ fontWeight: 900, fontSize: 18, color, marginTop: 6 }}>{val}</div>
              <div style={{ fontSize: 12, color: "#64748b", marginTop: 3 }}>{label}</div>
            </div>
          ))}
        </div>

        {/* LONG MEMORY PREVIEW */}
        {profile.long_memory && (
          <div style={S.memoryCard}>
            <div style={S.cardTitle}>🧠 What EVOSGPT Remembers About You</div>
            <p style={{ color: "#94a3b8", fontSize: 14, lineHeight: 1.7, margin: 0 }}>{profile.long_memory}</p>
          </div>
        )}

        {/* UPGRADE CTA */}
        {profile.evosgpt_tier === "Basic" && (
          <div style={S.upgradeCard}>
            <div>
              <div style={{ fontWeight: 800, fontSize: 16, color: "#f1f5f9", marginBottom: 6 }}>⚡ Unlock Pro Power</div>
              <p style={{ color: "#94a3b8", fontSize: 13, margin: 0 }}>Unlimited chats, bigger memory, and expert-level responses for code, design & writing.</p>
            </div>
            <button style={S.upgradeBtn} onClick={() => setPage("upgrade")}>Upgrade Now</button>
          </div>
        )}

        {/* REFERRAL */}
        {referral && (
          <div style={S.referralCard}>
            <div style={S.cardTitle}>🎁 Invite Friends</div>
            <p style={{ color: "#94a3b8", fontSize: 13, marginBottom: 14 }}>
              You've referred <strong style={{ color: "#f1f5f9" }}>{referral.referral_count}</strong> people.
            </p>
            <div style={S.linkBox}>{referral.referral_link}</div>
            <button style={S.copyBtn} onClick={copyLink}>{copied ? "✅ Copied!" : "📋 Copy Link"}</button>
          </div>
        )}

        {/* EVOSDATA CROSSELL */}
        <div style={S.crossellCard}>
          <div>
            <div style={{ fontWeight: 800, fontSize: 15, color: "#f1f5f9", marginBottom: 4 }}>📶 Need Data?</div>
            <p style={{ color: "#64748b", fontSize: 13, margin: 0 }}>Buy affordable Ghana data bundles on EvosData.</p>
          </div>
          <button style={S.crossellBtn} onClick={() => window.open(EVOSDATA_URL, "_blank")}>Visit EvosData →</button>
        </div>
      </main>
    </div>
  );
}

const S = {
  page:   { minHeight: "100vh", background: "#070d1a", color: "#e2e8f0" },
  loadingWrap: { display: "flex", alignItems: "center", justifyContent: "center", height: "100vh", color: "#64748b", fontSize: 15 },
  header: { display: "flex", justifyContent: "space-between", alignItems: "center", padding: "16px 20px", borderBottom: "1px solid rgba(255,255,255,0.06)", position: "sticky", top: 0, background: "rgba(7,13,26,0.9)", backdropFilter: "blur(16px)" },
  brand:  { fontWeight: 900, fontSize: 17, color: "#38bdf8" },
  ghostBtn: { padding: "9px 16px", borderRadius: 10, border: "1px solid rgba(255,255,255,0.12)", background: "transparent", color: "#e2e8f0", fontWeight: 700, fontSize: 13, cursor: "pointer" },
  dangerBtn: { padding: "9px 16px", borderRadius: 10, border: "1px solid rgba(239,68,68,0.3)", background: "rgba(239,68,68,0.08)", color: "#f87171", fontWeight: 700, fontSize: 13, cursor: "pointer" },
  main:   { maxWidth: 640, margin: "0 auto", padding: "28px 20px 60px" },
  welcomeCard: { background: "linear-gradient(135deg,rgba(56,189,248,0.1),rgba(167,139,250,0.07))", border: "1px solid rgba(255,255,255,0.07)", borderRadius: 22, padding: "24px 22px", marginBottom: 20 },
  greeting: { fontSize: 13, color: "#64748b", fontWeight: 600 },
  name: { fontSize: 24, fontWeight: 900, color: "#f1f5f9", margin: "4px 0 12px" },
  tierPill: { display: "inline-block", fontSize: 12, fontWeight: 800, padding: "5px 14px", borderRadius: 50, border: "1px solid" },
  statsGrid: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 20 },
  statCard: { background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 16, padding: "16px 14px", textAlign: "center" },
  memoryCard: { background: "rgba(167,139,250,0.06)", border: "1px solid rgba(167,139,250,0.2)", borderRadius: 18, padding: "20px", marginBottom: 20 },
  cardTitle: { fontWeight: 800, fontSize: 15, color: "#f1f5f9", marginBottom: 10 },
  upgradeCard: { background: "linear-gradient(135deg,rgba(56,189,248,0.1),rgba(14,165,233,0.06))", border: "1px solid rgba(56,189,248,0.25)", borderRadius: 18, padding: "20px", marginBottom: 20, display: "flex", justifyContent: "space-between", alignItems: "center", gap: 16, flexWrap: "wrap" },
  upgradeBtn: { padding: "11px 22px", borderRadius: 12, border: "none", background: "#38bdf8", color: "#000", fontWeight: 900, fontSize: 13, cursor: "pointer", whiteSpace: "nowrap" },
  referralCard: { background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 18, padding: "20px", marginBottom: 20 },
  linkBox: { background: "rgba(0,0,0,0.3)", border: "1px solid rgba(255,255,255,0.07)", borderRadius: 10, padding: "10px 14px", fontSize: 12, color: "#64748b", wordBreak: "break-all", marginBottom: 12 },
  copyBtn: { width: "100%", padding: 12, borderRadius: 12, border: "none", background: "linear-gradient(135deg,#38bdf8,#0ea5e9)", color: "#000", fontWeight: 900, fontSize: 13, cursor: "pointer" },
  crossellCard: { background: "rgba(34,197,94,0.06)", border: "1px solid rgba(34,197,94,0.2)", borderRadius: 18, padding: "18px 20px", display: "flex", justifyContent: "space-between", alignItems: "center", gap: 16, flexWrap: "wrap" },
  crossellBtn: { padding: "10px 18px", borderRadius: 12, border: "none", background: "linear-gradient(135deg,#22c55e,#16a34a)", color: "#fff", fontWeight: 800, fontSize: 13, cursor: "pointer", whiteSpace: "nowrap" },
};
