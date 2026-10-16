import { useEffect, useState } from "react";
import { smartFetch } from "../config";
import AfaForm, { AFA_REGIONS, StatusPill, s } from "../components/AfaForm";

export default function AgentBuyAfa({ user, setPage }) {
  const [loading, setLoading] = useState(true);
  const [price, setPrice] = useState(0);
  const [regions, setRegions] = useState(AFA_REGIONS);
  const [wallet, setWallet] = useState(0);
  const [history, setHistory] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [ok, setOk] = useState("");
  const [formKey, setFormKey] = useState(0); // remount form to clear it after success

  useEffect(() => {
    if (!user) { setPage("login"); return; }
    if (user.role !== "agent" || user.agent_status !== "approved") setPage("dashboard");
  }, [user, setPage]);

  const headers = () => ({ "X-Agent-Token": sessionStorage.getItem("agentToken") });

  const load = async () => {
    try {
      const [info, dash, hist] = await Promise.all([
        smartFetch(`/agent/afa-info/${user.id}`, { headers: headers() }).then((r) => r.json()),
        smartFetch(`/agent/dashboard/${user.id}`, { headers: headers() }).then((r) => r.json()),
        smartFetch(`/agent/afa/${user.id}`, { headers: headers() }).then((r) => r.json()),
      ]);
      setPrice(Number(info.price || 0));
      if (Array.isArray(info.regions)) setRegions(info.regions);
      setWallet(Number(dash.wallet_balance || 0));
      setHistory(hist.registrations || []);
    } catch {
      setError("Failed to load. Please refresh.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { if (user?.id) load(); /* eslint-disable-next-line */ }, [user]);

  const hasFunds = wallet >= price;

  const submit = async (fields) => {
    setError(""); setOk("");
    setBusy(true);
    try {
      const { email, ...rest } = fields;
      const res = await smartFetch(`/agent/buy-afa`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...headers() },
        body: JSON.stringify({ agent_id: user.id, ...rest }),
      });
      const data = await res.json();
      if (typeof data.new_wallet_balance === "number") setWallet(data.new_wallet_balance);
      if (data.status === "success") {
        setOk(`✅ ${data.message}`);
        setFormKey((k) => k + 1);
        load();
      } else {
        setError(data.message || data.detail || "Registration failed. Please try again.");
      }
    } catch {
      setError("Network error. Please try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={s.container}>
      <div style={s.header}>
        <div style={s.badge}>📝 AFA Registration (Base Price)</div>
        <h2 style={s.title}>Register an AFA SIM for a Customer</h2>
        <p style={s.subtitle}>You pay GH₵ {price.toFixed(2)} per registration from your wallet</p>
      </div>

      <div style={s.wrapper}>
        <div style={s.box}>
          <div style={{ ...s.row, borderBottom: "none", paddingTop: 0 }}>
            <span style={{ color: "#b4acd0" }}>💳 Wallet Balance</span>
            <strong style={{ color: hasFunds ? "#22c55e" : "#f87171", fontSize: 16 }}>GH₵ {wallet.toFixed(2)}</strong>
          </div>
          {ok && <div style={s.successBanner}>{ok}</div>}
          {!loading && !hasFunds && <div style={s.errorBanner}>Insufficient wallet balance. Top up to continue.</div>}

          {loading ? <p style={{ ...s.small, textAlign: "center" }}>Loading...</p> : (
            <AfaForm
              key={formKey}
              regions={regions}
              busy={busy}
              disabled={!hasFunds}
              error={error}
              onSubmit={submit}
              submitLabel={`Register for GH₵ ${price.toFixed(2)} →`}
            />
          )}
          <button style={s.ghost} onClick={() => setPage("agent-dashboard")}>← Back to Dashboard</button>
        </div>

        {history.length > 0 && (
          <div style={s.box}>
            <p style={{ ...s.label, marginTop: 0 }}>Recent registrations</p>
            {history.map((r) => (
              <div key={r.evosdata_ref} style={s.row}>
                <div>
                  <div>{r.name}</div>
                  <div style={s.small}>{r.phone_number} · {new Date(r.created_at).toLocaleDateString()}</div>
                  {r.failure_reason && <div style={{ ...s.small, color: "#f87171" }}>{r.failure_reason}</div>}
                </div>
                <StatusPill status={r.status} />
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
