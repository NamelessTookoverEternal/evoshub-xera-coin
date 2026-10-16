import { useEffect, useState, useRef } from "react";
import { asset } from "../lib/basePath";

import { smartFetch } from "../config";

const NETWORK_CONFIG = {
  MTN: {
    label: "MTN", logo: asset("images/mtn.png"), color: "#FFC107",
    bg: "linear-gradient(135deg, rgba(255,193,7,0.18), rgba(255,193,7,0.06))",
    border: "rgba(255,193,7,0.4)", shadow: "0 4px 20px rgba(245,158,11,0.2)",
    tag: "Most Popular", tagColor: "#f59e0b",
  },
  Telecel: {
    label: "Telecel (Vodafone)", logo: asset("images/telecel.png"), color: "#ef4444",
    bg: "linear-gradient(135deg, rgba(239,68,68,0.18), rgba(239,68,68,0.06))",
    border: "rgba(239,68,68,0.4)", shadow: "0 4px 20px rgba(239,68,68,0.2)",
    tag: "Reliable", tagColor: "#ef4444",
  },
  AirtelTigo: {
    label: "AirtelTigo", logo: asset("images/airteltigo.png"), color: "#8b5cf6",
    bg: "linear-gradient(135deg, rgba(139,92,246,0.18), rgba(139,92,246,0.06))",
    border: "rgba(139,92,246,0.4)", shadow: "0 4px 20px rgba(139,92,246,0.2)",
    tag: "Affordable", tagColor: "#8b5cf6",
  },
};

// Checkers tile — sits alongside the networks in the same landing grid.
const CHECKERS_TILE = {
  label: "Result Checkers", emoji: "🎓", color: "#a78bfa",
  bg: "linear-gradient(135deg, rgba(167,139,250,0.18), rgba(167,139,250,0.06))",
  border: "rgba(167,139,250,0.4)",
  desc: "WAEC & BECE",
};

const bundleAccents = [
  { border: "rgba(34,197,94,0.3)", price: "#22c55e" },
  { border: "rgba(200,255,62,0.3)", price: "#c8ff3e" },
  { border: "rgba(167,139,250,0.3)", price: "#a78bfa" },
  { border: "rgba(245,158,11,0.3)", price: "#f59e0b" },
  { border: "rgba(20,184,166,0.3)", price: "#14b8a6" },
  { border: "rgba(239,68,68,0.3)", price: "#ef4444" },
];

// =========================
// CHECKER (WAEC/BECE) CONFIG
// =========================
const CHECKER_CONFIG = {
  WAEC: {
    label: "WAEC Checker", emoji: "🎓", color: "#a78bfa",
    bg: "linear-gradient(135deg, rgba(167,139,250,0.18), rgba(167,139,250,0.06))",
    border: "rgba(167,139,250,0.4)",
    desc: "Result checker card for WASSCE results",
  },
  BECE: {
    label: "BECE Checker", emoji: "📘", color: "#c8ff3e",
    bg: "linear-gradient(135deg, rgba(200,255,62,0.18), rgba(200,255,62,0.06))",
    border: "rgba(200,255,62,0.4)",
    desc: "Result checker card for BECE results",
  },
};

const round2 = (n) => Math.round((Number(n) + Number.EPSILON) * 100) / 100;

// =========================
// ORDER TRACKING STATUS CONFIG
// Mirrors ETATrack.jsx status config so tracking behaves identically,
// just rendered inline inside the store instead of on a separate page.
// =========================
const STATUS_CONFIG = {
  pending_payment: {
    label: "Awaiting Payment",
    color: "#f59e0b",
    bg: "rgba(245,158,11,0.1)",
    border: "rgba(245,158,11,0.3)",
    eta: "Complete your payment to proceed.",
    icon: "⏳",
  },
  paid: {
    label: "Payment Confirmed",
    color: "#c8ff3e",
    bg: "rgba(200,255,62,0.1)",
    border: "rgba(200,255,62,0.3)",
    eta: "Your order is queued for delivery. Usually starts within 1-2 minutes.",
    icon: "✅",
  },
  processing: {
    label: "Processing",
    color: "#a78bfa",
    bg: "rgba(167,139,250,0.1)",
    border: "rgba(167,139,250,0.3)",
    eta: "Data bundle is being delivered. Usually arrives within 5-30 minutes.",
    icon: "📡",
  },
  successful: {
    label: "Delivered",
    color: "#22c55e",
    bg: "rgba(34,197,94,0.1)",
    border: "rgba(34,197,94,0.3)",
    eta: "Your data bundle has been delivered successfully.",
    icon: "🎉",
  },
  failed: {
    label: "Failed",
    color: "#ef4444",
    bg: "rgba(239,68,68,0.1)",
    border: "rgba(239,68,68,0.3)",
    eta: "Delivery attempt failed. The system will automatically retry delivery within 24 hours. No action needed.",
    icon: "❌",
  },
};

