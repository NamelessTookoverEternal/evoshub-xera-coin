import { useState } from "react";
import { registerUser } from "../api";

export default function Register({ setPage }) {
  const [form, setForm] = useState({
    username: "",
    fullName: "",
    email: "",
    phone: "",
    password: "",
    confirmPassword: "",
    ref: "",
  });

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [showPass, setShowPass] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);

  const handleChange = (field, value) => {
    setForm((prev) => ({ ...prev, [field]: value }));
  };

  const handleRegister = async () => {
    setError("");
    setSuccess("");

    const { username, fullName, email, phone, password, confirmPassword, ref } = form;

    if (!username || !email || !password) return setError("Username, email and password are required");
    if (username.length < 3) return setError("Username must be at least 3 characters");
    if (password.length < 6) return setError("Password must be at least 6 characters");
    if (password !== confirmPassword) return setError("Passwords do not match");

    const cleanPhone = phone.replace(/\D/g, "");
    if (cleanPhone.length < 10) return setError("Enter a valid phone number");

    try {
      setLoading(true);
      const res = await registerUser({
        username: username.trim().toLowerCase(),
        full_name: fullName.trim(),
        email: email.trim().toLowerCase(),
        phone: cleanPhone,
        password: password.trim(),
        referred_by: ref.trim() || null,
      });

      const data = res.data;

      if (data.status === "username_taken") return setError("Username already taken");
      if (data.status === "email_taken") return setError("Email already exists");
      if (data.status !== "created") return setError("Registration failed");

      setSuccess("Account created successfully!");
      setTimeout(() => setPage("login"), 1400);
    } catch (err) {
      setError(err.response?.data?.detail || "Server error. Try again.");
    } finally {
      setLoading(false);
    }
  };

  const fields = [
    { key: "username", placeholder: "Username", type: "text", icon: "👤" },
    { key: "fullName", placeholder: "Full Name", type: "text", icon: "🪪" },
    { key: "email", placeholder: "Email address", type: "email", icon: "✉️" },
    { key: "phone", placeholder: "Phone (e.g. 0551234567)", type: "tel", icon: "📱" },
  ];

  return (
    <div style={s.page}>
      <div style={s.card}>

        {/* Brand */}
        <div style={s.brand}>
          <div style={s.brandDot} />
          <span style={s.brandName}>EVOS</span>
        </div>

        <h2 style={s.title}>Create Account</h2>
        <p style={s.sub}>Join EVOS Data Services</p>

        {/* Regular fields */}
        {fields.map(({ key, placeholder, type, icon }) => (
          <div key={key} style={s.field}>
            <label style={s.label}>{placeholder}</label>
            <div style={s.iconWrap}>
              <span style={s.icon}>{icon}</span>
              <input
                style={s.input}
                type={type}
                placeholder={placeholder}
                value={form[key]}
                onChange={(e) => handleChange(key, e.target.value)}
              />
            </div>
          </div>
        ))}

        {/* Password */}
        <div style={s.field}>
          <label style={s.label}>Password</label>
          <div style={s.passWrap}>
            <span style={s.icon}>🔒</span>
            <input
              style={s.input}
              type={showPass ? "text" : "password"}
              placeholder="Min 6 characters"
              value={form.password}
              onChange={(e) => handleChange("password", e.target.value)}
            />
            <button style={s.eyeBtn} onClick={() => setShowPass(!showPass)} tabIndex={-1}>
              {showPass ? "🙈" : "👁"}
            </button>
          </div>
        </div>

        {/* Confirm Password */}
        <div style={s.field}>
          <label style={s.label}>Confirm Password</label>
          <div style={s.passWrap}>
            <span style={s.icon}>🔒</span>
            <input
              style={{
                ...s.input,
                borderColor: form.confirmPassword && form.password !== form.confirmPassword
                  ? "rgba(239,68,68,0.5)"
                  : form.confirmPassword && form.password === form.confirmPassword
                  ? "rgba(34,197,94,0.5)"
                  : "rgba(255,255,255,0.08)",
              }}
              type={showConfirm ? "text" : "password"}
              placeholder="Re-enter password"
              value={form.confirmPassword}
              onChange={(e) => handleChange("confirmPassword", e.target.value)}
            />
            <button style={s.eyeBtn} onClick={() => setShowConfirm(!showConfirm)} tabIndex={-1}>
              {showConfirm ? "🙈" : "👁"}
            </button>
          </div>
          {form.confirmPassword && form.password !== form.confirmPassword && (
            <p style={s.matchHint}>Passwords do not match</p>
          )}
          {form.confirmPassword && form.password === form.confirmPassword && (
            <p style={{ ...s.matchHint, color: "#4ade80" }}>Passwords match ✓</p>
          )}
        </div>

        {/* Referral */}
        <div style={s.field}>
          <label style={s.label}>Referral Code (optional)</label>
          <div style={s.iconWrap}>
            <span style={s.icon}>🎁</span>
            <input
              style={s.input}
              type="text"
              placeholder="Enter referral code"
              value={form.ref}
              onChange={(e) => handleChange("ref", e.target.value)}
            />
          </div>
        </div>

        {/* Error / Success */}
        {error && <div style={s.errorBox}>{error}</div>}
        {success && <div style={s.successBox}>{success}</div>}

        {/* Submit */}
        <button
          onClick={handleRegister}
          disabled={loading}
          style={{ ...s.btn, opacity: loading ? 0.65 : 1, cursor: loading ? "not-allowed" : "pointer" }}
        >
          {loading ? "Creating account..." : "Create Account"}
        </button>

        {/* Divider */}
        <div style={s.divider}>
          <div style={s.dividerLine} />
          <span style={s.dividerText}>already have an account?</span>
          <div style={s.dividerLine} />
        </div>

        <button style={s.loginBtn} onClick={() => setPage("login")}>
          Sign In
        </button>
      </div>
    </div>
  );
}

