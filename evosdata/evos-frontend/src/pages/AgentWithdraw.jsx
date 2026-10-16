import { useEffect, useState } from "react";

import { smartFetch } from "../config";
const NETWORKS = ["MTN", "TELECEL", "AIRTELTIGO"];
const NETWORK_LABELS = { MTN: "MTN", TELECEL: "Telecel", AIRTELTIGO: "AirtelTigo" };
const DEFAULT_FEE_PERCENT = 4; // fallback used only until /agent/withdraw/fee-info loads

// ── temporary provider availability flags ───────────────────────────
// Moolre is disabled for now — flip this back to true when it's ready.
const MOOLRE_ENABLED = false;

// ── withdrawal day restriction ───────────────────────────────────────
// Withdrawals are only allowed on Monday (1), Wednesday (3), and Thursday (4).
// getDay(): Sun=0, Mon=1, Tue=2, Wed=3, Thu=4, Fri=5, Sat=6
const ALLOWED_WITHDRAWAL_DAYS = [1, 3, 4];
const WITHDRAWAL_DAY_LABELS = "Mondays, Wednesdays & Thursdays";
const DAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

function isWithdrawalDayAllowed() {
  return ALLOWED_WITHDRAWAL_DAYS.includes(new Date().getDay());
}

export default function AgentWithdraw({ user, setPage }) {
  // ── step 1 = provider, 2 = amount, 3 = number+network, 4 = confirm ──
  const [step, setStep] = useState(1);

  const [provider, setProvider] = useState(""); // "paystack" | "moolre"
  const [amount, setAmount] = useState("");
  const [mobileNumber, setMobileNumber] = useState("");
  const [network, setNetwork] = useState("");

  // resolved in step 4
  const [resolvedName, setResolvedName] = useState("");
  const [recipientCode, setRecipientCode] = useState(""); // returned by verify-account (Paystack)

  const [wallet, setWallet] = useState(0);
  const [feePercent, setFeePercent] = useState(DEFAULT_FEE_PERCENT);
  const [loading, setLoading] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [message, setMessage] = useState({ text: "", ok: false });
  const [done, setDone] = useState(false);
  const [receivedAmount, setReceivedAmount] = useState(0); // actual payout after fee, set on success
  const [showPolicy, setShowPolicy] = useState(false);

  const withdrawalAllowedToday = isWithdrawalDayAllowed();
  const todayName = DAY_NAMES[new Date().getDay()];

  // ── fee math helper ──────────────────────────────────────────────
  const feeFor = (amt) => {
    const a = Number(amt) || 0;
    const fee = Math.round(a * (feePercent / 100) * 100) / 100;
    const payout = Math.round((a - fee) * 100) / 100;
    return { fee, payout };
  };

  // ── load wallet + fee rate ───────────────────────────────────────
  useEffect(() => {
    if (!user?.id) return;
    (async () => {
      try {
        const token = sessionStorage.getItem("agentToken");
        const res = await smartFetch(`/agent/dashboard/${user.id}`, {
          headers: { "X-Agent-Token": token },
        });
        const data = await res.json();
        setWallet(Number(data.wallet_balance || 0));
      } catch {
        /* silent */
      }
    })();

    (async () => {
      try {
        const res = await smartFetch(`/agent/withdraw/fee-info`);
        const data = await res.json();
        if (data?.fee_percent != null) setFeePercent(Number(data.fee_percent));
      } catch {
        /* silent — keep DEFAULT_FEE_PERCENT */
      }
    })();
  }, [user]);

  const say = (text, ok = false) => setMessage({ text, ok });
  const clear = () => setMessage({ text: "", ok: false });

  // ── safe fetch helper: never throws on non-2xx, always returns parsed data ──
  const safeFetch = async (path, options = {}) => {
    const res = await smartFetch(path, options);
    const text = await res.text();
    try {
      return { ok: res.ok, status: res.status, data: JSON.parse(text) };
    } catch {
      // backend returned HTML (500 page) or empty body
      console.error("Non-JSON response from", path, "→", text.slice(0, 200));
      return {
        ok: false,
        status: res.status,
        data: { error: `Server error (${res.status}) — check Supabase migration & backend deploy.` },
      };
    }
  };

  // ── step validators ────────────────────────────────────────────────
  const validateStep1 = () => {
    if (!withdrawalAllowedToday) {
      say(`Withdrawals are only available on ${WITHDRAWAL_DAY_LABELS}. Please come back on the next available day.`);
      return false;
    }
    if (!provider) { say("Choose a withdrawal method to continue."); return false; }
    return true;
  };

  const validateStep2 = () => {
    const amt = Number(amount);
    if (!amt || amt <= 0) { say("Enter a valid amount."); return false; }
    if (amt < 5)          { say("Minimum withdrawal is GH₵ 5."); return false; }
    if (amt > wallet)     { say("Amount exceeds your available balance."); return false; }
    return true;
  };

  const validateStep3 = () => {
    const cleaned = mobileNumber.replace(/[\s\-()]/g, "");
    if (!network)              { say("Select your mobile money network."); return false; }
    if (cleaned.length < 9)    { say("Enter a valid mobile number."); return false; }
    return true;
  };

  // ── step 3 → 4: verify account name ───────────────────────────────
  const verifyAccount = async () => {
    if (!withdrawalAllowedToday) {
      say(`Withdrawals are only available on ${WITHDRAWAL_DAY_LABELS}.`);
      return;
    }
    if (!validateStep3()) return;

    // Moolre has no name-lookup — skip directly to confirm
    if (provider === "moolre") {
      setResolvedName("");
      setRecipientCode("");
      setStep(4);
      clear();
      return;
    }

    setVerifying(true);
    clear();
    try {
      const token = sessionStorage.getItem("agentToken");
      const { data } = await safeFetch(`/agent/withdraw/verify-account`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Agent-Token": token },
        body: JSON.stringify({
          agent_id: user.id,
          mobile_number: mobileNumber.replace(/[\s\-()]/g, ""),
          network,
          provider,
        }),
      });

      if (data.status !== "success") {
        // If Paystack can't verify, still let agent proceed — they accepted the risk warning
        setResolvedName("");
        setRecipientCode("");
        setStep(4);
        say(data.message || "Account name could not be verified. Confirm only if you are sure the number is correct.");
      } else {
        setResolvedName(data.account_name || "");
        setRecipientCode(data.recipient_code || "");
        setStep(4);
        clear();
      }
    } catch (err) {
      console.error("verifyAccount error:", err);
      say("Could not reach the server. Check your connection and try again.");
    } finally {
      setVerifying(false);
    }
  };

  // ── final withdraw ─────────────────────────────────────────────────
  const withdraw = async () => {
    if (!withdrawalAllowedToday) {
      say(`Withdrawals are only available on ${WITHDRAWAL_DAY_LABELS}.`);
      return;
    }
    setLoading(true);
    clear();
    try {
      const token = sessionStorage.getItem("agentToken");
      const { ok, status, data } = await safeFetch(`/agent/withdraw`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Agent-Token": token },
        body: JSON.stringify({
          agent_id: user.id,
          amount: Number(amount),
          mobile_number: mobileNumber.replace(/[\s\-()]/g, ""),
          network,
          account_name: resolvedName,
          provider,
        }),
      });

      if (data.status === "success") {
        // Wallet is always debited the FULL amount the agent typed — the fee
        // is taken out of what actually gets sent out, not out of the wallet
        // twice. Prefer the payout_amount the backend computed; fall back to
        // a local calculation if it's ever missing.
        const payout = data.payout_amount != null ? Number(data.payout_amount) : feeFor(amount).payout;
        setWallet((p) => p - Number(amount));
        setReceivedAmount(payout);
        setDone(true);
        say(data.message || "Transfer initiated. Funds will arrive shortly.", true);
      } else {
        // Show the real error so the agent knows exactly what went wrong
        const errText = data.error || data.message || data.detail || `Request failed (HTTP ${status})`;
        say(errText);
        console.error("Withdraw API error:", status, data);
      }
    } catch (err) {
      console.error("Withdraw fetch error:", err);
      say("Could not reach the server. Check your connection and try again.");
    } finally {
      setLoading(false);
    }
  };

  const reset = () => {
    setStep(1); setProvider(""); setAmount(""); setMobileNumber("");
    setNetwork(""); setResolvedName(""); setRecipientCode("");
    setDone(false); setReceivedAmount(0); clear();
  };

  // ── shared styles ──────────────────────────────────────────────────
  const S = styles;
  const { fee: previewFee, payout: previewPayout } = feeFor(amount);

  // ── success screen ─────────────────────────────────────────────────
  if (done) {
    return (
      <div style={S.container}>
        <div style={S.successCard}>
          <div style={S.successIcon}>✅</div>
          <h2 style={S.successTitle}>Transfer Initiated</h2>
          <p style={S.successSub}>
            {message.text || (
              <>
                GH₵ {receivedAmount.toFixed(2)} is on its way to {mobileNumber}.
                Instant transfer — funds typically arrive within minutes.
              </>
            )}
          </p>
          <div style={S.successMeta}>
            <span style={S.metaLabel}>Withdrawn from wallet</span>
            <span style={S.metaValue}>GH₵ {Number(amount).toFixed(2)}</span>
          </div>
          <div style={S.successMeta}>
            <span style={S.metaLabel}>Liquidity fee ({feePercent}%)</span>
            <span style={S.metaValue}>GH₵ {(Number(amount) - receivedAmount).toFixed(2)}</span>
          </div>
          <div style={S.successMeta}>
            <span style={S.metaLabel}>You'll receive</span>
            <span style={{ ...S.metaValue, color: "#4ade80" }}>GH₵ {receivedAmount.toFixed(2)}</span>
          </div>
          <div style={S.successMeta}>
            <span style={S.metaLabel}>Via</span>
            <span style={S.metaValue}>{provider === "paystack" ? "Paystack" : "Moolre"}</span>
          </div>
          {resolvedName ? (
            <div style={S.successMeta}>
              <span style={S.metaLabel}>Account</span>
              <span style={S.metaValue}>{resolvedName}</span>
            </div>
          ) : null}
          <div style={S.successMeta}>
            <span style={S.metaLabel}>New wallet balance</span>
            <span style={S.metaValue}>GH₵ {wallet.toFixed(2)}</span>
          </div>
          <button onClick={reset} style={{ ...S.primaryBtn, marginTop: 20 }}>
            Make Another Withdrawal
          </button>
          <button onClick={() => setPage("agent-dashboard")} style={S.ghostBtn}>
            Back to Dashboard
          </button>
        </div>
        <Footer />
      </div>
    );
  }

  // ── blocked screen: outside allowed withdrawal days ─────────────────
  if (!withdrawalAllowedToday) {
    return (
      <div style={S.container}>
        <div style={S.header}>
          <h2 style={S.title}>Withdraw Funds</h2>
          <div style={S.balancePill}>
            GH₵ {wallet.toFixed(2)} available
          </div>
        </div>

        <div style={S.blockedCard}>
          <div style={S.blockedIcon}>🗓️</div>
          <h3 style={S.blockedTitle}>Withdrawals Unavailable Today</h3>
          <p style={S.blockedSub}>
            It's {todayName}. Withdrawals can only be made on {WITHDRAWAL_DAY_LABELS}.
            Please check back on the next available day — your wallet balance is safe
            and stays exactly as it is until then.
          </p>
        </div>

        <div onClick={() => setShowPolicy(true)} style={S.policyLink}>
          View Withdrawal Policy &amp; Rules
        </div>

        <button onClick={() => setPage("agent-dashboard")} style={{ ...S.ghostBtn, marginTop: 8 }}>
          Back to Dashboard
        </button>
        <Footer />
        {showPolicy && (
          <PolicyModal feePercent={feePercent} onClose={() => setShowPolicy(false)} />
        )}
      </div>
    );
  }

  return (
    <div style={S.container}>
      {/* header */}
      <div style={S.header}>
        <h2 style={S.title}>Withdraw Funds</h2>
        <div style={S.balancePill}>
          GH₵ {wallet.toFixed(2)} available
        </div>
      </div>

      {/* step tracker */}
      <div style={S.stepTrack}>
        {["Method", "Amount", "Details", "Confirm"].map((label, i) => {
          const n = i + 1;
          const active = step === n;
          const done_  = step > n;
          return (
            <div key={n} style={S.stepItem}>
              <div style={{
                ...S.stepDot,
                background: done_ ? "#22c55e" : active ? "#c8ff3e" : "rgba(255,255,255,0.08)",
                color:      done_ || active ? "#000" : "#7a6fa3",
                border:     active ? "2px solid #c8ff3e" : done_ ? "2px solid #22c55e" : "2px solid rgba(255,255,255,0.08)",
              }}>
                {done_ ? "✓" : n}
              </div>
              <span style={{ ...S.stepLabel, color: active ? "#e9e5f6" : "#7a6fa3" }}>{label}</span>
            </div>
          );
        })}
      </div>

      {/* message */}
      {message.text && (
        <div style={{
          ...S.msgBox,
          background: message.ok ? "rgba(34,197,94,0.12)" : "rgba(239,68,68,0.12)",
          border:     message.ok ? "1px solid rgba(34,197,94,0.35)" : "1px solid rgba(239,68,68,0.35)",
          color:      message.ok ? "#4ade80" : "#f87171",
        }}>
          {message.text}
        </div>
      )}

      {/* ── STEP 1: choose provider ─────────────────────────────────── */}
      {step === 1 && (
        <div>
          <p style={S.stepHeading}>How would you like to withdraw?</p>
          <div style={S.providerGrid}>
            <div
              onClick={() => { setProvider("paystack"); clear(); }}
              style={{
                ...S.providerCard,
                border: provider === "paystack"
                  ? "2px solid #c8ff3e"
                  : "2px solid rgba(255,255,255,0.07)",
                background: provider === "paystack"
                  ? "rgba(200,255,62,0.08)"
                  : "rgba(22,17,38,0.7)",
              }}
            >
              <div style={S.providerIcon}>🏦</div>
              <div style={S.providerName}>
                Paystack <span style={S.instantBadge}>⚡ Instant</span>
              </div>
              <div style={S.providerDesc}>
                Instant settlement · resolves account name before sending
              </div>
              {provider === "paystack" && <div style={S.providerCheck}>✓</div>}
            </div>

            <div
              onClick={() => {
                if (!MOOLRE_ENABLED) return;
                setProvider("moolre"); clear();
              }}
              aria-disabled={!MOOLRE_ENABLED}
              style={{
                ...S.providerCard,
                cursor: MOOLRE_ENABLED ? "pointer" : "not-allowed",
                opacity: MOOLRE_ENABLED ? 1 : 0.45,
                border: provider === "moolre"
                  ? "2px solid #a78bfa"
                  : "2px solid rgba(255,255,255,0.07)",
                background: provider === "moolre"
                  ? "rgba(167,139,250,0.08)"
                  : "rgba(22,17,38,0.7)",
              }}
            >
              <div style={S.providerIcon}>📱</div>
              <div style={S.providerName}>Moolre</div>
              <div style={S.providerDesc}>
                Alternative transfer route · supports all Ghana networks
              </div>
              {!MOOLRE_ENABLED && <div style={S.comingSoonBadge}>Coming soon</div>}
              {MOOLRE_ENABLED && provider === "moolre" && (
                <div style={{ ...S.providerCheck, color: "#a78bfa" }}>✓</div>
              )}
            </div>
          </div>

          <div style={S.feeNotice}>
            ⚡ Withdrawals are instant and fast — funds typically land in your mobile money
            wallet within minutes.
            <br />
            ℹ️ A {feePercent}% liquidity fee applies to all withdrawals. It's deducted from
            the payout, not added on top — your wallet is only ever charged what you type in.
            <br />
            📅 Withdrawals are only processed on {WITHDRAWAL_DAY_LABELS}.
          </div>

          <div onClick={() => setShowPolicy(true)} style={S.policyLink}>
            View Withdrawal Policy &amp; Rules
          </div>

          <button
            onClick={() => { if (validateStep1()) { clear(); setStep(2); } }}
            style={S.primaryBtn}
          >
            Continue →
          </button>
        </div>
      )}

      {/* ── STEP 2: amount ─────────────────────────────────────────── */}
      {step === 2 && (
        <div>
          <p style={S.stepHeading}>How much do you want to withdraw?</p>

          <label style={S.label}>Amount (GH₵)</label>
          <input
            type="number"
            inputMode="decimal"
            placeholder="e.g. 100"
            value={amount}
            onChange={(e) => { setAmount(e.target.value); clear(); }}
            style={S.input}
            autoFocus
          />

          {/* quick-pick */}
          <div style={S.quickRow}>
            {[10, 20, 50, 100].map((v) => (
              <div
                key={v}
                onClick={() => { setAmount(String(v)); clear(); }}
                style={{
                  ...S.quickChip,
                  background: Number(amount) === v ? "#c8ff3e" : "rgba(255,255,255,0.05)",
                  color:      Number(amount) === v ? "#000" : "#b4acd0",
                  border:     Number(amount) === v ? "1px solid #c8ff3e" : "1px solid rgba(255,255,255,0.08)",
                }}
              >
                GH₵ {v}
              </div>
            ))}
          </div>

          {/* live fee breakdown */}
          {Number(amount) > 0 && (
            <div style={S.feeBreakdown}>
              <div style={S.feeRow}>
                <span style={S.feeLabel}>You're withdrawing</span>
                <span style={S.feeValue}>GH₵ {Number(amount).toFixed(2)}</span>
              </div>
              <div style={S.feeRow}>
                <span style={S.feeLabel}>Liquidity fee ({feePercent}%)</span>
                <span style={{ ...S.feeValue, color: "#f87171" }}>− GH₵ {previewFee.toFixed(2)}</span>
              </div>
              <div style={{ ...S.feeRow, ...S.feeRowFinal }}>
                <span style={{ ...S.feeLabel, fontWeight: 800, color: "#d9d4ec" }}>You'll receive</span>
                <span style={{ ...S.feeValue, fontWeight: 900, color: "#4ade80" }}>GH₵ {previewPayout.toFixed(2)}</span>
              </div>
            </div>
          )}

          <p style={S.hint}>Max: GH₵ {wallet.toFixed(2)} · Min: GH₵ 5 · ⚡ Instant payout</p>

          <div style={S.navRow}>
            <button onClick={() => { clear(); setStep(1); }} style={S.ghostBtn}>← Back</button>
            <button
              onClick={() => { if (validateStep2()) { clear(); setStep(3); } }}
              style={{ ...S.primaryBtn, flex: 1, marginLeft: 10, marginBottom: 0 }}
            >
              Continue →
            </button>
          </div>
        </div>
      )}

      {/* ── STEP 3: network + number ────────────────────────────────── */}
      {step === 3 && (
        <div>
          <p style={S.stepHeading}>Where should we send it?</p>

          <label style={S.label}>Mobile Money Network</label>
          <div style={S.networkRow}>
            {NETWORKS.map((n) => (
              <div
                key={n}
                onClick={() => { setNetwork(n); clear(); }}
                style={{
                  ...S.networkBtn,
                  background: network === n ? "#c8ff3e" : "rgba(255,255,255,0.05)",
                  color:      network === n ? "#000" : "#e5e7eb",
                  border:     network === n ? "1px solid #c8ff3e" : "1px solid rgba(255,255,255,0.08)",
                  fontWeight: network === n ? 800 : 500,
                }}
              >
                {NETWORK_LABELS[n]}
              </div>
            ))}
          </div>

          <label style={S.label}>Mobile Money Number</label>
          <input
            type="tel"
            inputMode="numeric"
            placeholder="e.g. 0244000000"
            value={mobileNumber}
            onChange={(e) => { setMobileNumber(e.target.value); clear(); }}
            style={S.input}
            autoFocus
          />

          {provider === "paystack" && (
            <p style={S.hint}>
              We'll verify the account name before sending — you'll see it on the next screen.
            </p>
          )}
          {provider === "moolre" && (
            <p style={S.hint}>
              Double-check the number carefully — Moolre does not verify names. Wrong details cannot be reversed.
            </p>
          )}

          <div style={S.navRow}>
            <button onClick={() => { clear(); setStep(2); }} style={S.ghostBtn}>← Back</button>
            <button
              onClick={verifyAccount}
              disabled={verifying}
              style={{ ...S.primaryBtn, flex: 1, marginLeft: 10, marginBottom: 0, opacity: verifying ? 0.6 : 1 }}
            >
              {verifying ? "Verifying…" : "Verify Account →"}
            </button>
          </div>
        </div>
      )}

      {/* ── STEP 4: confirm ─────────────────────────────────────────── */}
      {step === 4 && (
        <div>
          <p style={S.stepHeading}>Confirm your withdrawal</p>

          <div style={S.confirmCard}>
            <ConfirmRow label="Amount"   value={`GH₵ ${Number(amount).toFixed(2)}`} highlight />
            <ConfirmRow label="Liquidity fee" value={`− GH₵ ${previewFee.toFixed(2)} (${feePercent}%)`} warn />
            <ConfirmRow label="You'll receive" value={`GH₵ ${previewPayout.toFixed(2)}`} verified />
            <div style={S.confirmDivider} />
            <ConfirmRow label="To"       value={mobileNumber} />
            <ConfirmRow label="Network"  value={NETWORK_LABELS[network] || network} />
            <ConfirmRow label="Via"      value={provider === "paystack" ? "Paystack" : "Moolre"} />
            {resolvedName ? (
              <ConfirmRow label="Account name" value={resolvedName} verified />
            ) : (
              <ConfirmRow label="Account name" value="Not verified — double-check number" warn />
            )}
            <div style={S.confirmDivider} />
            <ConfirmRow label="Wallet balance after" value={`GH₵ ${(wallet - Number(amount)).toFixed(2)}`} />
          </div>

          {resolvedName ? (
            <div style={S.verifiedBadge}>
              ✅ Account name verified — funds will go to <strong>{resolvedName}</strong>. ⚡ Instant transfer.
            </div>
          ) : (
            <div style={S.warnBadge}>
              ⚠️ No name resolved. Make sure the number is correct before proceeding — transfers cannot be reversed.
            </div>
          )}

          <button
            onClick={withdraw}
            disabled={loading}
            style={{ ...S.primaryBtn, background: "linear-gradient(135deg,#22c55e,#16a34a)", opacity: loading ? 0.6 : 1 }}
          >
            {loading ? "Sending…" : `Confirm & Send GH₵ ${previewPayout.toFixed(2)}`}
          </button>

          <div style={S.navRow}>
            <button onClick={() => { clear(); setStep(3); }} style={{ ...S.ghostBtn, flex: 1 }}>
              ← Edit Details
            </button>
          </div>
        </div>
      )}

      {/* back to dashboard always visible */}
      {!done && (
        <button onClick={() => setPage("agent-dashboard")} style={{ ...S.ghostBtn, marginTop: 8 }}>
          Back to Dashboard
        </button>
      )}

      <Footer />
      {showPolicy && (
        <PolicyModal feePercent={feePercent} onClose={() => setShowPolicy(false)} />
      )}
    </div>
  );
}