function formatDate(dateStr) {
  if (!dateStr) return "—";
  const d = new Date(dateStr);
  return d.toLocaleString("en-GH", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// =========================
// SESSION HELPERS
// Save and restore store state so ETATrack "back" returns to exact position
// =========================
const SESSION_KEY = "evos_store_state";

function saveStoreSession(agentId, step, network) {
  try {
    sessionStorage.setItem(SESSION_KEY, JSON.stringify({ agentId, step, network }));
    // Always keep agentId accessible for ETATrack
    sessionStorage.setItem("storeAgentId", agentId);
  } catch (_) {}
}

function loadStoreSession(agentId) {
  try {
    const raw = sessionStorage.getItem(SESSION_KEY);
    if (!raw) return null;
    const saved = JSON.parse(raw);
    // Only restore if it's for the same agent
    if (String(saved.agentId) === String(agentId)) return saved;
    return null;
  } catch (_) {
    return null;
  }
}

function clearStoreSession() {
  try {
    sessionStorage.removeItem(SESSION_KEY);
    sessionStorage.removeItem("storeAgentId");
  } catch (_) {}
}

// =========================
// CONFIRMATION MODAL
// =========================
function ConfirmModal({ selected, networkLabel, networkCfg, onClose, onConfirm, processing }) {
  const [phone, setPhone] = useState("");
  const [accepted, setAccepted] = useState(false);
  const [verifyInfo, setVerifyInfo] = useState(null);
  const [verifying, setVerifying] = useState(false);
  const [verifyTimedOut, setVerifyTimedOut] = useState(false); // watchdog: unblocks Pay if check is slow
  const [showVerifyResult, setShowVerifyResult] = useState(false); // popup stays up until the user proceeds or cancels
  const resultTimerRef = useRef(null);
  const canSubmit = phone.trim().length >= 9 && accepted && !processing;
  const network = selected.network;

  // Informational-only MTN pre-check — never blocks the purchase, just warns.
  // Fired once, on Pay (see handlePayClick) rather than as-you-type, so the
  // scarce 2-checks/minute vendor quota is spent on real purchase attempts
  // instead of being burned by keystrokes. Bounded to 12s (backend caps its
  // own DataMart call at ~9s worst case, see main.py) so this can never
  // hang indefinitely.
  const checkNumber = async (num) => {
    if (network !== "MTN" || num.trim().length < 9) return null;
    setVerifying(true);
    setVerifyTimedOut(false);
    if (resultTimerRef.current) clearTimeout(resultTimerRef.current);
    setShowVerifyResult(false);
    try {
      const controller = new AbortController();
      const t = setTimeout(() => controller.abort(), 12000);
      const res = await smartFetch(`/verify-number`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phoneNumber: num.trim(), network }),
        signal: controller.signal,
      });
      clearTimeout(t);
      const data = await res.json();
      setVerifyInfo(data);
      // Keep the result up until the user acts on it (Proceed/Cancel) —
      // this is no longer a passive toast, it's the gate before payment.
      setShowVerifyResult(true);
      return data;
    } catch {
      setVerifyInfo(null);
      setShowVerifyResult(true);
      return null;
    } finally {
      setVerifying(false);
    }
  };

  // Watchdog: pure safety net in case the request hangs outside fetch's own
  // control. Set comfortably past the 12s abort above so it never fires
  // before the real check has a chance to resolve — firing early would
  // flash the popup away and briefly re-enable Pay mid-check.
  useEffect(() => {
    if (!verifying) return;
    const t = setTimeout(() => setVerifyTimedOut(true), 13000);
    return () => clearTimeout(t);
  }, [verifying]);

  // True only while the Pay button should stay hidden behind the popup.
  const checkingBlocking = verifying && !verifyTimedOut;

  // Pay tap: for MTN, run the check and stop — the popup shows the outcome
  // with its own Proceed button so the customer always sees the status
  // before payment actually fires. Other networks skip straight through
  // since DataMart's check only exists for MTN.
  const handlePayClick = async () => {
    if (network === "MTN") {
      await checkNumber(phone);
      return;
    }
    onConfirm(phone.trim());
  };

  const handleProceed = () => {
    setShowVerifyResult(false);
    onConfirm(phone.trim());
  };

  return (
    <div style={modal.overlay}>
      <div style={modal.box}>
        <div style={modal.header}>
          <span style={modal.headerLabel}>✅ Complete Purchase</span>
          <button style={modal.closeBtn} onClick={onClose}>✕</button>
        </div>

        <div style={{
          ...modal.summary,
          background: networkCfg?.bg || "rgba(255,255,255,0.04)",
          border: `1px solid ${networkCfg?.border || "rgba(255,255,255,0.08)"}`,
        }}>
          <div style={modal.summaryHeader}>
            <span style={{ fontSize: 18 }}>{networkCfg?.emoji}</span>
            <span style={{ fontWeight: 900, fontSize: 14, color: networkCfg?.color }}>Order Summary</span>
          </div>
          <div style={modal.summaryRow}>
            <span style={modal.summaryLabel}>Network</span>
            <span style={{ ...modal.summaryValue, color: networkCfg?.color, fontWeight: 800 }}>{networkLabel}</span>
          </div>
          <div style={modal.summaryRow}>
            <span style={modal.summaryLabel}>Bundle</span>
            <span style={modal.summaryValue}>{selected.bundle}</span>
          </div>
          <div style={{ ...modal.summaryRow, borderBottom: "none" }}>
            <span style={modal.summaryLabel}>Amount</span>
            <span style={{ ...modal.summaryValue, color: "#22c55e", fontSize: 20, fontWeight: 900 }}>
              GH₵ {Number(selected.final_price).toFixed(2)}
            </span>
          </div>
        </div>

        <label style={modal.label}>📱 Recipient Phone Number</label>
        <input
          type="tel"
          placeholder="e.g. 0244000000"
          value={phone}
          onChange={(e) => {
            setPhone(e.target.value);
            setVerifyInfo(null);
            setVerifyTimedOut(false);
            setShowVerifyResult(false);
          }}
          style={modal.input}
          disabled={processing}
        />

        <label style={modal.checkRow}>
          <input
            type="checkbox"
            checked={accepted}
            onChange={(e) => setAccepted(e.target.checked)}
            disabled={processing}
            style={{ marginRight: 8, accentColor: "#c8ff3e", width: 15, height: 15, flexShrink: 0, marginTop: 2 }}
          />
          <span style={modal.checkText}>
            I confirm this phone number is correct.{" "}
            <strong style={{ color: "#f87171" }}>Wrong numbers will NOT be refunded.</strong>
          </span>
        </label>

        {checkingBlocking ? (
          <button disabled style={{ ...modal.buyBtn, opacity: 0.4, cursor: "not-allowed", background: "linear-gradient(135deg, #3d3460, #241c3d)" }}>
            🔎 Verifying number...
          </button>
        ) : showVerifyResult ? (
          <button disabled style={{ ...modal.buyBtn, opacity: 0.4, cursor: "not-allowed", background: "linear-gradient(135deg, #3d3460, #241c3d)" }}>
            See popup to continue
          </button>
        ) : (
          <button
            onClick={handlePayClick}
            disabled={!canSubmit}
            style={{ ...modal.buyBtn, opacity: canSubmit ? 1 : 0.45, cursor: canSubmit ? "pointer" : "not-allowed" }}
          >
            {processing ? "⏳ Processing..." : `💳 Pay GH₵ ${Number(selected.final_price).toFixed(2)} via Paystack`}
          </button>
        )}
        <p style={modal.secureNote}>🔒 Secured & encrypted by Paystack</p>
      </div>

      {/* VERIFY NUMBER POPUP */}
      {(checkingBlocking || showVerifyResult) && (
        <div style={modal.verifyOverlay}>
          <div style={modal.verifyPopup}>
            <style>{`@keyframes evos-spin { to { transform: rotate(360deg); } }`}</style>
            {checkingBlocking ? (
              <>
                <div style={modal.verifySpinner} />
                <p style={modal.verifyPopupText}>Checking number...</p>
                <p style={modal.verifyPopupSub}>Confirming this MTN number is active</p>
              </>
            ) : verifyInfo?.checked && verifyInfo?.recommendation === "activate_first" ? (
              <>
                <p style={modal.verifyPopupText}>⚠️ On hold — activation needed</p>
                <p style={modal.verifyPopupSub}>{verifyInfo.message}</p>
              </>
            ) : verifyInfo?.checked && verifyInfo?.recommendation === "sell_any" ? (
              <>
                <p style={modal.verifyPopupText}>✅ Number verified</p>
                <p style={modal.verifyPopupSub}>Active on MTN — any bundle size will deliver instantly</p>
              </>
            ) : (
              <>
                <p style={modal.verifyPopupText}>ℹ️ Couldn't confirm status</p>
                <p style={modal.verifyPopupSub}>{verifyInfo?.message || "You can still continue with your order"}</p>
              </>
            )}

            {showVerifyResult && !checkingBlocking && (
              <div style={modal.verifyPopupActions}>
                <button onClick={() => setShowVerifyResult(false)} style={modal.verifyPopupCancelBtn}>
                  Change number
                </button>
                <button
                  onClick={handleProceed}
                  disabled={processing}
                  style={{ ...modal.verifyPopupProceedBtn, opacity: processing ? 0.6 : 1 }}
                >
                  {processing
                    ? "⏳ Processing..."
                    : verifyInfo?.checked && verifyInfo?.recommendation === "activate_first"
                    ? "Proceed anyway"
                    : "Proceed to payment"}
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// =========================
// CHECKER CONFIRMATION MODAL
// Mirrors ConfirmModal but for WAEC/BECE result checkers — phone + quantity,
// no MTN-verify step since that check is data-bundle only.
// =========================
function CheckerConfirmModal({ selected, checkerCfg, onClose, onConfirm, processing }) {
  const [phone, setPhone] = useState("");
  const [quantity, setQuantity] = useState(1);
  const [accepted, setAccepted] = useState(false);
  const canSubmit = phone.trim().length >= 9 && accepted && quantity >= 1 && !processing;
  const total = round2(Number(selected.final_price) * quantity);

  return (
    <div style={modal.overlay}>
      <div style={modal.box}>
        <div style={modal.header}>
          <span style={modal.headerLabel}>✅ Complete Purchase</span>
          <button style={modal.closeBtn} onClick={onClose}>✕</button>
        </div>

        <div style={{
          ...modal.summary,
          background: checkerCfg?.bg || "rgba(255,255,255,0.04)",
          border: `1px solid ${checkerCfg?.border || "rgba(255,255,255,0.08)"}`,
        }}>
          <div style={modal.summaryHeader}>
            <span style={{ fontSize: 18 }}>{checkerCfg?.emoji}</span>
            <span style={{ fontWeight: 900, fontSize: 14, color: checkerCfg?.color }}>Order Summary</span>
          </div>
          <div style={modal.summaryRow}>
            <span style={modal.summaryLabel}>Checker</span>
            <span style={{ ...modal.summaryValue, color: checkerCfg?.color, fontWeight: 800 }}>{checkerCfg?.label}</span>
          </div>
          <div style={modal.summaryRow}>
            <span style={modal.summaryLabel}>Unit Price</span>
            <span style={modal.summaryValue}>GH₵ {Number(selected.final_price).toFixed(2)}</span>
          </div>
          <div style={{ ...modal.summaryRow, borderBottom: "none" }}>
            <span style={modal.summaryLabel}>Amount</span>
            <span style={{ ...modal.summaryValue, color: "#22c55e", fontSize: 20, fontWeight: 900 }}>
              GH₵ {total.toFixed(2)}
            </span>
          </div>
        </div>

        <label style={modal.label}>📱 Recipient Phone Number</label>
        <input
          type="tel"
          placeholder="e.g. 0244000000"
          value={phone}
          onChange={(e) => setPhone(e.target.value)}
          style={modal.input}
          disabled={processing}
        />

        <label style={modal.label}>🔢 Quantity</label>
        <input
          type="number"
          min={1}
          max={20}
          value={quantity}
          onChange={(e) => {
            const v = parseInt(e.target.value, 10);
            setQuantity(Number.isFinite(v) && v > 0 ? Math.min(v, 20) : 1);
          }}
          style={modal.input}
          disabled={processing}
        />

        <label style={modal.checkRow}>
          <input
            type="checkbox"
            checked={accepted}
            onChange={(e) => setAccepted(e.target.checked)}
            disabled={processing}
            style={{ marginRight: 8, accentColor: "#c8ff3e", width: 15, height: 15, flexShrink: 0, marginTop: 2 }}
          />
          <span style={modal.checkText}>
            I confirm this phone number is correct.{" "}
            <strong style={{ color: "#f87171" }}>Wrong numbers will NOT be refunded.</strong>
          </span>
        </label>

        <button
          onClick={() => onConfirm(phone.trim(), quantity)}
          disabled={!canSubmit}
          style={{ ...modal.buyBtn, opacity: canSubmit ? 1 : 0.45, cursor: canSubmit ? "pointer" : "not-allowed" }}
        >
          {processing ? "⏳ Processing..." : `💳 Pay GH₵ ${total.toFixed(2)} via Paystack`}
        </button>
        <p style={modal.secureNote}>🔒 Secured & encrypted by Paystack</p>
      </div>
    </div>
  );
}

// =========================
// TRACK ORDER MODAL
// Inline replacement for the old "eta-track" page redirect.
// Customer never leaves /store/{agentId} — they stay inside the
// reseller's own storefront the whole time, no EvosData branding leak.
// =========================
function TrackModal({ onClose }) {
  const [phone, setPhone] = useState("");
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [searched, setSearched] = useState(false);

  const search = async () => {
    setError("");
    setOrders([]);
    setSearched(false);

    const cleaned = phone.trim();
    if (!cleaned || cleaned.length < 9) {
      setError("Enter a valid phone number");
      return;
    }

    setLoading(true);
    try {
      const res = await smartFetch(`/orders/track?phone=${encodeURIComponent(cleaned)}`);
      const data = await res.json();

      if (data.orders && data.orders.length > 0) {
        setOrders(data.orders);
      } else {
        setError("No orders found for this number.");
      }
      setSearched(true);
    } catch (e) {
      setError("Network error. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={modal.overlay}>
      <div style={modal.box}>
        <div style={modal.header}>
          <span style={modal.headerLabel}>📦 Track Your Order</span>
          <button style={modal.closeBtn} onClick={onClose}>✕</button>
        </div>

        <label style={modal.label}>📱 Phone Number Used During Purchase</label>
        <div style={trackStyles.searchRow}>
          <input
            type="tel"
            placeholder="e.g. 0244000000"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && search()}
            style={trackStyles.searchInput}
          />
          <button
            onClick={search}
            disabled={loading}
            style={{ ...trackStyles.searchBtn, opacity: loading ? 0.6 : 1 }}
          >
            {loading ? "..." : "Track"}
          </button>
        </div>

        {error && <div style={trackStyles.errorBox}>{error}</div>}

        <div style={trackStyles.resultsWrap}>
          {orders.map((order, i) => {
            const status = order.status || "processing";
            const cfg = STATUS_CONFIG[status] || STATUS_CONFIG.processing;

            return (
              <div key={i} style={trackStyles.card}>

                {/* STATUS BADGE */}
                <div style={{
                  ...trackStyles.statusBadge,
                  background: cfg.bg,
                  border: `1px solid ${cfg.border}`,
                  color: cfg.color,
                }}>
                  <span style={trackStyles.statusIcon}>{cfg.icon}</span>
                  <span style={trackStyles.statusLabel}>{cfg.label}</span>
                </div>

                {/* ORDER DETAILS */}
                <div style={trackStyles.detailGrid}>
                  <div style={trackStyles.detailRow}>
                    <span style={trackStyles.detailLabel}>Network</span>
                    <span style={trackStyles.detailVal}>{order.network}</span>
                  </div>
                  <div style={trackStyles.detailRow}>
                    <span style={trackStyles.detailLabel}>Bundle</span>
                    <span style={trackStyles.detailVal}>{order.bundle}</span>
                  </div>
                  <div style={trackStyles.detailRow}>
                    <span style={trackStyles.detailLabel}>Amount Paid</span>
                    <span style={{ ...trackStyles.detailVal, color: "#c8ff3e", fontWeight: 800 }}>
                      GH&#8373; {Number(order.price || 0).toFixed(2)}
                    </span>
                  </div>
                  <div style={trackStyles.detailRow}>
                    <span style={trackStyles.detailLabel}>Phone</span>
                    <span style={trackStyles.detailVal}>{order.phone_number}</span>
                  </div>
                  <div style={trackStyles.detailRow}>
                    <span style={trackStyles.detailLabel}>Time Placed</span>
                    <span style={trackStyles.detailVal}>{formatDate(order.created_at)}</span>
                  </div>
                  <div style={{ ...trackStyles.detailRow, borderBottom: "none" }}>
                    <span style={trackStyles.detailLabel}>Reference</span>
                    <span style={{ ...trackStyles.detailVal, fontSize: 11, color: "#9189b5" }}>
                      {order.evosdata_ref || order.paystack_ref || "—"}
                    </span>
                  </div>
                </div>

                {/* ETA */}
                <div style={{
                  ...trackStyles.etaBox,
                  background: cfg.bg,
                  border: `1px solid ${cfg.border}`,
                }}>
                  <p style={{ ...trackStyles.etaText, color: cfg.color }}>
                    {cfg.eta}
                  </p>
                </div>

              </div>
            );
          })}
        </div>

        {searched && orders.length === 0 && !error && (
          <p style={trackStyles.emptyNote}>No orders found for this number.</p>
        )}
      </div>
    </div>
  );
}

// =========================
// MAIN STORE PAGE
// =========================
export default function StorePage({ setPage }) {
  const agentId = window.location.pathname.split("/store/")[1]?.split("/")[0];

  const [loading, setLoading] = useState(true);
  const [store, setStore] = useState(null);
  const [step, setStep] = useState(0);
  const [network, setNetwork] = useState("");
  const [selected, setSelected] = useState(null);
  const [checkerSelected, setCheckerSelected] = useState(null);
  const [processing, setProcessing] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);
  const [trackOpen, setTrackOpen] = useState(false);

  // On mount: restore previous step/network from session if available
  useEffect(() => {
    if (!agentId) { setLoading(false); window.__evosReady = true; return; }

    const saved = loadStoreSession(agentId);
    if (saved) {
      if (saved.step) setStep(saved.step);
      if (saved.network) setNetwork(saved.network);
    }

    const loadStore = async () => {
      try {
        setLoading(true);
        const res = await smartFetch(`/store/${agentId}`);
        const data = await res.json();
        if (!res.ok || data.status === "error") { setStore(null); }
        else { setStore(data); }
      } catch (err) {
        console.log("Store error:", err);
        setStore(null);
      } finally {
        setLoading(false);
        window.__evosReady = true; // lets the launch splash lift
      }
    };
    loadStore();
  }, [agentId]);

  // Save session whenever step or network changes
  useEffect(() => {
    if (agentId) {
      saveStoreSession(agentId, step, network);
    }
  }, [agentId, step, network]);

  const goToStep = (newStep, newNetwork = network) => {
    setStep(newStep);
    setNetwork(newNetwork);
  };

  const handleTrackOrder = () => {
    // Previously: setPage("eta-track") which navigated away to EvosData's
    // own tracking page. Now opens an inline modal so the customer never
    // leaves the reseller's storefront URL / branding.
    setTrackOpen(true);
  };

  const placeOrder = async (phone) => {
    if (!selected) return;
    setProcessing(true);
    try {
      const res = await smartFetch(`/store/order`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          agent_id: Number(agentId),
          network: selected.network,
          bundle: selected.bundle,
          phone_number: phone,
        }),
      });
      const data = await res.json();
      if (data.status === "created" && data.payment_url) {
        // Clear session on successful payment redirect so they start fresh on return
        clearStoreSession();
        window.location.href = data.payment_url;
        return;
      }
      alert(data.message || "Failed to create order");
    } catch (err) {
      alert("Network error");
    } finally {
      setProcessing(false);
    }
  };

  const placeCheckerOrder = async (phone, quantity) => {
    if (!checkerSelected) return;
    setProcessing(true);
    try {
      const res = await smartFetch(`/store/order/checker`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          agent_id: Number(agentId),
          checker_type: checkerSelected.checker_type,
          phone_number: phone,
          quantity: quantity,
        }),
      });
      const data = await res.json();
      if (data.status === "created" && data.payment_url) {
        clearStoreSession();
        window.location.href = data.payment_url;
        return;
      }
      alert(data.message || "Failed to create order");
    } catch (err) {
      alert("Network error");
    } finally {
      setProcessing(false);
    }
  };

  if (loading) return (
    <div style={styles.centerWrap}>
      <div style={{ fontSize: 40, marginBottom: 12 }}>⏳</div>
      <p style={{ fontSize: 15, color: "#9189b5", fontWeight: 700 }}>Loading store...</p>
    </div>
  );

  if (!store) return (
    <div style={styles.centerWrap}>
      <div style={{ fontSize: 48, marginBottom: 12 }}>😕</div>
      <h2 style={{ fontSize: 22, fontWeight: 900, color: "#f3f0fb", marginBottom: 8 }}>Store Not Found</h2>
      <p style={{ fontSize: 14, color: "#9189b5", fontWeight: 600 }}>This store link may be invalid or inactive.</p>
    </div>
  );

  const availableNetworks = [...new Set((store.prices || []).map((p) => p.network))];

  const bundles = (store.prices || [])
    .filter((p) => p.network === network)
    .sort((a, b) => Number(a.final_price) - Number(b.final_price));

  const checkerProducts = store.checkers || [];

  const cfg = NETWORK_CONFIG[network] || {};
  const networkLabel = cfg.label || network;

  return (
    <div style={styles.container}>

      {/* HEADER */}
      <div style={styles.header}>
        <img
          src={store.logo || asset("evosdata.png")}
          alt={`${store.agent_name} logo`}
          style={styles.storeLogo}
          onError={(e) => { e.target.src = asset("evosdata.png"); }}
        />
        <div style={styles.headerBadge}>🏪 Agent Store</div>
        <h1 style={styles.title}>{store.agent_name}'s Store</h1>
        <p style={styles.sub}>
          Fast Data Purchase · Powered by <span style={{ color: "#c8ff3e", fontWeight: 900 }}>EVOS HUB</span>
        </p>
      </div>

      {/* PROGRESS — only shown once inside the bundle-picking / pay flow */}
      {step === 2 && (
        <div style={styles.progressWrap}>
          {["Bundle", "Pay"].map((label, i) => {
            const active = i === 0; // this screen is always "Bundle"; Pay happens via modal
            return (
              <div key={i} style={styles.progressItem}>
                <div style={{
                  ...styles.progressDot,
                  background: active ? "#c8ff3e" : "rgba(255,255,255,0.1)",
                  border: active ? "2px solid #c8ff3e" : "2px solid rgba(255,255,255,0.1)",
                  color: active ? "white" : "#7a6fa3",
                }}>
                  {i + 1}
                </div>
                <span style={{
                  ...styles.progressLabel,
                  color: active ? "#c8ff3e" : "#7a6fa3",
                }}>{label}</span>
              </div>
            );
          })}
          <div style={styles.progressLine} />
        </div>
      )}

      <div style={styles.wrapper}>

        {/* ============ STEP 0 — LANDING: NETWORKS + CHECKERS GRID ============ */}
        {step === 0 && (
          <div style={styles.box}>
            <p style={styles.stepLabel}>What would you like to buy?</p>

            <div style={styles.landingGrid}>
              {availableNetworks.map((netKey) => {
                const c = NETWORK_CONFIG[netKey] || {
                  label: netKey, logo: null, color: "#9189b5",
                  bg: "rgba(255,255,255,0.04)", border: "rgba(255,255,255,0.1)",
                };
                return (
                  <div
                    key={netKey}
                    style={{
                      ...styles.landingTile,
                      background: c.bg,
                      border: `1px solid ${c.border}`,
                    }}
                    onClick={() => goToStep(2, netKey)}
                  >
                    {c.tag && (
                      <div style={{
                        ...styles.landingTag,
                        background: c.tagColor + "22",
                        color: c.tagColor,
                        border: `1px solid ${c.tagColor}44`,
                      }}>
                        {c.tag}
                      </div>
                    )}
                    <div style={styles.landingLogoWrap}>
                      {c.logo ? (
                        <img src={c.logo} alt={c.label} style={styles.landingLogo} />
                      ) : (
                        <div style={{ fontSize: 34 }}>📡</div>
                      )}
                    </div>
                    <div style={{ ...styles.landingName, color: c.color }}>{c.label}</div>
                    <div style={{ ...styles.bundleCta, color: c.color }}>Select →</div>
                  </div>
                );
              })}

              {/* CHECKERS TILE — same grid, same size */}
              <div
                style={{
                  ...styles.landingTile,
                  background: CHECKERS_TILE.bg,
                  border: `1px solid ${CHECKERS_TILE.border}`,
                }}
                onClick={() => setStep("checker")}
              >
                <div style={styles.landingLogoWrap}>
                  <div style={{ fontSize: 34 }}>{CHECKERS_TILE.emoji}</div>
                </div>
                <div style={{ ...styles.landingName, color: CHECKERS_TILE.color }}>{CHECKERS_TILE.label}</div>
                <div style={styles.landingDesc}>{CHECKERS_TILE.desc}</div>
                <div style={{ ...styles.bundleCta, color: CHECKERS_TILE.color }}>Select →</div>
              </div>
            </div>

            <div style={styles.infoRow}>
              <span style={styles.infoChip}>🔒 Paystack Secured</span>
              <span style={styles.infoChip}>⚡ Instant Delivery</span>
            </div>

            <button style={styles.trackBtn} onClick={handleTrackOrder}>
              📦 Track My Order
            </button>
          </div>
        )}

        {/* ============ STEP 2 — BUNDLES ============ */}
        {step === 2 && (
          <div style={styles.box}>
            <button style={styles.backBtn} onClick={() => goToStep(0, "")}>← Back</button>

            <p style={styles.stepLabel}>Pick a Bundle</p>

            <div style={{
              ...styles.networkPill,
              background: cfg.bg,
              border: `1px solid ${cfg.border}`,
              color: cfg.color,
            }}>
              {cfg.logo ? (
                <img src={cfg.logo} alt={networkLabel} style={styles.networkPillLogo} />
              ) : null}
              {networkLabel}
            </div>

            {bundles.length === 0 && (
              <div style={{ textAlign: "center", padding: "30px 0 10px" }}>
                <div style={{ fontSize: 36, marginBottom: 8 }}>📭</div>
                <p style={{ color: "#7a6fa3", fontSize: 14, margin: 0 }}>No bundles available.</p>
              </div>
            )}

            <div style={styles.bundleGrid}>
              {bundles.map((item, i) => {
                const accent = bundleAccents[i % bundleAccents.length];
                return (
                  <div
                    key={i}
                    style={{ ...styles.bundleCard, border: `1px solid ${accent.border}` }}
                    onClick={() => setSelected(item)}
                  >
                    <div style={styles.bundleSize}>{item.bundle}</div>
                    <div style={{ ...styles.bundlePrice, color: accent.price }}>
                      GH₵ {Number(item.final_price).toFixed(2)}
                    </div>
                    <div style={{ ...styles.bundleCta, color: accent.price }}>Select →</div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* ============ STEP "checker" — RESULT CHECKERS ============ */}
        {step === "checker" && (
          <div style={styles.box}>
            <button style={styles.backBtn} onClick={() => goToStep(0, "")}>← Back</button>

            <p style={styles.stepLabel}>Pick a Result Checker</p>

            {checkerProducts.length === 0 && (
              <div style={{ textAlign: "center", padding: "30px 0 10px" }}>
                <div style={{ fontSize: 36, marginBottom: 8 }}>📭</div>
                <p style={{ color: "#7a6fa3", fontSize: 14, margin: 0 }}>No checkers available.</p>
              </div>
            )}

            <div style={styles.checkerGrid}>
              {checkerProducts.map((item, i) => {
                const c = CHECKER_CONFIG[item.checker_type] || {
                  label: item.checker_type, emoji: "🎫", color: "#9189b5",
                  bg: "rgba(255,255,255,0.04)", border: "rgba(255,255,255,0.1)",
                };
                return (
                  <div
                    key={i}
                    style={{ ...styles.checkerCard, background: c.bg, border: `1px solid ${c.border}` }}
                    onClick={() => setCheckerSelected(item)}
                  >
                    <div style={styles.productTypeEmoji}>{c.emoji}</div>
                    <div style={{ ...styles.networkName, color: c.color }}>{c.label}</div>
                    <div style={{ ...styles.productTypeDesc, marginBottom: 2 }}>{c.desc}</div>
                    <div style={{ ...styles.bundlePrice, color: c.color }}>
                      GH₵ {Number(item.final_price).toFixed(2)}
                    </div>
                    <div style={{ ...styles.bundleCta, color: c.color }}>Select →</div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

      </div>

      {/* CONFIRM MODAL */}
      {selected && (
        <ConfirmModal
          selected={selected}
          networkLabel={networkLabel}
          networkCfg={cfg}
          processing={processing}
          onClose={() => { if (!processing) setSelected(null); }}
          onConfirm={placeOrder}
        />
      )}

      {/* CHECKER CONFIRM MODAL */}
      {checkerSelected && (
        <CheckerConfirmModal
          selected={checkerSelected}
          checkerCfg={CHECKER_CONFIG[checkerSelected.checker_type]}
          processing={processing}
          onClose={() => { if (!processing) setCheckerSelected(null); }}
          onConfirm={placeCheckerOrder}
        />
      )}

      {/* TRACK ORDER MODAL — replaces the old redirect to /eta-track */}
      {trackOpen && (
        <TrackModal onClose={() => setTrackOpen(false)} />
      )}

      {/* FLOATING SUPPORT */}
      <div style={styles.floatWrap}>
        {chatOpen && (
          <div style={styles.chatPopup}>
            <div style={styles.chatHeader}>
              <span style={{ fontWeight: 800, fontSize: 14, color: "#e5e7eb" }}>💬 EVOS Support</span>
              <button style={styles.chatClose} onClick={() => setChatOpen(false)}>✕</button>
            </div>
            <p style={styles.chatMsg}>Hi! How can we help you? Choose an option 👇</p>
            <div style={styles.chatOptions}>
              <button style={styles.chatOption}
                onClick={() => window.open("https://wa.me/233537314125", "_blank")}>
                💬 WhatsApp Chat
              </button>
              <button style={styles.chatOption}
                onClick={() => window.open("https://whatsapp.com/channel/0029VaTrnsZEgGfFXkIcjt1M", "_blank")}>
                👥 Community
              </button>
              <button style={styles.chatOption}
                onClick={() => window.location.href = "mailto:support@evosdata.xyz"}>
                📧 Email Support
              </button>
            </div>
          </div>
        )}
        <button style={styles.floatBtn} onClick={() => setChatOpen(!chatOpen)}>
          {chatOpen ? "✕" : "💬"}
        </button>
      </div>

    </div>
  );
}

const styles = {
  container: { padding: "28px 18px 80px", minHeight: "auto", fontFamily: "ui-sans-serif, system-ui, Arial", color: "#e5e7eb" },
  centerWrap: { display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", minHeight: "60vh", textAlign: "center", padding: 24, color: "#e5e7eb" },
  header: { textAlign: "center", marginBottom: 24 },
  storeLogo: {
    width: 72, height: 72, objectFit: "contain", borderRadius: 18,
    background: "rgba(22,17,38,0.9)", border: "1px solid rgba(255,255,255,0.08)",
    padding: 8, marginBottom: 10,
  },
  headerBadge: { display: "inline-block", padding: "5px 18px", borderRadius: 50, background: "rgba(200,255,62,0.15)", border: "1px solid rgba(200,255,62,0.3)", color: "#c8ff3e", fontSize: 12, fontWeight: 800, marginBottom: 10, letterSpacing: "0.5px" },
  title: { fontSize: "clamp(22px, 5vw, 30px)", fontWeight: 900, color: "#f3f0fb", margin: "0 0 6px" },
  sub: { fontSize: 13, color: "#9189b5", margin: 0, fontWeight: 600 },
  progressWrap: { display: "flex", justifyContent: "center", alignItems: "center", position: "relative", maxWidth: 340, margin: "0 auto 24px" },
  progressItem: { display: "flex", flexDirection: "column", alignItems: "center", gap: 6, flex: 1, position: "relative", zIndex: 1 },
  progressDot: { width: 34, height: 34, borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 13, fontWeight: 800, transition: "all 0.35s" },
  progressLabel: { fontSize: 11, fontWeight: 700, transition: "color 0.3s" },
  progressLine: { position: "absolute", top: 17, left: "16%", right: "16%", height: 2, background: "rgba(255,255,255,0.08)", zIndex: 0 },
  wrapper: { maxWidth: 480, margin: "0 auto" },
  box: { background: "rgba(22,17,38,0.9)", backdropFilter: "blur(20px)", WebkitBackdropFilter: "blur(20px)", padding: "24px 20px", borderRadius: 22, border: "1px solid rgba(255,255,255,0.07)", boxShadow: "0 25px 60px rgba(0,0,0,0.4)" },
  stepLabel: { fontSize: 12, color: "#c8ff3e", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.8px", margin: "0 0 18px" },
  landingGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(2, 1fr)",
    gap: 12,
    marginBottom: 20,
  },
  landingTile: {
    borderRadius: 18,
    padding: "16px 12px",
    cursor: "pointer",
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    textAlign: "center",
    position: "relative",
    aspectRatio: "1 / 1",
    transition: "transform 0.15s",
  },
  landingTag: {
    position: "absolute", top: 8, right: 8, fontSize: 9, fontWeight: 800,
    padding: "2px 7px", borderRadius: 50, letterSpacing: "0.4px", textTransform: "uppercase",
  },
  landingLogoWrap: {
    width: 52, height: 52, display: "flex", alignItems: "center", justifyContent: "center",
    borderRadius: "50%", background: "rgba(255,255,255,0.9)", marginBottom: 2,
    boxShadow: "0 2px 10px rgba(0,0,0,0.25)", flexShrink: 0,
  },
  landingLogo: { width: 34, height: 34, objectFit: "contain" },
  landingName: { fontWeight: 800, fontSize: 14, lineHeight: 1.2 },
  landingDesc: { fontSize: 10.5, color: "#9189b5", fontWeight: 600, marginTop: -4 },
  networkName: { fontWeight: 800, fontSize: 16, flex: 1 },
  infoRow: { display: "flex", justifyContent: "center", gap: 8, flexWrap: "wrap", marginBottom: 16 },
  infoChip: { fontSize: 11, color: "#7a6fa3", fontWeight: 700, background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.08)", padding: "4px 10px", borderRadius: 50 },
  trackBtn: { width: "100%", padding: "12px", borderRadius: 14, background: "rgba(200,255,62,0.1)", border: "1px solid rgba(200,255,62,0.25)", color: "#c8ff3e", fontWeight: 800, fontSize: 14, cursor: "pointer" },
  backBtn: { background: "rgba(255,255,255,0.06)", border: "none", color: "#c8ff3e", fontSize: 13, fontWeight: 800, cursor: "pointer", padding: "6px 14px", borderRadius: 50, marginBottom: 16, display: "inline-block" },
  networkPill: { display: "inline-flex", alignItems: "center", gap: 8, padding: "7px 18px", borderRadius: 50, fontSize: 13, fontWeight: 900, marginBottom: 20 },
  networkPillLogo: { width: 20, height: 20, objectFit: "contain", borderRadius: "50%", background: "#fff" },
  bundleGrid: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 },
  bundleCard: { background: "rgba(10,8,20,0.7)", borderRadius: 16, padding: "18px 14px 14px", cursor: "pointer", textAlign: "center", transition: "transform 0.15s", display: "flex", flexDirection: "column", alignItems: "center", gap: 6 },
  bundleSize: { fontWeight: 900, fontSize: 20, color: "#f3f0fb" },
  bundlePrice: { fontWeight: 900, fontSize: 17 },
  bundleCta: { fontSize: 11, fontWeight: 800, opacity: 0.7 },
  productTypeEmoji: { fontSize: 32, marginBottom: 2 },
  productTypeDesc: { fontSize: 12, color: "#9189b5", fontWeight: 600 },
  checkerGrid: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 },
  checkerCard: { borderRadius: 16, padding: "18px 14px 14px", cursor: "pointer", textAlign: "center", transition: "transform 0.15s", display: "flex", flexDirection: "column", alignItems: "center", gap: 6 },
  floatWrap: { position: "fixed", bottom: "calc(var(--dock, 0px) + 20px)", right: 16, zIndex: 9999, display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 10 },
  chatPopup: { background: "#161126", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 18, padding: 18, width: 270, boxShadow: "0 8px 40px rgba(0,0,0,0.5)" },
  chatHeader: { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 },
  chatClose: { background: "none", border: "none", color: "#9189b5", cursor: "pointer", fontSize: 14, fontWeight: 800 },
  chatMsg: { fontSize: 13, color: "#b4acd0", lineHeight: 1.55, margin: "0 0 12px" },
  chatOptions: { display: "flex", flexDirection: "column", gap: 8 },
  chatOption: { padding: "10px 14px", borderRadius: 10, border: "1px solid rgba(255,255,255,0.08)", background: "rgba(255,255,255,0.04)", color: "#e5e7eb", fontSize: 13, fontWeight: 700, cursor: "pointer", textAlign: "left" },
  floatBtn: { width: 54, height: 54, borderRadius: "50%", background: "linear-gradient(135deg, #25D366, #128C7E)", border: "none", color: "white", fontSize: 22, cursor: "pointer", boxShadow: "0 4px 20px rgba(37,211,102,0.45)", display: "flex", alignItems: "center", justifyContent: "center" },
};

const modal = {
  overlay: { position: "fixed", inset: 0, background: "rgba(0,0,0,0.7)", display: "flex", alignItems: "flex-end", justifyContent: "center", zIndex: 1000 },
  box: { width: "100%", maxWidth: 480, background: "#161126", borderRadius: "24px 24px 0 0", padding: "22px 20px 36px", border: "1px solid rgba(255,255,255,0.08)", boxShadow: "0 -8px 40px rgba(0,0,0,0.5)", fontFamily: "ui-sans-serif, system-ui, Arial", maxHeight: "88vh", overflowY: "auto" },
  header: { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 18 },
  headerLabel: { fontWeight: 900, fontSize: 16, color: "#f3f0fb" },
  closeBtn: { background: "rgba(255,255,255,0.08)", border: "none", color: "#b4acd0", fontSize: 13, cursor: "pointer", padding: "6px 10px", borderRadius: 50, fontWeight: 800 },
  summary: { borderRadius: 16, padding: "10px 16px", marginBottom: 18 },
  summaryHeader: { display: "flex", alignItems: "center", gap: 8, marginBottom: 10, paddingBottom: 8, borderBottom: "1px solid rgba(255,255,255,0.06)" },
  summaryRow: { display: "flex", justifyContent: "space-between", alignItems: "center", padding: "8px 0", borderBottom: "1px solid rgba(255,255,255,0.05)" },
  summaryLabel: { fontSize: 12, color: "#9189b5", fontWeight: 600 },
  summaryValue: { fontSize: 14, fontWeight: 700, color: "#e5e7eb" },
  label: { display: "block", fontSize: 12, color: "#9189b5", fontWeight: 800, marginBottom: 6 },
  input: { width: "100%", padding: "13px 14px", borderRadius: 14, border: "1px solid rgba(255,255,255,0.08)", background: "rgba(10,8,20,0.75)", color: "#fff", fontSize: 14, fontWeight: 600, marginBottom: 14, boxSizing: "border-box", outline: "none" },
  checkRow: { display: "flex", alignItems: "flex-start", background: "rgba(245,158,11,0.08)", border: "1px solid rgba(245,158,11,0.25)", padding: "12px 14px", borderRadius: 14, marginBottom: 18, cursor: "pointer" },
  checkText: { fontSize: 12, color: "#b4acd0", lineHeight: 1.55, fontWeight: 600 },
  buyBtn: { width: "100%", padding: 15, borderRadius: 16, border: "none", background: "linear-gradient(135deg, #22c55e, #16a34a)", color: "white", fontWeight: 900, fontSize: 15, cursor: "pointer", boxShadow: "0 6px 24px rgba(34,197,94,0.3)", marginBottom: 10 },
  secureNote: { textAlign: "center", fontSize: 12, color: "#7a6fa3", margin: 0, fontWeight: 600 },

  verifyOverlay: {
    position: "fixed", inset: 0, background: "rgba(10,8,20,0.75)",
    backdropFilter: "blur(2px)", display: "flex",
    alignItems: "center", justifyContent: "center", zIndex: 2000,
  },
  verifyPopup: {
    background: "#161126", border: "1px solid rgba(255,255,255,0.1)",
    borderRadius: 20, padding: "28px 32px", textAlign: "center",
    boxShadow: "0 20px 60px rgba(0,0,0,0.5)", maxWidth: 280,
  },
  verifySpinner: {
    width: 34, height: 34, margin: "0 auto 14px", borderRadius: "50%",
    border: "3px solid rgba(200,255,62,0.2)", borderTopColor: "#c8ff3e",
    animation: "evos-spin 0.8s linear infinite",
  },
  verifyPopupText: { fontSize: 15, fontWeight: 800, color: "#f3f0fb", margin: "0 0 4px" },
  verifyPopupSub: { fontSize: 12, color: "#9189b5", margin: 0 },
  verifyPopupActions: {
    display: "flex", flexDirection: "column", gap: 8, marginTop: 18,
  },
  verifyPopupProceedBtn: {
    background: "linear-gradient(135deg, #c8ff3e, #8fe600)", color: "#fff",
    border: "none", borderRadius: 12, padding: "12px 16px",
    fontSize: 14, fontWeight: 800, cursor: "pointer",
  },
  verifyPopupCancelBtn: {
    background: "transparent", color: "#b4acd0",
    border: "1px solid rgba(255,255,255,0.12)", borderRadius: 12,
    padding: "10px 16px", fontSize: 13, fontWeight: 700, cursor: "pointer",
  },
};

// =========================
// TRACK MODAL STYLES
// =========================
const trackStyles = {
  searchRow: { display: "flex", gap: 10, marginBottom: 14 },
  searchInput: {
    flex: 1, padding: "13px 14px", borderRadius: 14,
    border: "1px solid rgba(255,255,255,0.08)", background: "rgba(10,8,20,0.75)",
    color: "#fff", fontSize: 14, fontWeight: 600, boxSizing: "border-box", outline: "none",
  },
  searchBtn: {
    padding: "13px 20px", borderRadius: 14, border: "none",
    background: "linear-gradient(135deg,#c8ff3e,#8fe600)", color: "#000",
    fontWeight: 900, fontSize: 14, cursor: "pointer", flexShrink: 0,
  },
  errorBox: {
    background: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.3)",
    color: "#f87171", padding: "12px 14px", borderRadius: 10, fontSize: 13, marginBottom: 14,
  },
  resultsWrap: { display: "flex", flexDirection: "column", gap: 14 },
  card: {
    background: "rgba(10,8,20,0.6)", borderRadius: 18, padding: "18px 16px",
    border: "1px solid rgba(255,255,255,0.07)",
  },
  statusBadge: { display: "flex", alignItems: "center", gap: 8, padding: "10px 14px", borderRadius: 10, marginBottom: 16 },
  statusIcon: { fontSize: 18 },
  statusLabel: { fontWeight: 800, fontSize: 14 },
  detailGrid: {
    background: "rgba(22,17,38,0.6)", borderRadius: 12, padding: "4px 14px",
    marginBottom: 14, border: "1px solid rgba(255,255,255,0.05)",
  },
  detailRow: {
    display: "flex", justifyContent: "space-between", alignItems: "center",
    padding: "10px 0", borderBottom: "1px solid rgba(255,255,255,0.05)",
  },
  detailLabel: { fontSize: 12, color: "#9189b5" },
  detailVal: { fontSize: 13, fontWeight: 600, color: "#e5e7eb" },
  etaBox: { padding: "10px 14px", borderRadius: 10 },
  etaText: { fontSize: 12, margin: 0, lineHeight: 1.55, fontWeight: 500 },
  emptyNote: { textAlign: "center", color: "#7a6fa3", fontSize: 13, fontWeight: 600, margin: "10px 0 0" },
};
