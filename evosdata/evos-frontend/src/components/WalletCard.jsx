import { useEffect, useState } from "react";
import { userApi } from "../lib/userApi";

// Customer wallet card for the dashboard: balance, top up, last few movements.
// Deposit-only: there is no withdraw button here. Agents get the same card (their agent wallet is separate).
export default function WalletCard({ user, setPage }) {
  const [w, setW] = useState(null);

  useEffect(() => {
    if (!user?.id) return;
    let off = false;
    (async () => {
      const r = await userApi(user, `/wallet/me?user_id=${user.id}`);
      if (!off && r.ok && r.data?.status === "ok") setW(r.data);
    })();
    return () => { off = true; };
  }, [user]);

  if (!w) return null;
  const txs = (w.transactions || []).slice(0, 4);

  return (
    <section style={st.card}>
      <div style={st.top}>
        <div>
          <div style={st.lbl}>👛 My wallet</div>
          <div style={st.bal}>GH₵ {Number(w.balance).toFixed(2)}</div>
        </div>
        <button style={st.btn} onClick={() => setPage("wallet-topup")}>+ Top up</button>
      </div>
      <p style={st.hint}>
        Pay from your wallet at checkout for a cheaper price. Top-ups are free of charge. The wallet is for buying only, so it can't be withdrawn.
        {w.is_agent && " This is your customer wallet; your agent wallet is separate."}
      </p>
      {txs.length > 0 && (
        <div style={st.list}>
          {txs.map((t, i) => (
            <div key={i} style={st.row}>
              <span>{t.label}</span>
              <b style={{ color: t.type === "credit" ? "#3ddc97" : "#ffb020" }}>
                {t.type === "credit" ? "+" : "−"}GH₵ {Number(t.amount).toFixed(2)}
              </b>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

const st = {
  card: { margin: "0 0 18px", padding: 16, borderRadius: 16, border: "1px solid rgba(255,255,255,0.1)", background: "rgba(255,255,255,0.04)" },
  top: { display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 },
  lbl: { fontSize: 12, opacity: 0.7, fontWeight: 700 },
  bal: { fontSize: 28, fontWeight: 900, color: "#ffb020" },
  btn: { background: "linear-gradient(135deg,#22c55e,#16a34a)", color: "#fff", border: "none", borderRadius: 12, padding: "11px 18px", fontWeight: 800, cursor: "pointer" },
  hint: { fontSize: 12, opacity: 0.65, margin: "10px 0 0", lineHeight: 1.5 },
  list: { marginTop: 12, borderTop: "1px solid rgba(255,255,255,0.08)", paddingTop: 8 },
  row: { display: "flex", justifyContent: "space-between", fontSize: 13, padding: "5px 0" },
};