// ── policy modal ────────────────────────────────────────────────────
function PolicyModal({ feePercent, onClose }) {
  return (
    <div style={styles.modalOverlay} onClick={onClose}>
      <div style={styles.modalCard} onClick={(e) => e.stopPropagation()}>
        <div style={styles.modalHeader}>
          <span style={styles.modalTitle}>Withdrawal Policy &amp; Rules</span>
          <span style={styles.modalClose} onClick={onClose}>✕</span>
        </div>
        <ul style={styles.modalList}>
          <li>Withdrawals are processed only on {WITHDRAWAL_DAY_LABELS}.</li>
          <li>A {feePercent}% liquidity fee applies to all withdrawals, deducted from the payout — your wallet is only ever charged the amount you type in.</li>
          <li>Minimum withdrawal amount is GH₵ 5.</li>
          <li>Instant transfers cannot be reversed once sent — always double-check the mobile number and network before confirming.</li>
        </ul>
        <button onClick={onClose} style={styles.modalCloseBtn}>Close</button>
      </div>
    </div>
  );
}

// ── footer component ────────────────────────────────────────────────
function Footer() {
  return (
    <div style={styles.footer}>
      © 2026 Evosdata Services. Evos Business Hub
      <br />
      By Evoxera Technology
    </div>
  );
}

