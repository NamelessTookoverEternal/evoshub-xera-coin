import { useEffect, useState } from "react";

import { smartFetch } from "../config";

const OUT_OF_STOCK = [];

const NETWORKS = [
  { name: "MTN", icon: "🟡", style: styles_network("mtn") },
  { name: "Telecel (Vodafone)", icon: "🔴", style: styles_network("telecel") },
  { name: "AirtelTigo", icon: "🔵", style: styles_network("airtel") },
];

function styles_network(n) {
  if (n === "mtn") return {
    background: "linear-gradient(135deg, rgba(255,193,7,0.15), rgba(255,193,7,0.05))",
    border: "1px solid rgba(255,193,7,0.3)",
  };
  if (n === "telecel") return {
    background: "linear-gradient(135deg, rgba(239,68,68,0.15), rgba(239,68,68,0.05))",
    border: "1px solid rgba(239,68,68,0.3)",
  };
  return {
    background: "linear-gradient(135deg, rgba(59,130,246,0.15), rgba(59,130,246,0.05))",
    border: "1px solid rgba(59,130,246,0.3)",
  };
}

export default function AgentStore({ setPage }) {
  const [loading, setLoading] = useState(true);
  const [store, setStore] = useState(null);
  const [step, setStep] = useState(1);

  const [network, setNetwork] = useState("");
  const [bundle, setBundle] = useState("");
  const [finalPrice, setFinalPrice] = useState(0);
  const [phone, setPhone] = useState("");
  const [confirmPhone, setConfirmPhone] = useState("");
  const [agree, setAgree] = useState(false);
  const [error, setError] = useState("");
  const [processing, setProcessing] = useState(false);

  useEffect(() => {
    const agentId = window.location.pathname.split("/store/")[1];
    if (!agentId) { setLoading(false); return; }

    const load = async () => {
      try {
        const res = await smartFetch(`/store/${agentId}`);
        const data = await res.json();
        setStore(data);
      } catch (e) {
        console.log(e);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, []);

  const isOutOfStock = (name) => OUT_OF_STOCK.includes(name);

  // Map display name → actual network key in store.prices
  const networkKey = network.replace(" (Vodafone)", "");
  const bundles = (store?.prices || []).filter((p) => p.network === networkKey);

  const validPhone = (num) => /^0\d{9}$/.test(num);

  const handleBuy = async () => {
    setError("");

    if (!validPhone(phone)) {
      setError("Phone must be 10 digits and start with 0");
      return;
    }
    if (phone !== confirmPhone) {
      setError("Phone numbers do not match");
      return;
    }
    if (!agree) {
      setError("You must confirm the refund policy");
      return;
    }

    setProcessing(true);
    try {
      const res = await smartFetch(`/store/order`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          agent_id: store.agent_id,
          phone_number: phone,
          network: networkKey,
          bundle: bundle,
        }),
      });
      const data = await res.json();

      if (data.status === "created" && data.payment_url) {
        window.location.href = data.payment_url;
        return;
      }
      setError(data.message || "Order failed");
    } catch (e) {
      setError("Network error. Please try again.");
    } finally {
      setProcessing(false);
    }
  };

  if (loading) return <p style={{ padding: 20, color: "#e5e7eb" }}>Loading store...</p>;
  if (!store) return <p style={{ padding: 20, color: "#e5e7eb" }}>Store not found</p>;

  return (
    <div style={styles.container}>

      <h2 style={styles.title}>{store.store_name || store.agent_name || "Agent Store"}</h2>
      <p style={styles.subTitle}>Fast Data Purchase • Powered by EVOS HUB</p>

      {error && <div style={styles.error}>{error}</div>}

      <div style={styles.wrapper}>

        {/* STEP 1 — NETWORK */}
        {step === 1 && (
          <div style={styles.box}>
            <h3 style={styles.step}>Select Network</h3>

            {NETWORKS.map((n) => {
              const disabled = isOutOfStock(n.name);
              return (
                <div
                  key={n.name}
                  style={{
                    ...styles.option,
                    ...n.style,
                    opacity: disabled ? 0.45 : 1,
                    cursor: disabled ? "not-allowed" : "pointer",
                  }}
                  onClick={() => {
                    if (disabled) return;
                    setNetwork(n.name);
                    setStep(2);
                  }}
                >
                  <span>{n.icon}</span>
                  {n.name}
                  {disabled && <span style={styles.stock}>Out of Stock</span>}
                </div>
              );
            })}

            <button style={styles.trackBtn} onClick={() => setPage("order-tracking")}>
              Track Order
            </button>
          </div>
        )}

        {/* STEP 2 — BUNDLE */}
        {step === 2 && (
          <div style={styles.box}>
            <button style={styles.back} onClick={() => setStep(1)}>← Back</button>
            <h3 style={styles.step}>Select Bundle — <span style={{ color: "#c8ff3e" }}>{network}</span></h3>

            {bundles.length === 0 && (
              <p style={{ color: "#9189b5", fontSize: 13 }}>No bundles available.</p>
            )}

            <div style={styles.bundleGrid}>
              {bundles.map((b, i) => (
                <div
                  key={i}
                  style={styles.bundleCard}
                  onClick={() => {
                    setBundle(b.bundle);
                    setFinalPrice(b.final_price);
                    setStep(3);
                  }}
                >
                  <span style={styles.bundleName}>{b.bundle}</span>
                  <span style={styles.bundlePrice}>GH₵ {Number(b.final_price).toFixed(2)}</span>
                  <span style={styles.bundleArrow}>Tap →</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* STEP 3 — CHECKOUT */}
        {step === 3 && (
          <div style={styles.box}>
            <button style={styles.back} onClick={() => setStep(2)}>← Back</button>
            <h3 style={styles.step}>Complete Order</h3>

            <div style={styles.summary}>
              <p style={{ margin: "0 0 4px", color: "#b4acd0", fontSize: 13 }}>{network}</p>
              <h3 style={{ margin: "0 0 4px", color: "#e5e7eb" }}>{bundle}</h3>
              <p style={{ margin: 0, color: "#c8ff3e", fontWeight: 800, fontSize: 18 }}>
                GH₵ {Number(finalPrice).toFixed(2)}
              </p>
            </div>

            <input
              style={styles.input}
              type="tel"
              placeholder="Phone Number (e.g. 0244000000)"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
            />

            <input
              style={styles.input}
              type="tel"
              placeholder="Confirm Phone Number"
              value={confirmPhone}
              onChange={(e) => setConfirmPhone(e.target.value)}
            />

            <div style={styles.notice}>
              <label style={styles.checkWrap}>
                <input
                  type="checkbox"
                  checked={agree}
                  onChange={() => setAgree(!agree)}
                  style={{ accentColor: "#c8ff3e", flexShrink: 0, marginTop: 2 }}
                />
                <span style={styles.checkText}>
                  I confirm this number is correct.{" "}
                  <strong style={{ color: "#f87171" }}>Wrong numbers will NOT be refunded.</strong>{" "}
                  I take full responsibility for the number entered.
                </span>
              </label>
            </div>

            <button
              onClick={handleBuy}
              disabled={processing}
              style={{ ...styles.buyBtn, opacity: processing ? 0.6 : 1 }}
            >
              {processing ? "Processing..." : `Pay GH₵ ${Number(finalPrice).toFixed(2)} →`}
            </button>
          </div>
        )}

      </div>
    </div>
  );
}

const styles = {
  container: {
    padding: "24px",
    color: "#e5e7eb",
    textAlign: "center",
    minHeight: "auto",
  },
  title: {
    marginBottom: "6px",
    fontSize: "24px",
    fontWeight: "900",
  },
  subTitle: {
    color: "#b4acd0",
    marginBottom: "22px",
    fontSize: "14px",
  },
  wrapper: {
    maxWidth: "440px",
    margin: "0 auto",
  },
  box: {
    background: "rgba(22,17,38, 0.88)",
    backdropFilter: "blur(16px)",
    WebkitBackdropFilter: "blur(16px)",
    padding: "22px",
    borderRadius: "18px",
    boxShadow: "0 25px 60px rgba(0,0,0,0.45)",
    border: "1px solid rgba(255,255,255,0.06)",
    textAlign: "left",
  },
  step: {
    marginBottom: "16px",
    color: "#c8ff3e",
    fontWeight: "700",
    fontSize: "14px",
    textTransform: "uppercase",
    letterSpacing: "0.6px",
  },
  option: {
    padding: "16px",
    marginBottom: "12px",
    borderRadius: "14px",
    cursor: "pointer",
    display: "flex",
    alignItems: "center",
    gap: "10px",
    fontWeight: "700",
    transition: "0.2s ease",
  },
  stock: {
    marginLeft: "auto",
    color: "#ef4444",
    fontSize: "12px",
    fontWeight: "800",
  },
  bundleGrid: {
    display: "grid",
    gridTemplateColumns: "1fr 1fr",
    gap: 10,
  },
  bundleCard: {
    background: "rgba(10,8,20,0.65)",
    border: "1px solid rgba(255,255,255,0.07)",
    borderRadius: 12,
    padding: "14px 12px",
    cursor: "pointer",
    display: "flex",
    flexDirection: "column",
    gap: 4,
  },
  bundleName: { fontWeight: 700, fontSize: 13, color: "#e5e7eb" },
  bundlePrice: { fontWeight: 800, fontSize: 16, color: "#c8ff3e" },
  bundleArrow: { fontSize: 10, color: "#c8ff3e", opacity: 0.6, marginTop: 2 },
  summary: {
    background: "rgba(10,8,20, 0.65)",
    padding: "14px",
    borderRadius: "12px",
    marginBottom: "15px",
    border: "1px solid rgba(255,255,255,0.05)",
  },
  input: {
    width: "100%",
    padding: "14px",
    marginBottom: "12px",
    borderRadius: "12px",
    border: "1px solid rgba(255,255,255,0.08)",
    background: "rgba(10,8,20, 0.75)",
    color: "#ffffff",
    outline: "none",
    fontSize: "14px",
    boxSizing: "border-box",
  },
  notice: {
    background: "rgba(245,158,11,0.08)",
    border: "1px solid rgba(245,158,11,0.25)",
    padding: "12px",
    borderRadius: "12px",
    marginBottom: "14px",
    textAlign: "left",
  },
  checkWrap: {
    display: "flex",
    gap: "10px",
    alignItems: "flex-start",
    fontSize: "14px",
    lineHeight: "1.5",
    cursor: "pointer",
  },
  checkText: { fontSize: 13, color: "#b4acd0", lineHeight: 1.55 },
  buyBtn: {
    width: "100%",
    padding: "14px",
    borderRadius: "14px",
    background: "linear-gradient(135deg,#c8ff3e,#8fe600)",
    border: "none",
    color: "#000",
    fontWeight: "900",
    cursor: "pointer",
    fontSize: "15px",
  },
  back: {
    marginBottom: "12px",
    background: "transparent",
    border: "none",
    color: "#c8ff3e",
    cursor: "pointer",
    fontWeight: "700",
    fontSize: "14px",
    padding: 0,
  },
  trackBtn: {
    marginTop: "14px",
    width: "100%",
    padding: "12px",
    borderRadius: "12px",
    background: "#241c3d",
    color: "white",
    border: "none",
    cursor: "pointer",
    fontSize: "14px",
  },
  error: {
    background: "rgba(127, 29, 29, 0.8)",
    color: "#ffffff",
    padding: "12px",
    borderRadius: "12px",
    marginBottom: "14px",
    border: "1px solid rgba(255,255,255,0.08)",
    maxWidth: "440px",
    marginInline: "auto",
  },
};