const s = {
  page: {
    minHeight: "calc(100dvh - var(--dock, 0px) - 58px)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    padding: "20px 16px",
  },
  card: {
    width: "100%",
    maxWidth: 420,
    background: "rgba(22,17,38,0.92)",
    backdropFilter: "blur(20px)",
    WebkitBackdropFilter: "blur(20px)",
    borderRadius: 24,
    padding: "36px 28px",
    border: "1px solid rgba(255,255,255,0.08)",
    boxShadow: "0 32px 64px rgba(0,0,0,0.5)",
    display: "flex",
    flexDirection: "column",
    gap: 0,
  },
  brand: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    marginBottom: 20,
    justifyContent: "center",
  },
  brandDot: {
    width: 10, height: 10, borderRadius: "50%",
    background: "#c8ff3e", boxShadow: "0 0 10px #c8ff3e",
  },
  brandName: {
    fontSize: 18, fontWeight: 900, color: "#c8ff3e", letterSpacing: "0.15em",
  },
  title: {
    fontSize: 22, fontWeight: 900, color: "#e5e7eb",
    margin: "0 0 4px", textAlign: "center",
  },
  sub: {
    fontSize: 13, color: "#9189b5", textAlign: "center", margin: "0 0 22px",
  },
  field: { marginBottom: 14 },
  label: {
    display: "block", fontSize: 11, color: "#b4acd0",
    marginBottom: 5, letterSpacing: "0.05em", textTransform: "uppercase",
  },
  iconWrap: { position: "relative", display: "flex", alignItems: "center" },
  passWrap: { position: "relative", display: "flex", alignItems: "center" },
  icon: {
    position: "absolute", left: 12, fontSize: 14, zIndex: 1, pointerEvents: "none",
  },
  input: {
    width: "100%",
    padding: "12px 14px 12px 36px",
    borderRadius: 12,
    border: "1px solid rgba(255,255,255,0.08)",
    background: "rgba(10,8,20,0.7)",
    color: "#e5e7eb",
    fontSize: 14,
    outline: "none",
    boxSizing: "border-box",
  },
  eyeBtn: {
    position: "absolute", right: 12, background: "none",
    border: "none", cursor: "pointer", fontSize: 15, padding: 2,
  },
  matchHint: {
    fontSize: 11, color: "#f87171", margin: "4px 0 0", paddingLeft: 2,
  },
  errorBox: {
    background: "rgba(239,68,68,0.12)",
    border: "1px solid rgba(239,68,68,0.35)",
    color: "#f87171",
    padding: "10px 14px", borderRadius: 10,
    fontSize: 13, marginBottom: 14, textAlign: "center",
  },
  successBox: {
    background: "rgba(34,197,94,0.12)",
    border: "1px solid rgba(34,197,94,0.35)",
    color: "#4ade80",
    padding: "10px 14px", borderRadius: 10,
    fontSize: 13, marginBottom: 14, textAlign: "center",
  },
  btn: {
    width: "100%", padding: 14, borderRadius: 14, border: "none",
    background: "linear-gradient(135deg,#c8ff3e,#8fe600)",
    color: "#000", fontWeight: 900, fontSize: 15, marginBottom: 16,
  },
  divider: {
    display: "flex", alignItems: "center", gap: 10, marginBottom: 16,
  },
  dividerLine: { flex: 1, height: 1, background: "rgba(255,255,255,0.07)" },
  dividerText: { fontSize: 11, color: "#7a6fa3", whiteSpace: "nowrap" },
  loginBtn: {
    width: "100%", padding: 13, borderRadius: 14,
    border: "1px solid rgba(255,255,255,0.1)",
    background: "transparent", color: "#e5e7eb",
    fontWeight: 700, fontSize: 14, cursor: "pointer",
  },
};
