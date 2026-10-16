import { useState } from "react";
import { loginUser } from "../api";

export default function Login({ setUser, setPage }) {
    const [username, setUsername] = useState("");
    const [password, setPassword] = useState("");
    const [loading, setLoading]   = useState(false);
    const [error, setError]       = useState("");
    const [showPass, setShowPass] = useState(false);

    const handleLogin = async () => {
        setError("");
        if (!username || !password) {
            setError("Please fill in all fields");
            return;
        }
        try {
            setLoading(true);
            const res  = await loginUser({
                username: username.trim().toLowerCase(),
                password: password.trim(),
            });
            const data = res?.data;
            if (!data || data.status !== "ok") {
                setError("Invalid username or password");
                return;
            }
            const user = data.user;
            const normalizedUser = {
                id:            user.id || user.user_id,
                username:      user.username      || "",
                email:         user.email         || "",
                role:          user.role          || "user",
                agent_status:  user.agent_status  || "pending",
                full_name:     user.full_name      || "",
                referral_code: user.referral_code  || "",
                rank:          user.rank           || 1,
                agent_token:   user.agent_token    || null,
                user_token:    user.user_token     || null,
            };

            // Persist user to localStorage (includes agent_token for page refresh rehydration)
            localStorage.setItem("user",      JSON.stringify(normalizedUser));
            localStorage.setItem("email",     normalizedUser.email);
            localStorage.setItem("username",  normalizedUser.username);
            localStorage.setItem("user_id",   normalizedUser.id);

            if (normalizedUser.user_token) localStorage.setItem("userToken", normalizedUser.user_token);

            // FIX: save token to BOTH storages so it's available however the component reads it
            if (normalizedUser.agent_token) {
                sessionStorage.setItem("agentToken", normalizedUser.agent_token);
                localStorage.setItem("agentToken",   normalizedUser.agent_token);
            }

            // FIX: set user in state BEFORE navigating so dashboard gets agent_token immediately
            setUser(normalizedUser);

            if (normalizedUser.role === "agent" && normalizedUser.agent_status === "approved") {
                setPage("agent-dashboard");
            } else {
                setPage("dashboard");
            }
        } catch (err) {
            setError(err?.response?.data?.detail || "Server error. Try again.");
        } finally {
            setLoading(false);
        }
    };

    return (
        <div style={s.page}>
            <div style={s.card}>
                <div style={s.brand}>
                    <div style={s.brandDot} />
                    <span style={s.brandName}>EVOS</span>
                </div>
                <h2 style={s.title}>Welcome back</h2>
                <p style={s.sub}>Sign in to your account</p>

                <div style={s.field}>
                    <label style={s.label}>Username or Email</label>
                    <input
                        style={s.input}
                        placeholder="e.g. john_doe"
                        value={username}
                        onChange={(e) => setUsername(e.target.value)}
                        onKeyDown={(e) => e.key === "Enter" && handleLogin()}
                        autoComplete="username"
                    />
                </div>

                <div style={s.field}>
                    <label style={s.label}>Password</label>
                    <div style={s.passWrap}>
                        <input
                            style={{ ...s.input, marginBottom: 0, paddingRight: 44 }}
                            placeholder="Enter password"
                            type={showPass ? "text" : "password"}
                            value={password}
                            onChange={(e) => setPassword(e.target.value)}
                            onKeyDown={(e) => e.key === "Enter" && handleLogin()}
                            autoComplete="current-password"
                        />
                        <button style={s.eyeBtn} onClick={() => setShowPass(!showPass)} tabIndex={-1}>
                            {showPass ? "🙈" : "👁"}
                        </button>
                    </div>
                </div>

                <p style={s.forgotLink} onClick={() => setPage("forgot-password")}>
                    Forgot password?
                </p>

                {error && <div style={s.errorBox}>{error}</div>}

                <button
                    onClick={handleLogin}
                    disabled={loading}
                    style={{ ...s.btn, opacity: loading ? 0.65 : 1, cursor: loading ? "not-allowed" : "pointer" }}
                >
                    {loading ? "Signing in..." : "Sign In"}
                </button>

                <div style={s.divider}>
                    <div style={s.dividerLine} />
                    <span style={s.dividerText}>or</span>
                    <div style={s.dividerLine} />
                </div>

                <button style={s.registerBtn} onClick={() => setPage("register")}>
                    Create an account
                </button>

                <p style={s.footer}>
                    By signing in you agree to our{" "}
                    <span style={s.footerLink}>Terms of Service</span>
                </p>
            </div>
        </div>
    );
}

