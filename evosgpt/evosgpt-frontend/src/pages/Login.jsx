import { useState } from "react";
import { loginUser } from "../api";
import { HUB_URL, openProduct } from "../config";

export default function Login({ setPage, setUser, notice, onBack }) {
  const [form, setForm]     = useState({ username: "", password: "" });
  const [loading, setLoad]  = useState(false);
  const [error, setError]   = useState("");

  const set = (k, v) => setForm(f => ({ ...f, [k]: v }));

  const submit = async () => {
    setError("");
    if (!form.username || !form.password) return setError("Please fill in all fields.");
    try {
      setLoad(true);
      const { data } = await loginUser({ username: form.username.trim(), password: form.password });
      if (data.status === "invalid_credentials") return setError("Invalid username/email or password.");
      if (data.status !== "ok") return setError("Something went wrong. Try again.");
      setUser(data.user);
      setPage("chat");
    } catch (e) {
      setError(e.response?.data?.detail || "Server error. Please try again.");
    } finally { setLoad(false); }
  };

  return (
    <div style={S.page}>
      <div style={S.card} className="fade-in">
        <div style={{ textAlign: "center", marginBottom: 6 }}>
          <div style={{ fontSize: 44 }}>⚡</div>
          <div style={S.brand}>EVOSGPT</div>
          <div style={S.sub}>The AI that evolves with you</div>
        </div>

        {notice && (
          <div role="status" style={{ fontSize: 13, textAlign: "center", margin: "0 0 12px", color: "#38bdf8" }}>
            {notice}{" "}
            {onBack && <span onClick={onBack} style={{ cursor: "pointer", textDecoration: "underline" }}>Back to browsing</span>}
          </div>
        )}
        <h2 style={S.title}>Welcome Back</h2>

        <label style={S.label}>Username or Email</label>
        <input style={S.input} placeholder="Enter username or email" value={form.username}
          onChange={e => set("username", e.target.value)} onKeyDown={e => e.key === "Enter" && submit()} />

        <label style={S.label}>Password</label>
        <input style={S.input} type="password" placeholder="Enter password" value={form.password}
          onChange={e => set("password", e.target.value)} onKeyDown={e => e.key === "Enter" && submit()} />

        {error && <div style={S.error}>{error}</div>}

        <button style={{ ...S.btn, opacity: loading ? 0.6 : 1 }} onClick={submit} disabled={loading}>
          {loading ? "Signing in..." : "Sign In →"}
        </button>

        <div style={S.divider}><span>New to EVOSGPT?</span></div>

        <button style={S.ghost} onClick={() => setPage("register")}>Create a Free Account</button>

        <div style={{ textAlign: "center", marginTop: 10 }}>
          <span style={{ fontSize: 13, color: "#334155" }}>Part of </span>
          <span onClick={() => openProduct(HUB_URL)} style={{ fontSize: 13, color: "#38bdf8", cursor: "pointer", fontWeight: 700 }}>EVOS Business Hub</span>
        </div>
      </div>
    </div>
  );
}

const S = {
  page:  { minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: "#070d1a", padding: 20 },
  card:  { width: "100%", maxWidth: 420, background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.07)", borderRadius: 24, padding: "40px 32px", display: "flex", flexDirection: "column", gap: 12, backdropFilter: "blur(20px)" },
  brand: { fontSize: 26, fontWeight: 900, background: "linear-gradient(135deg,#38bdf8,#a78bfa)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", marginTop: 6 },
  sub:   { fontSize: 13, color: "#475569", marginTop: 4 },
  title: { fontSize: 20, fontWeight: 900, color: "#f1f5f9", textAlign: "center", marginTop: 8, marginBottom: 4 },
  label: { fontSize: 12, fontWeight: 700, color: "#64748b", marginBottom: -6 },
  input: { padding: "13px 16px", borderRadius: 12, border: "1px solid rgba(255,255,255,0.09)", background: "rgba(0,0,0,0.3)", color: "#f1f5f9", fontSize: 14, outline: "none" },
  btn:   { padding: 14, borderRadius: 12, border: "none", background: "linear-gradient(135deg,#38bdf8,#0ea5e9)", color: "#000", fontWeight: 900, fontSize: 15, cursor: "pointer", marginTop: 4 },
  ghost: { padding: 13, borderRadius: 12, border: "1px solid rgba(255,255,255,0.1)", background: "transparent", color: "#94a3b8", fontWeight: 700, fontSize: 14, cursor: "pointer" },
  error: { color: "#f87171", fontSize: 13, background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.25)", borderRadius: 8, padding: "9px 13px", textAlign: "center" },
  divider: { textAlign: "center", fontSize: 12, color: "#334155", margin: "4px 0" },
};