// ── small confirm row component ─────────────────────────────────────
function ConfirmRow({ label, value, highlight, verified, warn }) {
  return (
    <div style={{
      display: "flex",
      justifyContent: "space-between",
      alignItems: "center",
      padding: "9px 0",
      borderBottom: "1px solid rgba(255,255,255,0.05)",
    }}>
      <span style={{ fontSize: 13, color: "#9189b5" }}>{label}</span>
      <span style={{
        fontSize: highlight ? 16 : 13,
        fontWeight: highlight ? 900 : 600,
        color: highlight ? "#c8ff3e" : verified ? "#4ade80" : warn ? "#f87171" : "#e9e5f6",
      }}>
        {value}
      </span>
    </div>
  );
}

// ── styles ──────────────────────────────────────────────────────────
const styles = {
  container: {
    maxWidth: 480,
    margin: "0 auto",
    padding: "20px 18px 40px",
    color: "#e5e7eb",
  },
  header: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 20,
  },
  title: {
    fontSize: 22,
    fontWeight: 900,
    margin: 0,
  },
  balancePill: {
    fontSize: 12,
    fontWeight: 700,
    color: "#c8ff3e",
    background: "rgba(200,255,62,0.1)",
    border: "1px solid rgba(200,255,62,0.25)",
    padding: "5px 12px",
    borderRadius: 20,
  },

  // step tracker
  stepTrack: {
    display: "flex",
    justifyContent: "space-between",
    marginBottom: 24,
    position: "relative",
  },
  stepItem: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    gap: 5,
    flex: 1,
  },
  stepDot: {
    width: 30,
    height: 30,
    borderRadius: "50%",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    fontSize: 12,
    fontWeight: 800,
    transition: "0.2s",
  },
  stepLabel: {
    fontSize: 10,
    fontWeight: 600,
    textTransform: "uppercase",
    letterSpacing: 0.5,
  },

  msgBox: {
    padding: "12px 14px",
    borderRadius: 10,
    fontSize: 13,
    marginBottom: 16,
    lineHeight: 1.5,
  },

  stepHeading: {
    fontSize: 15,
    fontWeight: 700,
    color: "#d9d4ec",
    marginBottom: 18,
    marginTop: 4,
  },

  // provider cards
  providerGrid: {
    display: "flex",
    flexDirection: "column",
    gap: 12,
    marginBottom: 16,
  },
  providerCard: {
    padding: "16px 18px",
    borderRadius: 14,
    cursor: "pointer",
    position: "relative",
    transition: "0.15s",
  },
  providerIcon: { fontSize: 22, marginBottom: 6 },
  providerName: { fontSize: 15, fontWeight: 800, color: "#e9e5f6", marginBottom: 4, display: "flex", alignItems: "center", gap: 8 },
  providerDesc: { fontSize: 12, color: "#9189b5", lineHeight: 1.5 },
  providerCheck: {
    position: "absolute",
    top: 14,
    right: 16,
    fontSize: 16,
    fontWeight: 900,
    color: "#c8ff3e",
  },
  instantBadge: {
    fontSize: 10,
    fontWeight: 800,
    color: "#facc15",
    background: "rgba(250,204,21,0.1)",
    border: "1px solid rgba(250,204,21,0.3)",
    borderRadius: 20,
    padding: "2px 8px",
  },
  comingSoonBadge: {
    position: "absolute",
    top: 14,
    right: 16,
    fontSize: 10,
    fontWeight: 800,
    color: "#b4acd0",
    background: "rgba(255,255,255,0.06)",
    border: "1px solid rgba(255,255,255,0.12)",
    borderRadius: 20,
    padding: "3px 10px",
    textTransform: "uppercase",
    letterSpacing: 0.5,
  },

  feeNotice: {
    background: "rgba(200,255,62,0.08)",
    border: "1px solid rgba(200,255,62,0.25)",
    borderRadius: 10,
    padding: "10px 14px",
    fontSize: 12,
    color: "#7dd3fc",
    marginBottom: 16,
    lineHeight: 1.5,
  },

  // clickable policy link — plain text, no blue link color
  policyLink: {
    fontSize: 12.5,
    fontWeight: 700,
    color: "#b4acd0",
    textDecoration: "underline",
    textDecorationColor: "rgba(148,163,184,0.4)",
    textAlign: "center",
    cursor: "pointer",
    marginBottom: 16,
  },

  // policy modal
  modalOverlay: {
    position: "fixed",
    inset: 0,
    background: "rgba(0,0,0,0.6)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    padding: 20,
    zIndex: 1000,
  },
  modalCard: {
    background: "#161126",
    border: "1px solid rgba(255,255,255,0.08)",
    borderRadius: 16,
    padding: "20px 20px 18px",
    maxWidth: 420,
    width: "100%",
    maxHeight: "80vh",
    overflowY: "auto",
  },
  modalHeader: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 14,
  },
  modalTitle: {
    fontSize: 15,
    fontWeight: 800,
    color: "#e9e5f6",
  },
  modalClose: {
    fontSize: 14,
    color: "#9189b5",
    cursor: "pointer",
    padding: "2px 6px",
  },
  modalList: {
    margin: 0,
    paddingLeft: 18,
    fontSize: 13,
    color: "#d9d4ec",
    lineHeight: 1.8,
  },
  modalCloseBtn: {
    width: "100%",
    marginTop: 16,
    padding: 12,
    borderRadius: 10,
    border: "1px solid rgba(255,255,255,0.09)",
    background: "rgba(255,255,255,0.04)",
    color: "#e9e5f6",
    fontWeight: 700,
    fontSize: 13,
    cursor: "pointer",
  },

  // blocked (non-withdrawal day) card
  blockedCard: {
    background: "rgba(255,255,255,0.03)",
    border: "1px solid rgba(255,255,255,0.07)",
    borderRadius: 14,
    padding: "28px 20px",
    textAlign: "center",
    marginBottom: 16,
  },
  blockedIcon: { fontSize: 40, marginBottom: 12 },
  blockedTitle: { fontSize: 17, fontWeight: 800, color: "#e9e5f6", marginBottom: 10 },
  blockedSub: { fontSize: 13, color: "#b4acd0", lineHeight: 1.6, margin: 0 },

  // fee breakdown (step 2)
  feeBreakdown: {
    background: "rgba(22,17,38,0.9)",
    border: "1px solid rgba(255,255,255,0.07)",
    borderRadius: 12,
    padding: "10px 14px 4px",
    marginBottom: 14,
  },
  feeRow: {
    display: "flex",
    justifyContent: "space-between",
    padding: "7px 0",
  },
  feeRowFinal: {
    borderTop: "1px solid rgba(255,255,255,0.07)",
    marginTop: 2,
  },
  feeLabel: { fontSize: 12.5, color: "#b4acd0" },
  feeValue: { fontSize: 13, fontWeight: 700, color: "#e9e5f6" },

  // amount quick picks
  quickRow: {
    display: "flex",
    gap: 8,
    marginBottom: 14,
  },
  quickChip: {
    flex: 1,
    padding: "8px 0",
    borderRadius: 8,
    textAlign: "center",
    fontSize: 12,
    fontWeight: 700,
    cursor: "pointer",
    transition: "0.15s",
  },
  hint: {
    fontSize: 11,
    color: "#7a6fa3",
    marginBottom: 18,
    lineHeight: 1.5,
    margin: "0 0 16px",
  },

  // network buttons
  networkRow: {
    display: "flex",
    gap: 10,
    marginBottom: 16,
  },
  networkBtn: {
    flex: 1,
    padding: "10px 0",
    borderRadius: 10,
    textAlign: "center",
    cursor: "pointer",
    fontSize: 13,
    transition: "0.15s",
  },

  // confirm card
  confirmCard: {
    background: "rgba(22,17,38,0.9)",
    border: "1px solid rgba(255,255,255,0.07)",
    borderRadius: 14,
    padding: "4px 16px 8px",
    marginBottom: 14,
  },
  confirmDivider: {
    height: 1,
    background: "rgba(255,255,255,0.07)",
    margin: "4px 0",
  },

  verifiedBadge: {
    background: "rgba(34,197,94,0.1)",
    border: "1px solid rgba(34,197,94,0.3)",
    borderRadius: 10,
    padding: "10px 14px",
    fontSize: 12,
    color: "#4ade80",
    marginBottom: 16,
    lineHeight: 1.5,
  },
  warnBadge: {
    background: "rgba(239,68,68,0.08)",
    border: "1px solid rgba(239,68,68,0.3)",
    borderRadius: 10,
    padding: "10px 14px",
    fontSize: 12,
    color: "#f87171",
    marginBottom: 16,
    lineHeight: 1.5,
  },

  // buttons
  primaryBtn: {
    width: "100%",
    padding: 14,
    borderRadius: 12,
    border: "none",
    background: "linear-gradient(135deg,#c8ff3e,#8fe600)",
    color: "#000",
    fontWeight: 900,
    cursor: "pointer",
    fontSize: 15,
    marginBottom: 10,
    transition: "0.15s",
  },
  ghostBtn: {
    padding: "12px 16px",
    borderRadius: 10,
    background: "rgba(255,255,255,0.04)",
    color: "#b4acd0",
    border: "1px solid rgba(255,255,255,0.07)",
    cursor: "pointer",
    fontSize: 13,
    fontWeight: 600,
    marginBottom: 0,
    width: "100%",
  },
  navRow: {
    display: "flex",
    gap: 10,
    marginTop: 4,
    marginBottom: 10,
  },

  // success screen
  successCard: {
    marginTop: 40,
    textAlign: "center",
    padding: "0 10px",
  },
  successIcon: { fontSize: 52, marginBottom: 16 },
  successTitle: { fontSize: 22, fontWeight: 900, marginBottom: 10 },
  successSub: {
    fontSize: 14,
    color: "#b4acd0",
    lineHeight: 1.6,
    marginBottom: 24,
  },
  successMeta: {
    display: "flex",
    justifyContent: "space-between",
    padding: "10px 16px",
    background: "rgba(255,255,255,0.03)",
    borderRadius: 10,
    marginBottom: 8,
  },
  metaLabel: { fontSize: 12, color: "#7a6fa3" },
  metaValue: { fontSize: 13, fontWeight: 700, color: "#e9e5f6" },

  label: {
    display: "block",
    fontSize: 12,
    color: "#9189b5",
    fontWeight: 600,
    marginBottom: 7,
    textTransform: "uppercase",
    letterSpacing: 0.5,
  },
  input: {
    width: "100%",
    padding: "13px 14px",
    marginBottom: 16,
    borderRadius: 12,
    border: "1px solid rgba(255,255,255,0.09)",
    background: "rgba(10,8,20,0.8)",
    color: "white",
    fontSize: 15,
    boxSizing: "border-box",
    outline: "none",
  },

  // footer — plain text, no blue/link color
  footer: {
    marginTop: 28,
    textAlign: "center",
    fontSize: 11,
    color: "#9189b5",
    lineHeight: 1.7,
  },
};
