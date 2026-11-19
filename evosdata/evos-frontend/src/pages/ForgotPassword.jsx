import { useState } from "react";
import { smartPost } from "../config";
import { IS_HUB_MOUNT } from "../lib/basePath";
import { hubSignInUrl } from "../lib/hubSession";

// Inside the Hub (evoshub.xyz/evosdata) accounts sign in on the Hub login page,
// and after signing in they land on the Hub's own dashboard (/hub/), not EVOS Data.
// Standalone (evosdata.xyz) uses the in-app login.
const goToLogin = (setPage) => {
  if (IS_HUB_MOUNT) window.location.assign(hubSignInUrl("/hub/"));
  else setPage("login");
};

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
  const [notFound, setNotFound] = useState(false); // "no account with this email" dialog

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
        setSuccess("");
        setStep(2);
      } else {
        setError("Something went wrong. Try again.");
      }
    } catch (err) {
      if (err?.response?.status === 404) setNotFound(true);
      else setError(err?.response?.data?.detail || "Server error. Try again.");
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
        setSuccess("");
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
    // Login and Register both trim the password, so the reset must store the trimmed
    // value too — otherwise a stray space (paste / keyboard autocomplete) makes the
    // new password impossible to sign in with.
    const pw = newPassword.trim();
    const pwConfirm = confirmPassword.trim();
    if (!pw || !pwConfirm) {
      setError("Please fill in both password fields");
      return;
    }
    if (pw.length < 6) {
      setError("Password must be at least 6 characters");
      return;
    }
    if (pw !== pwConfirm) {
      setError("Passwords do not match");
      return;
    }
    try {
      setLoading(true);
      const res = await smartPost(`/auth/reset-password`, {
        email: email.trim().toLowerCase(),
        otp: otp.trim(),
        new_password: pw,
      });
      if (res.data?.status === "success") {
        setSuccess("Password reset successfully! Redirecting to login...");
        setTimeout(() => goToLogin(setPage), 2000);
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
                  ? "linear-gradient(135deg,#ffb020,#f59300)"
                  : "rgba(255,255,255,0.07)",
                color: step >= n ? "#000" : "#6c7a8f",
                fontWeight: step >= n ? 900 : 500,
              }}>
                {step > n ? "✓" : n}
              </div>
              <span style={{
                ...s.stepText,
                color: step >= n ? "#b3bece" : "#36445a",
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
          {step === 1 && "Enter the email on your account. You will receive a 6-digit OTP from the Evoxera Technology Team."}
          {step === 2 && `Expect an OTP from the Evoxera Technology Team. We sent it to ${email.trim().toLowerCase()}. Check your inbox and spam folder.`}
          {step === 3 && "Choose a strong new password"}
        </p>

        {/* No-account dialog (the only popup on this page) */}
        {notFound && (
          <div style={s.overlay} role="alertdialog" aria-modal="true" aria-labelledby="fpNfTitle" onClick={() => setNotFound(false)}>
            <div style={s.dialog} onClick={(e) => e.stopPropagation()}>
              <h3 id="fpNfTitle" style={s.dialogTitle}>No account found</h3>
              <p style={s.dialogText}>
                This email doesn't exist. No account is registered with <b>{email.trim().toLowerCase()}</b>.
                Please check the spelling or use the email you signed up with.
              </p>
              <button style={s.btn} autoFocus onClick={() => setNotFound(false)}>Try another email</button>
            </div>
          </div>
        )}

        {/* Success Banner (only after the password is changed) */}
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
        <button style={s.backBtn} onClick={() => goToLogin(setPage)}>
          ← Back to Sign In
        </button>

        <p style={s.help}>
          Need help? <a href="mailto:support@evoshub.xyz" style={s.resendLink}>support@evoshub.xyz</a>
        </p>

      </div>
    </div>
  );
}

const s = {
  overlay: {
    position: "fixed", inset: 0, background: "rgba(0,0,0,0.6)", zIndex: 1000,
    display: "flex", alignItems: "center", justifyContent: "center", padding: 20,
  },
  dialog: {
    width: "100%", maxWidth: 340, background: "#161e29", borderRadius: 18, padding: "24px 22px 8px",
    border: "1px solid rgba(255,255,255,0.1)", boxShadow: "0 24px 48px rgba(0,0,0,0.5)", textAlign: "center",
  },
  dialogTitle: { margin: "0 0 8px", fontSize: 18, fontWeight: 900, color: "#f87171" },
  dialogText: { margin: "0 0 18px", fontSize: 13, lineHeight: 1.5, color: "#b3bece" },
  help: { fontSize: 12, color: "#8b98ab", textAlign: "center", margin: "16px 0 0" },
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
    background: "rgba(22,30,41,0.92)",
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
    background: "#ffb020",
    boxShadow: "0 0 10px #ffb020",
  },
  brandName: {
    fontSize: 18,
    fontWeight: 900,
    color: "#ffb020",
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
    color: "#8b98ab",
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
    color: "#b3bece",
    marginBottom: 6,
    letterSpacing: "0.04em",
    textTransform: "uppercase",
  },
  input: {
    width: "100%",
    padding: "13px 14px",
    borderRadius: 12,
    border: "1px solid rgba(255,255,255,0.08)",
    background: "rgba(11,16,23,0.7)",
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
    background: "linear-gradient(135deg,#ffb020,#f59300)",
    color: "#000",
    fontWeight: 900,
    fontSize: 15,
    marginBottom: 16,
    letterSpacing: "0.02em",
    transition: "opacity 0.2s",
  },
  resend: {
    fontSize: 12,
    color: "#8b98ab",
    textAlign: "center",
    marginBottom: 16,
    marginTop: -8,
  },
  resendLink: {
    color: "#ffb020",
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