const s = {
    page:        { minHeight: "calc(100dvh - var(--dock, 0px) - 58px)", display: "flex", alignItems: "center", justifyContent: "center", padding: "20px 16px" },
    card:        { width: "100%", maxWidth: 400, background: "rgba(22,17,38,0.92)", backdropFilter: "blur(20px)", WebkitBackdropFilter: "blur(20px)", borderRadius: 24, padding: "36px 28px", border: "1px solid rgba(255,255,255,0.08)", boxShadow: "0 32px 64px rgba(0,0,0,0.5)", display: "flex", flexDirection: "column", gap: 0 },
    brand:       { display: "flex", alignItems: "center", gap: 8, marginBottom: 24, justifyContent: "center" },
    brandDot:    { width: 10, height: 10, borderRadius: "50%", background: "#c8ff3e", boxShadow: "0 0 10px #c8ff3e" },
    brandName:   { fontSize: 18, fontWeight: 900, color: "#c8ff3e", letterSpacing: "0.15em" },
    title:       { fontSize: 24, fontWeight: 900, color: "#e5e7eb", margin: "0 0 6px", textAlign: "center" },
    sub:         { fontSize: 13, color: "#9189b5", textAlign: "center", margin: "0 0 28px" },
    field:       { marginBottom: 16 },
    label:       { display: "block", fontSize: 12, color: "#b4acd0", marginBottom: 6, letterSpacing: "0.04em", textTransform: "uppercase" },
    input:       { width: "100%", padding: "13px 14px", borderRadius: 12, border: "1px solid rgba(255,255,255,0.08)", background: "rgba(10,8,20,0.7)", color: "#e5e7eb", fontSize: 14, outline: "none", boxSizing: "border-box", marginBottom: 0, transition: "border-color 0.15s" },
    passWrap:    { position: "relative" },
    eyeBtn:      { position: "absolute", right: 12, top: "50%", transform: "translateY(-50%)", background: "none", border: "none", cursor: "pointer", fontSize: 16, padding: 2, lineHeight: 1 },
    forgotLink:  { textAlign: "right", fontSize: 12, color: "#c8ff3e", cursor: "pointer", margin: "-8px 0 16px", fontWeight: 600 },
    errorBox:    { background: "rgba(239,68,68,0.12)", border: "1px solid rgba(239,68,68,0.35)", color: "#f87171", padding: "10px 14px", borderRadius: 10, fontSize: 13, marginBottom: 16, textAlign: "center" },
    btn:         { width: "100%", padding: "14px", borderRadius: 14, border: "none", background: "linear-gradient(135deg,#c8ff3e,#8fe600)", color: "#000", fontWeight: 900, fontSize: 15, marginBottom: 16, letterSpacing: "0.02em" },
    divider:     { display: "flex", alignItems: "center", gap: 10, marginBottom: 16 },
    dividerLine: { flex: 1, height: 1, background: "rgba(255,255,255,0.07)" },
    dividerText: { fontSize: 12, color: "#7a6fa3" },
    registerBtn: { width: "100%", padding: "13px", borderRadius: 14, border: "1px solid rgba(255,255,255,0.1)", background: "transparent", color: "#e5e7eb", fontWeight: 700, fontSize: 14, cursor: "pointer", marginBottom: 20 },
    footer:      { textAlign: "center", fontSize: 11, color: "#7a6fa3", margin: 0 },
    footerLink:  { color: "#c8ff3e", cursor: "pointer" },
};
