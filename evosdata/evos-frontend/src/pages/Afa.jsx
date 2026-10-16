import { useEffect, useState } from "react";
import { getAfaInfo, createAfaRegistration, trackAfa } from "../api";
import AfaForm, { AFA_REGIONS, StatusPill, s } from "../components/AfaForm";

export default function Afa() {
  const [price, setPrice] = useState(null);
  const [regions, setRegions] = useState(AFA_REGIONS);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const [trackPhone, setTrackPhone] = useState("");
  const [trackBusy, setTrackBusy] = useState(false);
  const [trackErr, setTrackErr] = useState("");
  const [results, setResults] = useState(null);

  const user = JSON.parse(localStorage.getItem("user") || "{}");

  useEffect(() => {
    getAfaInfo().then((r) => {
      setPrice(Number(r.data?.price));
      if (Array.isArray(r.data?.regions)) setRegions(r.data.regions);
    }).catch(() => {});
  }, []);

  const pay = async (fields) => {
    setError("");
    setBusy(true);
    try {
      const res = await createAfaRegistration({ ...fields, user_id: user?.id || null });
      if (fields.email) localStorage.setItem("email", fields.email);
      const url = res.data?.payment_url;
      if (!url) throw new Error("no url");
      window.location.href = url;
    } catch (err) {
      setBusy(false);
      setError(err.response?.data?.detail || err.response?.data?.message || "Could not start payment. Try again.");
    }
  };

  const track = async () => {
    setTrackErr(""); setResults(null);
    if (!/^0\d{9}$/.test(trackPhone)) return setTrackErr("Enter a valid 10-digit phone number");
    setTrackBusy(true);
    try {
      const res = await trackAfa(trackPhone);
      setResults(res.data?.registrations || []);
    } catch (err) {
      setTrackErr(err.response?.data?.detail || "Couldn't fetch registrations right now");
    } finally {
      setTrackBusy(false);
    }
  };

  return (
    <div style={s.container}>
      <div style={s.header}>
        <div style={s.badge}>📝 AFA Registration</div>
        <h2 style={s.title}>Register an MTN AFA SIM</h2>
        <p style={s.subtitle}>MTN numbers only · Ghana Card required{price ? ` · GH₵ ${price.toFixed(2)}` : ""}</p>
      </div>

      <div style={s.wrapper}>
        <div style={s.box}>
          <AfaForm
            regions={regions}
            showEmail={!user?.id}
            busy={busy}
            error={error}
            onSubmit={pay}
            submitLabel={price ? `Pay GH₵ ${price.toFixed(2)} →` : "Continue to payment →"}
          />
        </div>

        <div style={s.box}>
          <p style={{ ...s.label, marginTop: 0 }}>Check a registration</p>
          <input style={s.input} type="tel" value={trackPhone} onChange={(e) => setTrackPhone(e.target.value)} placeholder="MTN number used for registration" />
          {trackErr && <div style={{ ...s.errorBanner, marginTop: 10 }}>{trackErr}</div>}
          <button style={s.ghost} onClick={track} disabled={trackBusy}>{trackBusy ? "Searching..." : "🔎 Find my registration"}</button>

          {results && results.length === 0 && <p style={{ ...s.small, textAlign: "center", marginTop: 14 }}>No registrations found for this number.</p>}
          {results && results.map((r) => (
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
      </div>
    </div>
  );
}
