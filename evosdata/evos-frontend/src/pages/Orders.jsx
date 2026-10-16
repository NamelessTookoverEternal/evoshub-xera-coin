import { useEffect, useState } from "react";
import { getOrders } from "../api";

export default function Orders() {
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // ✅ USE REAL USER ID INSTEAD OF EMAIL
  const userId = localStorage.getItem("user_id");

  // 🔥 STATUS COLOR MAP
  const getColor = (status) => {
    if (status === "pending_payment") return "#f59e0b";
    if (status === "processing") return "#3b82f6";
    if (status === "successful") return "#10b981";
    if (status === "failed") return "#ef4444";
    return "#6b7280";
  };

  // ⚡ NEW: STATUS LABEL MAP (UI ONLY - DATAMART AWARE)
  const getStatusLabel = (status) => {
    if (status === "pending_payment") return "Waiting for Payment";

    if (status === "processing")
      return "Processed (Delivery: 1 min - 4 hrs)";

    if (status === "successful")
      return "Delivered Successfully";

    if (status === "failed")
      return "Delivery Failed";

    return "Unknown Status";
  };

  // 🔥 FETCH ORDERS
  const loadOrders = async () => {
    if (!userId) {
      setLoading(false);
      return;
    }

    try {
      setError("");

      const res = await getOrders(userId);

      // ✅ BACKEND RETURNS { status, orders }
      if (Array.isArray(res.data.orders)) {
        setOrders(res.data.orders);
      } else {
        setOrders([]);
      }
    } catch (err) {
      console.error(err);
      setOrders([]);
      setError("Failed to load orders");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadOrders();

    const interval = setInterval(loadOrders, 5000);

    return () => clearInterval(interval);
  }, [userId]);

  return (
    <div style={styles.container}>
      <h1 style={styles.title}>My Orders</h1>

      {/* NOT LOGGED IN */}
      {!userId && (
        <p style={styles.info}>
          Please login to view your orders.
        </p>
      )}

      {/* LOADING */}
      {loading && userId && (
        <p style={styles.info}>Loading orders...</p>
      )}

      {/* ERROR */}
      {error && <p style={styles.error}>{error}</p>}

      {/* EMPTY */}
      {!loading && userId && orders.length === 0 && !error && (
        <p style={styles.info}>No orders yet.</p>
      )}

      {/* ORDERS */}
      <div style={styles.grid}>
        {orders.map((o, i) => (
          <div key={i} style={styles.card}>
            <h3>{o.network} • {o.bundle}</h3>

            {/* 🔥 UPDATED STATUS DISPLAY */}
            <p style={{ color: getColor(o.status), fontWeight: "bold" }}>
              {getStatusLabel(o.status)}
            </p>

            <p>GH₵ {o.price}</p>

            <p style={styles.phone}>
              {o.phone_number}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}

const styles = {
  container: {
    padding: "24px",
    minHeight: "auto",
  },

  title: {
    textAlign: "center",
    marginBottom: "24px",
    fontSize: "22px",
    fontWeight: "700",
    letterSpacing: "0.5px",
  },

  grid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
    gap: "16px",
  },

  card: {
    padding: "16px",
    borderRadius: "14px",
    background: "rgba(22,17,38, 0.85)",
    backdropFilter: "blur(14px)",
    WebkitBackdropFilter: "blur(14px)",
    boxShadow: "0 20px 50px rgba(0,0,0,0.35)",
    border: "1px solid rgba(255,255,255,0.06)",
    transition: "0.2s ease",
  },

  phone: {
    fontSize: "12px",
    color: "#b4acd0",
    marginTop: "6px",
  },

  info: {
    textAlign: "center",
    color: "#b4acd0",
    fontSize: "14px",
    marginTop: "20px",
  },

  error: {
    textAlign: "center",
    color: "#f87171",
    background: "rgba(127, 29, 29, 0.25)",
    padding: "10px",
    borderRadius: "10px",
    border: "1px solid rgba(255,255,255,0.06)",
    fontSize: "13px",
    maxWidth: "400px",
    margin: "0 auto",
  },
};
