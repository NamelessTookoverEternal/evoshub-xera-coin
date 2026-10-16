import { useEffect, useState } from "react";
import { getCheckerProducts, createCheckerOrder, trackCheckers } from "../api";

export default function Checkers() {
  const [step, setStep] = useState(1);
  const [products, setProducts] = useState([]);
  const [productsLoading, setProductsLoading] = useState(true);
  const [checkerType, setCheckerType] = useState("");
  const [unitPrice, setUnitPrice] = useState(0);
  const [quantity, setQuantity] = useState(1);
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState(localStorage.getItem("email") || "");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [agree, setAgree] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);

  // "Track my checker" lookup
  const [trackOpen, setTrackOpen] = useState(false);
  const [trackPhone, setTrackPhone] = useState("");
  const [trackLoading, setTrackLoading] = useState(false);
  const [trackError, setTrackError] = useState("");
  const [trackResults, setTrackResults] = useState(null);
  const [copiedKey, setCopiedKey] = useState("");

  const user = JSON.parse(localStorage.getItem("user") || "{}");
  const user_id = user?.id || null;

  useEffect(() => {
    const loadProducts = async () => {
      try {
        const res = await getCheckerProducts();
        const data = res.data?.data;
        setProducts(Array.isArray(data) ? data : []);
      } catch {
        setProducts([]);
      } finally {
        setProductsLoading(false);
      }
    };
    loadProducts();
  }, []);

  const validPhone = (num) => /^0\d{9}$/.test(num);

  const checkerCards = [
    { name: "WAEC", label: "WAEC", emoji: "🟢", desc: "West African Senior School Certificate result checker" },
    { name: "BECE", label: "BECE", emoji: "📘", desc: "Basic Education Certificate Examination result checker" },
  ].map((c) => {
    const product = products.find((p) => (p.name || "").toUpperCase() === c.name);
    return {
      ...c,
      price: product ? Number(product.price) : null,
      inStock: product ? !!product.inStock : false,
      found: !!product,
    };
  });

  const selectedCard = checkerCards.find((c) => c.name === checkerType);
  const totalPrice = Number(unitPrice) * Number(quantity || 0);

  const handleSelectType = (card) => {
    if (!card.inStock) return;
    setCheckerType(card.name);
    setUnitPrice(card.price || 0);
    setQuantity(1);
    setStep(2);
  };

  const handleBuy = async () => {
    setError("");
    if (!checkerType) { setError("Select a checker type"); return; }
    if (!quantity || quantity < 1 || quantity > 20) { setError("Quantity must be between 1 and 20"); return; }
    if (!phone) { setError("Enter the phone number to receive the checker"); return; }
    if (!validPhone(phone)) { setError("Phone must be 10 digits and start with 0"); return; }
    if (!agree) { setError("Please confirm the phone number is correct"); return; }

    try {
      setLoading(true);
      const res = await createCheckerOrder({
        user_id,
        checker_type: checkerType,
        phone_number: phone,
        quantity,
        email: email || undefined,
      });

      const data = res.data;
      const paymentUrl = data?.payment_url || data?.data?.authorization_url;

      if (!paymentUrl) {
        setLoading(false);
        setError("Payment link not received");
        return;
      }

      localStorage.setItem("email", email);
      window.location.href = paymentUrl;
    } catch (err) {
      setLoading(false);
      setError(
        err.response?.data?.detail ||
        err.response?.data?.message ||
        "Order failed"
      );
    }
  };

  const handleTrack = async () => {
    setTrackError("");
    setTrackResults(null);
    if (!validPhone(trackPhone)) { setTrackError("Enter a valid 10-digit phone number"); return; }
    try {
      setTrackLoading(true);
      const res = await trackCheckers(trackPhone);
      setTrackResults(res.data?.checkers || []);
    } catch (err) {
      setTrackError(
        err.response?.data?.detail ||
        err.response?.data?.message ||
        "Couldn't fetch your checker orders right now"
      );
    } finally {
      setTrackLoading(false);
    }
  };

  const copyToClipboard = (text, key) => {
    if (!text) return;
    navigator.clipboard?.writeText(text).then(() => {
      setCopiedKey(key);
      setTimeout(() => setCopiedKey(""), 1500);
    });
  };

  return (
    <div style={styles.container}>
      <style>{`@keyframes evos-spin { to { transform: rotate(360deg); } }`}</style>

      {/* HEADER */}
      <div style={styles.header}>
        <div style={styles.headerBadge}>🎓 Result Checkers</div>
        <h2 style={styles.title}>WAEC & BECE Result Checkers</h2>
        <p style={styles.subtitle}>Get your serial number and PIN instantly, delivered by SMS</p>
        <button style={styles.trackLinkBtn} onClick={() => setTrackOpen(true)}>
          🔎 Already bought one? Find your checker
        </button>
      </div>

      {/* PROGRESS BAR */}
      <div style={styles.progressWrap}>
        {["Type", "Checkout"].map((label, i) => {
          const active = step === i + 1;
          const done = step > i + 1;
          return (
            <div key={i} style={styles.progressItem}>
              <div style={{
                ...styles.progressDot,
                background: done ? "#22c55e" : active ? "#22c55e" : "rgba(255,255,255,0.1)",
                border: active ? "2px solid #22c55e" : done ? "2px solid #22c55e" : "2px solid rgba(255,255,255,0.1)",
              }}>
                {done ? "✓" : i + 1}
              </div>
              <span style={{
                ...styles.progressLabel,
                color: active || done ? "#22c55e" : "#7a6fa3",
              }}>{label}</span>
            </div>
          );
        })}
        <div style={styles.progressLine} />
      </div>

      {/* ERROR */}
      {error && <div style={styles.error}>⚠️ {error}</div>}

      <div style={styles.wrapper}>

        {/* ============ STEP 1 — CHECKER TYPE ============ */}
        {step === 1 && (
          <div style={styles.box}>
            <p style={styles.stepLabel}>Step 1 of 2 · Select Checker Type</p>

            {productsLoading ? (
              <p style={styles.emptyText}>Loading available checkers…</p>
            ) : (
              <div style={styles.networkGrid}>
                {checkerCards.map((c) => {
                  const disabled = !c.inStock;
                  return (
                    <div
                      key={c.name}
                      style={{
                        ...styles.networkCard,
                        background: "linear-gradient(135deg, rgba(34,197,94,0.16), rgba(34,197,94,0.05))",
                        border: "1px solid rgba(34,197,94,0.35)",
                        opacity: disabled ? 0.45 : 1,
                        cursor: disabled ? "not-allowed" : "pointer",
                      }}
                      onClick={() => handleSelectType(c)}
                    >
                      <div style={{ ...styles.networkEmoji, color: "#22c55e" }}>{c.emoji}</div>
                      <div style={{ flex: 1 }}>
                        <div style={{ ...styles.networkName, color: "#22c55e" }}>{c.label} Checker</div>
                        <div style={styles.networkDesc}>{c.desc}</div>
                        {c.found && (
                          <div style={styles.priceTag}>GH₵ {Number(c.price).toFixed(2)} per card</div>
                        )}
                      </div>
                      {disabled && <div style={styles.stockBadge}>Out of Stock</div>}
                      {!disabled && <div style={{ ...styles.networkArrow, color: "#22c55e" }}>→</div>}
                    </div>
                  );
                })}
              </div>
            )}

            <div style={styles.infoRow}>
              <span style={styles.infoText}>🔒 Secured by Paystack</span>
              <span style={styles.infoText}>⚡ Delivered instantly</span>
            </div>
          </div>
        )}

        {/* ============ STEP 2 — CHECKOUT ============ */}
        {step === 2 && (
          <div style={styles.box}>
            <button style={styles.backBtn} onClick={() => setStep(1)}>← Back</button>
            <p style={styles.stepLabel}>Step 2 of 2 · Complete Order</p>

            <div style={{
              ...styles.networkPill,
              background: "rgba(34,197,94,0.15)",
              border: "1px solid rgba(34,197,94,0.35)",
              color: "#22c55e",
            }}>
              {selectedCard?.emoji} {selectedCard?.label} Checker
            </div>

            <label style={styles.inputLabel}>🔢 Quantity (1–20)</label>
            <div style={styles.qtyRow}>
              <button
                type="button"
                style={styles.qtyBtn}
                onClick={() => setQuantity((q) => Math.max(1, Number(q) - 1))}
              >−</button>
              <input
                style={styles.qtyInput}
                type="number"
                min={1}
                max={20}
                value={quantity}
                onChange={(e) => {
                  const v = parseInt(e.target.value, 10);
                  setQuantity(Number.isNaN(v) ? 1 : Math.min(20, Math.max(1, v)));
                }}
              />
              <button
                type="button"
                style={styles.qtyBtn}
                onClick={() => setQuantity((q) => Math.min(20, Number(q) + 1))}
              >+</button>
            </div>

            <div style={styles.summaryCard}>
              <div style={styles.summaryRow}>
                <span style={styles.summaryLabel}>Type</span>
                <span style={{ ...styles.summaryVal, color: "#22c55e", fontWeight: 800 }}>
                  {selectedCard?.emoji} {selectedCard?.label}
                </span>
              </div>
              <div style={styles.summaryRow}>
                <span style={styles.summaryLabel}>Unit price</span>
                <span style={styles.summaryVal}>GH₵ {Number(unitPrice).toFixed(2)}</span>
              </div>
              <div style={styles.summaryRow}>
                <span style={styles.summaryLabel}>Quantity</span>
                <span style={styles.summaryVal}>{quantity}</span>
              </div>
              <div style={{ ...styles.summaryRow, borderBottom: "none" }}>
                <span style={styles.summaryLabel}>Total</span>
                <span style={{ ...styles.summaryVal, color: "#22c55e", fontSize: 20, fontWeight: 900 }}>
                  GH₵ {totalPrice.toFixed(2)}
                </span>
              </div>
            </div>

            <label style={styles.inputLabel}>📱 Phone Number (to receive SMS)</label>
            <input
              style={{
                ...styles.input,
                borderColor: phone && !validPhone(phone)
                  ? "rgba(239,68,68,0.6)"
                  : phone && validPhone(phone)
                  ? "rgba(34,197,94,0.6)"
                  : "rgba(255,255,255,0.08)",
              }}
              type="tel"
              placeholder="e.g. 0244000000"
              value={phone}
              maxLength={10}
              onChange={(e) => setPhone(e.target.value)}
            />
            {phone.length > 0 && !validPhone(phone) && (
              <p style={styles.phoneHint}>⚠️ Must be 10 digits starting with 0</p>
            )}
            {phone.length > 0 && validPhone(phone) && (
              <p style={styles.phoneHintGood}>✅ Looks good!</p>
            )}

            <label style={styles.inputLabel}>📧 Email (for receipt)</label>
            <input
              style={styles.input}
              type="email"
              placeholder="your@email.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />

            <label style={styles.checkWrap}>
              <input
                type="checkbox"
                checked={agree}
                onChange={() => setAgree(!agree)}
                style={{ accentColor: "#22c55e", width: 16, height: 16, flexShrink: 0, marginTop: 2 }}
              />
              <span style={styles.checkText}>
                I confirm this phone number is correct.{" "}
                <strong style={{ color: "#f87171" }}>Wrong numbers will NOT be refunded.</strong>{" "}
                I take full responsibility.
              </span>
            </label>

            <button
              onClick={handleBuy}
              disabled={loading}
              style={{ ...styles.buyBtn, opacity: loading ? 0.6 : 1 }}
            >
              {loading ? "⏳ Processing..." : `💳 Pay GH₵ ${totalPrice.toFixed(2)} via Paystack`}
            </button>

            <p style={styles.secureNote}>🔒 Secured & encrypted via Paystack</p>
          </div>
        )}
      </div>

      {/* TRACK MY CHECKER POPUP */}
      {trackOpen && (
        <div style={styles.verifyOverlay} onClick={() => setTrackOpen(false)}>
          <div style={styles.trackPopup} onClick={(e) => e.stopPropagation()}>
            <div style={styles.trackHeader}>
              <span style={{ fontWeight: 900, fontSize: 16, color: "#f3f0fb" }}>🔎 Find My Checker</span>
              <button style={styles.chatClose} onClick={() => setTrackOpen(false)}>✕</button>
            </div>
            <p style={{ fontSize: 13, color: "#b4acd0", margin: "0 0 14px", lineHeight: 1.5 }}>
              Enter the phone number you used at checkout to see your serial number and PIN.
            </p>
            <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
              <input
                style={{ ...styles.input, marginBottom: 0 }}
                type="tel"
                placeholder="e.g. 0244000000"
                value={trackPhone}
                maxLength={10}
                onChange={(e) => setTrackPhone(e.target.value)}
              />
              <button
                style={styles.trackSearchBtn}
                onClick={handleTrack}
                disabled={trackLoading}
              >
                {trackLoading ? "…" : "Search"}
              </button>
            </div>
            {trackError && <p style={styles.phoneHint}>⚠️ {trackError}</p>}

            {trackResults && trackResults.length === 0 && (
              <p style={styles.emptyText}>No checker orders found for this number.</p>
            )}

            {trackResults && trackResults.length > 0 && (
              <div style={styles.trackResultsList}>
                {trackResults.map((c, i) => (
                  <div key={i} style={styles.trackResultCard}>
                    <div style={styles.trackResultHead}>
                      <span style={{ fontWeight: 800, color: "#22c55e", fontSize: 13 }}>
                        {c.checker_type} × {c.quantity}
                      </span>
                      <span style={{
                        ...styles.trackStatusPill,
                        color: c.status === "successful" ? "#22c55e" : c.status === "failed" ? "#f87171" : "#fbbf24",
                        background: c.status === "successful" ? "rgba(34,197,94,0.12)" : c.status === "failed" ? "rgba(239,68,68,0.12)" : "rgba(251,191,36,0.12)",
                      }}>
                        {c.status}
                      </span>
                    </div>
                    {c.status === "successful" && Array.isArray(c.serial_numbers) && c.serial_numbers.length > 0 ? (
                      <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 6 }}>
                        {c.serial_numbers.map((card, j) => (
                          <div key={j} style={styles.cardBox}>
                            <div style={styles.cardRow}>
                              <span style={styles.cardLabel}>Serial</span>
                              <span style={styles.cardValue}>{card.serialNumber}</span>
                              <button
                                style={styles.copyBtn}
                                onClick={() => copyToClipboard(card.serialNumber, `s-${i}-${j}`)}
                              >
                                {copiedKey === `s-${i}-${j}` ? "✓" : "Copy"}
                              </button>
                            </div>
                            <div style={styles.cardRow}>
                              <span style={styles.cardLabel}>PIN</span>
                              <span style={styles.cardValue}>{card.pin}</span>
                              <button
                                style={styles.copyBtn}
                                onClick={() => copyToClipboard(card.pin, `p-${i}-${j}`)}
                              >
                                {copiedKey === `p-${i}-${j}` ? "✓" : "Copy"}
                              </button>
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p style={{ fontSize: 12, color: "#9189b5", margin: "6px 0 0" }}>
                        {c.status === "failed"
                          ? "This order did not go through. Contact support if you were charged."
                          : "Still processing — check back shortly."}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* FLOATING SUPPORT */}
      <div style={styles.floatWrap}>
        {chatOpen && (
          <div style={styles.chatPopup}>
            <div style={styles.chatHeader}>
              <span style={{ fontWeight: 800, fontSize: 14, color: "#e5e7eb" }}>💬 EVOS Support</span>
              <button style={styles.chatClose} onClick={() => setChatOpen(false)}>✕</button>
            </div>
            <p style={styles.chatMsg}>Hi! Need help with your checker order? Choose an option below 👇</p>
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
  container: {
    padding: "24px 18px 60px", color: "#e5e7eb",
    fontFamily: "ui-sans-serif, system-ui, Arial", minHeight: "auto",
  },
  header: { textAlign: "center", marginBottom: 28 },
  headerBadge: {
    display: "inline-block", padding: "5px 16px", borderRadius: 50,
    background: "rgba(34,197,94,0.15)", border: "1px solid rgba(34,197,94,0.3)",
    color: "#22c55e", fontSize: 12, fontWeight: 700, marginBottom: 12,
  },
  title: { fontSize: 24, fontWeight: 900, color: "#f3f0fb", margin: "0 0 6px" },
  subtitle: { fontSize: 14, color: "#9189b5", margin: "0 0 12px" },
  trackLinkBtn: {
    background: "none", border: "none", color: "#22c55e",
    fontSize: 13, fontWeight: 700, cursor: "pointer", padding: 0,
    textDecoration: "underline", textUnderlineOffset: 3,
  },

  progressWrap: {
    display: "flex", justifyContent: "center", alignItems: "center",
    gap: 0, marginBottom: 28, position: "relative",
    maxWidth: 260, margin: "0 auto 28px",
  },
  progressItem: {
    display: "flex", flexDirection: "column", alignItems: "center",
    gap: 6, flex: 1, position: "relative", zIndex: 1,
  },
  progressDot: {
    width: 32, height: 32, borderRadius: "50%",
    display: "flex", alignItems: "center", justifyContent: "center",
    fontSize: 13, fontWeight: 800, color: "white", transition: "all 0.3s",
  },
  progressLabel: { fontSize: 11, fontWeight: 700, transition: "color 0.3s" },
  progressLine: {
    position: "absolute", top: 16, left: "20%", right: "20%",
    height: 2, background: "rgba(255,255,255,0.08)", zIndex: 0,
  },

  error: {
    background: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.3)",
    color: "#f87171", padding: "12px 16px", borderRadius: 12,
    marginBottom: 16, fontSize: 14, maxWidth: 480,
    margin: "0 auto 16px", textAlign: "center",
  },

  wrapper: { maxWidth: 480, margin: "0 auto" },
  box: {
    background: "rgba(22,17,38,0.9)", backdropFilter: "blur(20px)",
    WebkitBackdropFilter: "blur(20px)", padding: "24px 20px",
    borderRadius: 22, border: "1px solid rgba(255,255,255,0.07)",
    boxShadow: "0 25px 60px rgba(0,0,0,0.4)",
  },
  stepLabel: {
    fontSize: 12, color: "#22c55e", fontWeight: 700,
    textTransform: "uppercase", letterSpacing: "0.8px", margin: "0 0 18px",
  },

  networkGrid: { display: "flex", flexDirection: "column", gap: 12, marginBottom: 20 },
  networkCard: {
    padding: "16px 18px", borderRadius: 16, cursor: "pointer",
    display: "flex", alignItems: "center", gap: 14,
    transition: "transform 0.15s", position: "relative",
  },
  networkEmoji: { fontSize: 26, flexShrink: 0 },
  networkName: { fontWeight: 800, fontSize: 16, marginBottom: 2 },
  networkDesc: { fontSize: 12, color: "#9189b5", lineHeight: 1.4 },
  priceTag: { fontSize: 12, color: "#22c55e", fontWeight: 800, marginTop: 6 },
  networkArrow: { fontSize: 18, fontWeight: 900, flexShrink: 0 },
  stockBadge: {
    position: "absolute", right: 14, top: "50%", transform: "translateY(-50%)",
    background: "rgba(239,68,68,0.15)", border: "1px solid rgba(239,68,68,0.3)",
    color: "#ef4444", fontSize: 11, fontWeight: 800, padding: "3px 10px", borderRadius: 50,
  },
  infoRow: { display: "flex", justifyContent: "center", gap: 20 },
  infoText: { fontSize: 12, color: "#7a6fa3", fontWeight: 600 },
  emptyText: { color: "#7a6fa3", fontSize: 14, textAlign: "center", padding: "20px 0" },

  backBtn: {
    background: "none", border: "none", color: "#22c55e",
    fontSize: 14, fontWeight: 700, cursor: "pointer",
    padding: 0, marginBottom: 14, display: "block",
  },
  networkPill: {
    display: "inline-block", padding: "6px 16px", borderRadius: 50,
    fontSize: 13, fontWeight: 800, marginBottom: 18,
  },

  qtyRow: { display: "flex", alignItems: "center", gap: 10, marginBottom: 18 },
  qtyBtn: {
    width: 40, height: 40, borderRadius: 12, border: "1px solid rgba(34,197,94,0.3)",
    background: "rgba(34,197,94,0.1)", color: "#22c55e", fontSize: 18, fontWeight: 900,
    cursor: "pointer", flexShrink: 0,
  },
  qtyInput: {
    flex: 1, textAlign: "center", padding: "10px 8px", borderRadius: 12,
    border: "1.5px solid rgba(255,255,255,0.08)", background: "rgba(10,8,20,0.75)",
    color: "#fff", fontSize: 16, fontWeight: 800, outline: "none",
  },

  summaryCard: {
    background: "rgba(10,8,20,0.7)", border: "1px solid rgba(255,255,255,0.06)",
    borderRadius: 16, padding: "6px 16px", marginBottom: 22,
  },
  summaryRow: {
    display: "flex", justifyContent: "space-between", alignItems: "center",
    padding: "12px 0", borderBottom: "1px solid rgba(255,255,255,0.05)",
  },
  summaryLabel: { fontSize: 13, color: "#9189b5" },
  summaryVal: { fontSize: 15, fontWeight: 700, color: "#e5e7eb" },

  inputLabel: { display: "block", fontSize: 12, color: "#9189b5", fontWeight: 700, marginBottom: 6 },
  input: {
    width: "100%", padding: "13px 14px", marginBottom: 6, borderRadius: 12,
    border: "1.5px solid", background: "rgba(10,8,20,0.75)",
    color: "#fff", outline: "none", fontSize: 14, boxSizing: "border-box",
    transition: "border-color 0.2s",
  },
  phoneHint: { fontSize: 12, color: "#f87171", margin: "0 0 14px", paddingLeft: 2 },
  phoneHintGood: { fontSize: 12, color: "#22c55e", margin: "0 0 14px", paddingLeft: 2 },

  checkWrap: {
    display: "flex", gap: 10, alignItems: "flex-start",
    background: "rgba(34,197,94,0.08)", border: "1px solid rgba(34,197,94,0.25)",
    padding: "12px 14px", borderRadius: 12, marginBottom: 16, cursor: "pointer", marginTop: 8,
  },
  checkText: { fontSize: 13, color: "#b4acd0", lineHeight: 1.55 },
  buyBtn: {
    width: "100%", padding: "15px", borderRadius: 14, border: "none",
    background: "linear-gradient(135deg, #22c55e, #16a34a)", color: "white",
    fontWeight: 900, fontSize: 15, cursor: "pointer", marginBottom: 12,
    boxShadow: "0 4px 20px rgba(34,197,94,0.3)",
  },
  secureNote: { textAlign: "center", fontSize: 12, color: "#7a6fa3", margin: 0 },

  verifyOverlay: {
    position: "fixed", inset: 0, background: "rgba(10,8,20,0.7)",
    backdropFilter: "blur(2px)", display: "flex",
    alignItems: "center", justifyContent: "center", zIndex: 2000, padding: 16,
  },
  trackPopup: {
    background: "#161126", border: "1px solid rgba(255,255,255,0.1)",
    borderRadius: 20, padding: "22px 20px", textAlign: "left",
    boxShadow: "0 20px 60px rgba(0,0,0,0.5)", maxWidth: 380, width: "100%",
    maxHeight: "80vh", overflowY: "auto",
  },
  trackHeader: { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 },
  trackSearchBtn: {
    padding: "0 16px", borderRadius: 12, border: "none",
    background: "linear-gradient(135deg, #22c55e, #16a34a)", color: "white",
    fontWeight: 800, fontSize: 13, cursor: "pointer", flexShrink: 0,
  },
  trackResultsList: { display: "flex", flexDirection: "column", gap: 10, marginTop: 6 },
  trackResultCard: {
    background: "rgba(10,8,20,0.6)", border: "1px solid rgba(255,255,255,0.06)",
    borderRadius: 12, padding: "12px 14px",
  },
  trackResultHead: { display: "flex", justifyContent: "space-between", alignItems: "center" },
  trackStatusPill: {
    fontSize: 10, fontWeight: 800, padding: "3px 10px", borderRadius: 50,
    textTransform: "uppercase", letterSpacing: "0.3px",
  },
  cardBox: {
    background: "rgba(34,197,94,0.06)", border: "1px solid rgba(34,197,94,0.2)",
    borderRadius: 10, padding: "8px 10px",
  },
  cardRow: { display: "flex", alignItems: "center", gap: 8, padding: "3px 0" },
  cardLabel: { fontSize: 11, color: "#9189b5", fontWeight: 700, width: 44, flexShrink: 0 },
  cardValue: {
    fontSize: 13, color: "#f3f0fb", fontWeight: 800, fontFamily: "monospace",
    flex: 1, wordBreak: "break-all",
  },
  copyBtn: {
    fontSize: 11, fontWeight: 800, color: "#22c55e", background: "rgba(34,197,94,0.12)",
    border: "1px solid rgba(34,197,94,0.3)", borderRadius: 8, padding: "3px 8px",
    cursor: "pointer", flexShrink: 0,
  },

  floatWrap: {
    position: "fixed", bottom: "calc(var(--dock, 0px) + 20px)", right: 16, zIndex: 9999,
    display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 10,
  },
  chatPopup: {
    background: "#161126", border: "1px solid rgba(255,255,255,0.1)",
    borderRadius: 18, padding: 18, width: 270, boxShadow: "0 8px 32px rgba(0,0,0,0.5)",
  },
  chatHeader: { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 },
  chatClose: { background: "none", border: "none", color: "#9189b5", cursor: "pointer", fontSize: 14 },
  chatMsg: { fontSize: 13, color: "#b4acd0", lineHeight: 1.55, margin: "0 0 12px" },
  chatOptions: { display: "flex", flexDirection: "column", gap: 8 },
  chatOption: {
    padding: "10px 14px", borderRadius: 10, border: "1px solid rgba(255,255,255,0.08)",
    background: "rgba(255,255,255,0.04)", color: "#e5e7eb",
    fontSize: 13, fontWeight: 700, cursor: "pointer", textAlign: "left",
  },
  floatBtn: {
    width: 54, height: 54, borderRadius: "50%",
    background: "linear-gradient(135deg, #25D366, #128C7E)",
    border: "none", color: "white", fontSize: 22, cursor: "pointer",
    boxShadow: "0 4px 20px rgba(37,211,102,0.45)",
    display: "flex", alignItems: "center", justifyContent: "center",
  },
};
