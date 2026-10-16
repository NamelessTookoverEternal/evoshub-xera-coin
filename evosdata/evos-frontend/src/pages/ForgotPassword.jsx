import { useState } from "react";
import { smartPost } from "../config";

export default function ForgotPassword({ setPage }) {
  const [step, setStep] = useState(1); // 1 = email, 2 = otp, 3 = new password
  const [email, setEmail] = useState("");
  const [otp, setOtp] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPass, setShowPass] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  // ── Step 1: Send OTP ──
  const handleSendOTP = async () => {
    setError("");
    if (!email.trim()) {
      setError("Please enter your email address");
      return;
    }
    try {
      setLoading(true);
      const res = await smartPost(`/auth/forgot-password`, {
        email: email.trim().toLowerCase(),
      });
      if (res.data?.status === "sent") {
        setSuccess("OTP sent! Check your email inbox.");
        setStep(2);
      } else {
        setError("Something went wrong. Try again.");
      }
    } catch (err) {
      setError(err?.response?.data?.detail || "Server error. Try again.");
    } finally {
      setLoading(false);
    }
  };

  // ── Step 2: Verify OTP ──
  const handleVerifyOTP = async () => {
    setError("");
    if (!otp.trim() || otp.length !== 6) {
      setError("Please enter the 6-digit OTP");
      return;
    }
    try {
      setLoading(true);
      const res = await smartPost(`/auth/verify-otp`, {
        email: email.trim().toLowerCase(),
        otp: otp.trim(),
      });
      if (res.data?.status === "valid") {
        setSuccess("OTP verified! Set your new password.");
        setStep(3);
      } else {
        setError("Invalid or expired OTP. Try again.");
      }
    } catch (err) {
      setError(err?.response?.data?.detail || "Invalid or expired OTP.");
    } finally {
      setLoading(false);
    }
  };

  // ── Step 3: Reset Password ──
  const handleResetPassword = async () => {
    setError("");
    if (!newPassword || !confirmPassword) {
      setError("Please fill in both password fields");
      return;
    }
    if (newPassword.length < 6) {
      setError("Password must be at least 6 characters");
      return;
    }
    if (newPassword !== confirmPassword) {
      setError("Passwords do not match");
      return;
    }
    try {
      setLoading(true);
      const res = await smartPost(`/auth/reset-password`, {
        email: email.trim().toLowerCase(),
        otp: otp.trim(),
        new_password: newPassword,
      });
      if (res.data?.status === "success") {
        setSuccess("Password reset successfully! Redirecting to login...");
        setTimeout(() => setPage("login"), 2000);
      } else {
        setError("Reset failed. Please try again.");
      }
    } catch (err) {
      setError(err?.response?.data?.detail || "Server error. Try again.");
    } finally {
      setLoading(false);
    }
  };

  const stepLabel = ["Enter Email", "Verify OTP", "New Password"];

  return (
    <div style={s.page}>
      <div style={s.card}>

        {/* Brand */}
        <div style={s.brand}>
          <div style={s.brandDot} />
          <span style={s.brandName}>EVOS</span>
        </div>

        {/* Step Indicator */}
        <div style={s.steps}>
          {[1, 2, 3].map((n) => (
            <div key={n} style={s.stepItem}>
              <div style={{
                ...s.stepCircle,
                background: step >= n
                  ? "linear-gradient(135deg,#c8ff3e,#8fe600)"
                  : "rgba(255,255,255,0.07)",
                color: step >= n ? "#000" : "#7a6fa3",
                fontWeight: step >= n ? 900 : 500,
              }}>
                {step > n ? "✓" : n}
              </div>
              <span style={{
                ...s.stepText,
                color: step >= n ? "#b4acd0" : "#3d3460",
              }}>
                {stepLabel[n - 1]}
              </span>
            </div>
          ))}
        </div>

        <h2 style={s.title}>
          {step === 1 && "Forgot Password"}
          {step === 2 && "Enter OTP"}
          {step === 3 && "New Password"}
        </h2>
        <p style={s.sub}>
          {step === 1 && "We'll send a 6-digit OTP to your email"}
          {step === 2 && `OTP sent to ${email}`}
          {step === 3 && "Choose a strong new password"}
        </p>

        {/* Success Banner */}
        {success && (
          <div style={s.successBox}>{success}</div>
        )}

        {/* ── STEP 1: Email ── */}
        {step === 1 && (
          <div style={s.field}>
            <label style={s.label}>Email Address</label>
            <input
              style={s.input}
              placeholder="e.g. john@gmail.com"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSendOTP()}
              autoComplete="email"
            />
          </div>
        )}

        {/* ── STEP 2: OTP ── */}
        {step === 2 && (
          <>
            <div style={s.field}>
              <label style={s.label}>6-Digit OTP</label>
              <input
                style={{ ...s.input, letterSpacing: "0.3em", fontSize: 20, textAlign: "center" }}
                placeholder="000000"
                type="text"
                inputMode="numeric"
                maxLength={6}
                value={otp}
                onChange={(e) => setOtp(e.target.value.replace(/\D/g, ""))}
                onKeyDown={(e) => e.key === "Enter" && handleVerifyOTP()}
                autoComplete="one-time-code"
              />
            </div>
            <p style={s.resend}>
              Didn't get it?{" "}
              <span
                style={s.resendLink}
                onClick={() => {
                  setStep(1);
                  setOtp("");
                  setError("");
                  setSuccess("");
                }}
              >
                Resend OTP
              </span>
            </p>
          </>
        )}

        {/* ── STEP 3: New Password ── */}
        {step === 3 && (
          <>
            <div style={s.field}>
              <label style={s.label}>New Password</label>
              <div style={s.passWrap}>
                <input
                  style={{ ...s.input, paddingRight: 44 }}
                  placeholder="Min. 6 characters"
                  type={showPass ? "text" : "password"}
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  autoComplete="new-password"
                />
                <button style={s.eyeBtn} onClick={() => setShowPass(!showPass)} tabIndex={-1}>
                  {showPass ? "🙈" : "👁"}
                </button>
              </div>
            </div>
            <div style={s.field}>
              <label style={s.label}>Confirm Password</label>
              <div style={s.passWrap}>
                <input
                  style={{ ...s.input, paddingRight: 44 }}
                  placeholder="Repeat password"
                  type={showConfirm ? "text" : "password"}
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleResetPassword()}
                  autoComplete="new-password"
                />
                <button style={s.eyeBtn} onClick={() => setShowConfirm(!showConfirm)} tabIndex={-1}>
                  {showConfirm ? "🙈" : "👁"}
                </button>
              </div>
            </div>
          </>
        )}

        {/* Error */}
        {error && <div style={s.errorBox}>{error}</div>}

        {/* CTA Button */}
        <button
          onClick={
            step === 1 ? handleSendOTP :
            step === 2 ? handleVerifyOTP :
            handleResetPassword
          }
          disabled={loading}
          style={{ ...s.btn, opacity: loading ? 0.65 : 1, cursor: loading ? "not-allowed" : "pointer" }}
        >
          {loading
            ? "Please wait..."
            : step === 1 ? "Send OTP"
            : step === 2 ? "Verify OTP"
            : "Reset Password"
          }
        </button>

        {/* Back to Login */}
        <button style={s.backBtn} onClick={() => setPage("login")}>
          ← Back to Sign In
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
    maxWidth: 400,
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
    marginBottom: 24,
    justifyContent: "center",
  },
  brandDot: {
    width: 10,
    height: 10,
    borderRadius: "50%",
    background: "#c8ff3e",
    boxShadow: "0 0 10px #c8ff3e",
  },
  brandName: {
    fontSize: 18,
    fontWeight: 900,
    color: "#c8ff3e",
    letterSpacing: "0.15em",
  },
  steps: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "flex-start",
    marginBottom: 24,
    position: "relative",
  },
  stepItem: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    gap: 6,
    flex: 1,
  },
  stepCircle: {
    width: 32,
    height: 32,
    borderRadius: "50%",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    fontSize: 13,
    transition: "all 0.3s",
  },
  stepText: {
    fontSize: 10,
    textTransform: "uppercase",
    letterSpacing: "0.04em",
    textAlign: "center",
  },
  title: {
    fontSize: 24,
    fontWeight: 900,
    color: "#e5e7eb",
    margin: "0 0 6px",
    textAlign: "center",
  },
  sub: {
    fontSize: 13,
    color: "#9189b5",
    textAlign: "center",
    margin: "0 0 24px",
  },
  successBox: {
    background: "rgba(34,197,94,0.12)",
    border: "1px solid rgba(34,197,94,0.35)",
    color: "#4ade80",
    padding: "10px 14px",
    borderRadius: 10,
    fontSize: 13,
    marginBottom: 16,
    textAlign: "center",
  },
  field: {
    marginBottom: 16,
  },
  label: {
    display: "block",
    fontSize: 12,
    color: "#b4acd0",
    marginBottom: 6,
    letterSpacing: "0.04em",
    textTransform: "uppercase",
  },
  input: {
    width: "100%",
    padding: "13px 14px",
    borderRadius: 12,
    border: "1px solid rgba(255,255,255,0.08)",
    background: "rgba(10,8,20,0.7)",
    color: "#e5e7eb",
    fontSize: 14,
    outline: "none",
    boxSizing: "border-box",
    transition: "border-color 0.15s",
  },
  passWrap: {
    position: "relative",
  },
  eyeBtn: {
    position: "absolute",
    right: 12,
    top: "50%",
    transform: "translateY(-50%)",
    background: "none",
    border: "none",
    cursor: "pointer",
    fontSize: 16,
    padding: 2,
    lineHeight: 1,
  },
  errorBox: {
    background: "rgba(239,68,68,0.12)",
    border: "1px solid rgba(239,68,68,0.35)",
    color: "#f87171",
    padding: "10px 14px",
    borderRadius: 10,
    fontSize: 13,
    marginBottom: 16,
    textAlign: "center",
  },
  btn: {
    width: "100%",
    padding: "14px",
    borderRadius: 14,
    border: "none",
    background: "linear-gradient(135deg,#c8ff3e,#8fe600)",
    color: "#000",
    fontWeight: 900,
    fontSize: 15,
    marginBottom: 16,
    letterSpacing: "0.02em",
    transition: "opacity 0.2s",
  },
  resend: {
    fontSize: 12,
    color: "#9189b5",
    textAlign: "center",
    marginBottom: 16,
    marginTop: -8,
  },
  resendLink: {
    color: "#c8ff3e",
    cursor: "pointer",
    fontWeight: 700,
  },
  backBtn: {
    width: "100%",
    padding: "13px",
    borderRadius: 14,
    border: "1px solid rgba(255,255,255,0.1)",
    background: "transparent",
    color: "#e5e7eb",
    fontWeight: 700,
    fontSize: 14,
    cursor: "pointer",
  },
};
