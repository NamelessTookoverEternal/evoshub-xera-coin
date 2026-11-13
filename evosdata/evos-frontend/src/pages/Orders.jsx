import { useEffect, useState } from "react";
import { getOrders } from "../api";

export default function Orders({ user } = {}) {
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // The signed-in account: prefer the app's user, fall back to what login saved (some sign-in paths only save the user object).
  const userId = (() => {
    try {
      return user?.id || localStorage.getItem("user_id") || JSON.parse(localStorage.getItem("user") || "{}")?.id || null;
    } catch { return user?.id || null; }
  })();

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

    if (status === "processing" || status === "paid")
      return "On its way";

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
        // newest first, whatever order the server returns
        setOrders([...res.data.orders].sort((a, b) => new Date(b.created_at) - new Date(a.created_at)));
      } else {
        setOrders([]);
      }
    } catch (err) {
      console.error(err);
      setError(err?.response?.status === 403
        ? "Your session expired. Please sign in again to see your orders."
        : "Couldn't load your orders. Retrying...");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadOrders();

    const interval = setInterval(loadOrders, 15000);

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

            {o.status === "successful" && o.delivered_at ? (
              <p style={styles.meta}>✅ Delivered {fmt(o.delivered_at)}</p>
            ) : (o.status === "processing" || o.status === "paid") && o.eta_text ? (
              <p style={styles.meta}>⏱ {o.eta_text}</p>
            ) : null}

            <p>GH₵ {o.price}</p>

            <p style={styles.phone}>
              {o.phone_number}
            </p>
            <p style={styles.meta}>Placed {fmt(o.created_at)}</p>
            {(o.evosdata_ref || o.paystack_ref) && (
              <p style={{ ...styles.meta, wordBreak: "break-all" }}>Ref: {o.evosdata_ref || o.paystack_ref}</p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

const fmt = (d) => {
  if (!d) return "";
  const x = new Date(d);
  return isNaN(x) ? "" : x.toLocaleString("en-GH", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
};

const styles = {
  meta: { fontSize: 12, opacity: 0.75, margin: "4px 0" },
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
    background: "rgba(22,30,41, 0.85)",
    backdropFilter: "blur(14px)",
    WebkitBackdropFilter: "blur(14px)",
    boxShadow: "0 20px 50px rgba(0,0,0,0.35)",
    border: "1px solid rgba(255,255,255,0.06)",
    transition: "0.2s ease",
  },

  phone: {
    fontSize: "12px",
    color: "#b3bece",
    marginTop: "6px",
  },

  info: {
    textAlign: "center",
    color: "#b3bece",
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
