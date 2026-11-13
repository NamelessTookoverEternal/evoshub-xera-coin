import { useEffect, useState } from "react";
import { userApi, errorText } from "../lib/userApi";

const QUICK = [10, 20, 50, 100, 200, 500];

// Load money into the customer wallet. No fee on top: you pay what you load.
export default function WalletTopUp({ user, setPage }) {
  const [amount, setAmount] = useState("");
  const [balance, setBalance] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => { if (!user) setPage("login"); }, [user, setPage]);
  useEffect(() => {
    if (!user?.id) return;
    (async () => {
      const r = await userApi(user, `/wallet/me?user_id=${user.id}`);
      if (r.needsLogin) { setPage("login"); return; }
      if (r.ok) setBalance(Number(r.data.balance));
    })();
  }, [user, setPage]);

  const n = parseFloat(amount) || 0;
  const valid = n >= 1 && n <= 5000;

  const go = async () => {
    if (!valid || busy) return;
    setBusy(true); setError("");
    const r = await userApi(user, "/wallet/deposit/initiate", { method: "POST", body: { user_id: user.id, amount: n } });
    if (r.needsLogin) { setPage("login"); return; }
    if (!r.ok || !r.data?.payment_url) {
      setBusy(false);
      setError(errorText(r, "Could not start the payment. Try again."));
      return;
    }
    window.location.href = r.data.payment_url;
  };

  return (
    <div style={{ maxWidth: 460, margin: "0 auto", padding: "8px 4px" }}>
      <button style={{ background: "none", border: "none", color: "inherit", opacity: 0.7, cursor: "pointer", marginBottom: 8 }}
        onClick={() => setPage("dashboard")}>← Back</button>
      <h2 style={{ margin: "0 0 4px" }}>Top up wallet</h2>
      <p style={{ opacity: 0.7, fontSize: 13, margin: "0 0 14px" }}>
        {balance === null ? "…" : `Balance: GH₵ ${balance.toFixed(2)}`} · Wallet orders are cheaper than paying directly. No top-up fee.
      </p>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 8, marginBottom: 12 }}>
        {QUICK.map((q) => (
          <button key={q} onClick={() => setAmount(String(q))}
            style={{ padding: "12px 0", borderRadius: 12, fontWeight: 800, cursor: "pointer", color: "inherit",
                     border: n === q ? "2px solid #22c55e" : "1px solid rgba(255,255,255,0.14)", background: "rgba(255,255,255,0.04)" }}>
            GH₵ {q}
          </button>
        ))}
      </div>

      <input type="number" inputMode="decimal" min="1" max="5000" placeholder="Or enter an amount (GH₵ 1 – 5000)"
        value={amount} onChange={(e) => setAmount(e.target.value)}
        style={{ width: "100%", boxSizing: "border-box", padding: 14, borderRadius: 12, fontSize: 16, marginBottom: 12,
                 border: "1px solid rgba(255,255,255,0.14)", background: "rgba(255,255,255,0.04)", color: "inherit" }} />

      {valid && (
        <p style={{ fontSize: 13, opacity: 0.8, margin: "0 0 12px" }}>
          You pay <b>GH₵ {n.toFixed(2)}</b> and the wallet gets <b>GH₵ {n.toFixed(2)}</b>.
        </p>
      )}
      {error && <p style={{ color: "#ff4d6a", fontSize: 13 }}>{error}</p>}

      <button onClick={go} disabled={!valid || busy}
        style={{ width: "100%", padding: 15, borderRadius: 14, border: "none", fontWeight: 900, fontSize: 15, color: "#fff",
                 background: "linear-gradient(135deg,#22c55e,#16a34a)", opacity: !valid || busy ? 0.5 : 1, cursor: valid && !busy ? "pointer" : "not-allowed" }}>
        {busy ? "⏳ Opening Paystack…" : valid ? `💳 Pay GH₵ ${n.toFixed(2)} via Paystack` : "Enter an amount"}
      </button>
      <p style={{ textAlign: "center", fontSize: 12, opacity: 0.55, marginTop: 10 }}>
        Deposit only: wallet money can be spent on data but cannot be withdrawn.
      </p>
    </div>
  );
}
