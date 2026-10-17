import { useState } from "react";
import { registerUser } from "../api";

export default function Register({ setPage, setUser }) {
  const params = new URLSearchParams(window.location.search);
  const refFromUrl = params.get("ref") || "";

  const [form, setForm] = useState({
    username: "", full_name: "", email: "", phone: "",
    password: "", confirm: "", referred_by: refFromUrl,
  });
  const [loading, setLoad] = useState(false);
  const [error, setError]  = useState("");
  const [success, setOk]   = useState("");

  const set = (k, v) => setForm(f => ({ ...f, [k]: v }));

  const submit = async () => {
    setError(""); setOk("");
    const { username, full_name, email, phone, password, confirm, referred_by } = form;

    if (!username || !full_name || !email || !password) return setError("Please fill in all required fields.");
    if (username.length < 3) return setError("Username must be at least 3 characters.");
    if (password.length < 6) return setError("Password must be at least 6 characters.");
    if (password !== confirm) return setError("Passwords do not match.");

    try {
      setLoad(true);
      const { data } = await registerUser({
        username: username.trim().toLowerCase(),
        full_name: full_name.trim(),
        email: email.trim().toLowerCase(),
        phone: phone.replace(/\D/g, ""),
        password,
        referred_by: referred_by.trim() || null,
      });

      if (data.status === "username_taken") return setError("That username is already taken.");
      if (data.status === "email_taken")    return setError("That email is already registered.");
      if (data.status !== "created")        return setError("Registration failed. Please try again.");

      setOk("🎉 Account created! Redirecting to chat...");
      setUser(data.user);
      setTimeout(() => setPage("chat"), 1200);
    } catch (e) {
      setError(e.response?.data?.detail || "Server error. Please try again.");
    } finally { setLoad(false); }
  };

  return (
    <div style={S.page}>
      <div style={S.card} className="fade-in">
        <div style={{ textAlign: "center", marginBottom: 4 }}>
          <div style={{ fontSize: 40 }}>⚡</div>
          <div style={S.brand}>Join EVOSGPT</div>
          <div style={S.sub}>Free to start. No credit card needed.</div>
        </div>

        <input style={S.input} placeholder="Username" value={form.username} onChange={e => set("username", e.target.value)} />
        <input style={S.input} placeholder="Full Name" value={form.full_name} onChange={e => set("full_name", e.target.value)} />
        <input style={S.input} placeholder="Email" type="email" value={form.email} onChange={e => set("email", e.target.value)} />
        <input style={S.input} placeholder="Phone (optional)" value={form.phone} onChange={e => set("phone", e.target.value)} />
        <input style={S.input} placeholder="Password" type="password" value={form.password} onChange={e => set("password", e.target.value)} />
        <input style={S.input} placeholder="Confirm Password" type="password" value={form.confirm} onChange={e => set("confirm", e.target.value)}
          onKeyDown={e => e.key === "Enter" && submit()} />
        <input style={S.input} placeholder="Referral Code (optional)" value={form.referred_by} onChange={e => set("referred_by", e.target.value)} />

        {error   && <div style={S.error}>{error}</div>}
        {success && <div style={S.success}>{success}</div>}

        <button style={{ ...S.btn, opacity: loading ? 0.6 : 1 }} onClick={submit} disabled={loading}>
          {loading ? "Creating account..." : "Create Free Account →"}
        </button>

        <div style={{ textAlign: "center", marginTop: 6 }}>
          <span style={{ fontSize: 13, color: "#475569" }}>Already have an account? </span>
          <span onClick={() => setPage("login")} style={{ fontSize: 13, color: "#38bdf8", cursor: "pointer", fontWeight: 700 }}>Login</span>
        </div>
      </div>
    </div>
  );
}

const S = {
  page:  { minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: "#070d1a", padding: 20 },
  card:  { width: "100%", maxWidth: 440, background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.07)", borderRadius: 24, padding: "36px 32px", display: "flex", flexDirection: "column", gap: 12, backdropFilter: "blur(20px)" },
  brand: { fontSize: 22, fontWeight: 900, color: "#f1f5f9", marginTop: 6 },
  sub:   { fontSize: 13, color: "#475569", marginTop: 4, marginBottom: 6 },
  input: { padding: "13px 16px", borderRadius: 12, border: "1px solid rgba(255,255,255,0.09)", background: "rgba(0,0,0,0.3)", color: "#f1f5f9", fontSize: 14, outline: "none" },
  btn:   { padding: 14, borderRadius: 12, border: "none", background: "linear-gradient(135deg,#38bdf8,#0ea5e9)", color: "#000", fontWeight: 900, fontSize: 15, cursor: "pointer", marginTop: 4 },
  error:   { color: "#f87171", fontSize: 13, background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.25)", borderRadius: 8, padding: "9px 13px", textAlign: "center" },
  success: { color: "#4ade80", fontSize: 13, background: "rgba(34,197,94,0.08)", border: "1px solid rgba(34,197,94,0.25)", borderRadius: 8, padding: "9px 13px", textAlign: "center" },
};
