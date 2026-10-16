import { useState } from "react";
import { BUSINESS_HUB_API_BASE } from "../config";

export default function OrderTracking() {
  const [ref, setRef] = useState("");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);

  const trackOrder = async () => {
    if (!ref) return;

    setLoading(true);

    try {
      const res = await fetch(
        `${BUSINESS_HUB_API_BASE}/orders/sync/${ref}`,
        {
          method: "POST",
        }
      );

      const result = await res.json();
      setData(result);
    } catch (err) {
      alert("Error tracking order");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={styles.wrap}>
      <h1 style={styles.title}>Track Order</h1>

      <input
        placeholder="Enter order reference"
        value={ref}
        onChange={(e) => setRef(e.target.value)}
        style={styles.input}
      />

      <button onClick={trackOrder} style={styles.btn}>
        {loading ? "Checking..." : "Track"}
      </button>

      {data && (
        <div style={styles.card}>
          <p>Status: <b>{data.status}</b></p>
          <p>Network: {data.network}</p>
          <p>Phone: {data.phone}</p>
          <p>Message: {data.message}</p>
        </div>
      )}
    </div>
  );
}

const styles = {
  wrap: {
    maxWidth: 600,
    margin: "0 auto",
    padding: 20,
    color: "white",
  },

  title: {
    fontSize: 26,
    fontWeight: 900,
  },

  input: {
    width: "100%",
    padding: 12,
    marginTop: 20,
    borderRadius: 12,
    background: "#0a0814",
    color: "white",
    border: "1px solid rgba(255,255,255,0.1)",
  },

  btn: {
    width: "100%",
    marginTop: 12,
    padding: 14,
    borderRadius: 12,
    border: "none",
    background: "#c8ff3e",
    fontWeight: 800,
    cursor: "pointer",
  },

  card: {
    marginTop: 20,
    padding: 14,
    borderRadius: 12,
    background: "#161126",
  },
};
