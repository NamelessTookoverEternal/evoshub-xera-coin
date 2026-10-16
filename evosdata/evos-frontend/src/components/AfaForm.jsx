import { useState } from "react";

export const AFA_REGIONS = [
  "Greater Accra", "Ashanti", "Western", "Western North", "Central", "Eastern",
  "Volta", "Oti", "Northern", "Savannah", "North East", "Upper East",
  "Upper West", "Bono", "Bono East", "Ahafo",
];

const MTN_PREFIXES = ["024", "025", "053", "054", "055", "059"];
const CARD_RE = /^GHA-\d{9}-\d$/;

export const STATUS_META = {
  pending_payment: { label: "Awaiting payment", color: "#fbbf24" },
  paid:            { label: "Submitting",        color: "#fbbf24" },
  failed:          { label: "Retrying",          color: "#fbbf24" },
  processing:      { label: "Processing",        color: "#60a5fa" },
  successful:      { label: "Registered",        color: "#22c55e" },
  rejected:        { label: "Rejected",          color: "#f87171" },
};

// Auto-shape what the user types into GHA-XXXXXXXXX-X
function formatCard(raw) {
  const d = raw.toUpperCase().replace(/[^A-Z0-9]/g, "");
  const digits = d.replace(/^GHA/, "").replace(/\D/g, "").slice(0, 10);
  if (!d) return "";
  let out = "GHA";
  if (digits.length || d.length > 3) out += "-" + digits.slice(0, 9);
  if (digits.length > 9) out += "-" + digits.slice(9, 10);
  return out;
}

export default function AfaForm({ regions = AFA_REGIONS, showEmail = false, submitLabel, busy, onSubmit, error, disabled }) {
  const [f, setF] = useState({
    name: "", phone: "", idNumber: "", occupation: "", location: "",
    region: "", dob: "", email: localStorage.getItem("email") || "",
  });
  const [agree, setAgree] = useState(false);
  const [localErr, setLocalErr] = useState("");
  const set = (k) => (e) => setF((p) => ({ ...p, [k]: e.target.value }));

  const submit = () => {
    setLocalErr("");
    const phone = f.phone.replace(/\s/g, "");
    if (f.name.trim().length < 3) return setLocalErr("Enter the full name exactly as on the Ghana Card");
    if (!/^0\d{9}$/.test(phone) || !MTN_PREFIXES.includes(phone.slice(0, 3))) return setLocalErr("Enter a valid MTN number (e.g. 0551234567)");
    if (!CARD_RE.test(f.idNumber)) return setLocalErr("Ghana Card must look like GHA-123456789-0");
    if (f.occupation.trim().length < 2) return setLocalErr("Enter an occupation");
    if (f.location.trim().length < 2) return setLocalErr("Enter the town / location");
    if (!f.region) return setLocalErr("Select a region");
    if (!f.dob) return setLocalErr("Enter the date of birth");
    const age = (Date.now() - new Date(f.dob).getTime()) / 31557600000;
    if (age < 18) return setLocalErr("Registrant must be 18 or older");
    if (showEmail && f.email && !/^\S+@\S+\.\S+$/.test(f.email)) return setLocalErr("Enter a valid email or leave it blank");
    if (!agree) return setLocalErr("Please confirm the details are correct");
    onSubmit({
      name: f.name.trim(), phone_number: phone, id_number: f.idNumber,
      occupation: f.occupation.trim(), location: f.location.trim(),
      region: f.region, date_of_birth: f.dob, email: f.email || undefined,
    });
  };

  const shown = localErr || error;

  return (
    <>
      {shown && <div style={s.errorBanner}>{shown}</div>}

      <p style={s.label}>Full name (as on Ghana Card)</p>
      <input style={s.input} value={f.name} onChange={set("name")} placeholder="e.g. Kwame Asante" autoComplete="name" />

      <p style={s.label}>MTN number to register</p>
      <input style={s.input} type="tel" value={f.phone} onChange={set("phone")} placeholder="e.g. 0551234567" inputMode="tel" />

      <p style={s.label}>Ghana Card number</p>
      <input
        style={s.input} value={f.idNumber} placeholder="GHA-123456789-0" autoCapitalize="characters"
        onChange={(e) => setF((p) => ({ ...p, idNumber: formatCard(e.target.value) }))}
      />

      <p style={s.label}>Date of birth</p>
      <input style={s.input} type="date" value={f.dob} onChange={set("dob")} max={new Date().toISOString().slice(0, 10)} />

      <p style={s.label}>Occupation</p>
      <input style={s.input} value={f.occupation} onChange={set("occupation")} placeholder="e.g. Trader" />

      <p style={s.label}>Town / location</p>
      <input style={s.input} value={f.location} onChange={set("location")} placeholder="e.g. Kumasi" />

      <p style={s.label}>Region</p>
      <select style={s.input} value={f.region} onChange={set("region")}>
        <option value="">Select region</option>
        {regions.map((r) => <option key={r} value={r}>{r}</option>)}
      </select>

      {showEmail && (
        <>
          <p style={s.label}>Email for payment receipt (optional)</p>
          <input style={s.input} type="email" value={f.email} onChange={set("email")} placeholder="you@example.com" />
        </>
      )}

      <label style={s.agree}>
        <input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} />
        <span>These details match the Ghana Card exactly. Wrong details can cause rejection.</span>
      </label>

      <button
        onClick={submit}
        disabled={busy || disabled}
        style={{ ...s.submit, opacity: busy || disabled ? 0.5 : 1, cursor: busy || disabled ? "not-allowed" : "pointer" }}
      >
        {busy ? "⏳ Processing..." : submitLabel}
      </button>
    </>
  );
}

export const s = {
  container: { padding: "28px 18px 80px", fontFamily: "'Nunito', 'Poppins', ui-rounded, system-ui, Arial", color: "#241c3d" },
  header: { textAlign: "center", marginBottom: 20 },
  badge: { display: "inline-block", padding: "5px 18px", borderRadius: 50, background: "linear-gradient(135deg, #fef9c3, #fde68a)", border: "1px solid #facc15", color: "#854d0e", fontSize: 12, fontWeight: 800, marginBottom: 10, letterSpacing: "0.5px" },
  title: { fontSize: 24, fontWeight: 900, color: "#f3f0fb", margin: "0 0 6px", letterSpacing: "-0.5px" },
  subtitle: { fontSize: 13, color: "#9189b5", margin: 0, fontWeight: 600 },
  wrapper: { maxWidth: 480, margin: "0 auto" },
  box: { background: "rgba(22,17,38,0.85)", backdropFilter: "blur(20px)", WebkitBackdropFilter: "blur(20px)", padding: "24px 20px", borderRadius: 24, border: "1px solid rgba(255,255,255,0.07)", boxShadow: "0 8px 40px rgba(0,0,0,0.3)", marginBottom: 16 },
  label: { fontSize: 11, color: "#facc15", fontWeight: 800, textTransform: "uppercase", letterSpacing: "1px", margin: "16px 0 8px" },
  input: { width: "100%", padding: "12px 14px", borderRadius: 12, background: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.12)", color: "#f3f0fb", fontSize: 14, fontWeight: 700, boxSizing: "border-box", outline: "none", colorScheme: "dark" },
  agree: { display: "flex", gap: 10, alignItems: "flex-start", margin: "18px 0 0", fontSize: 12, color: "#b4acd0", fontWeight: 600, lineHeight: 1.5 },
  submit: { width: "100%", padding: 15, borderRadius: 16, border: "none", color: "#1a1300", fontWeight: 900, fontSize: 15, marginTop: 16, background: "linear-gradient(135deg, #facc15, #eab308)", boxShadow: "0 6px 24px rgba(250,204,21,0.25)" },
  errorBanner: { background: "rgba(239,68,68,0.12)", border: "1px solid rgba(239,68,68,0.35)", color: "#f87171", borderRadius: 12, padding: "10px 14px", fontSize: 13, fontWeight: 700, marginBottom: 6 },
  successBanner: { background: "rgba(34,197,94,0.12)", border: "1px solid rgba(34,197,94,0.35)", color: "#22c55e", borderRadius: 12, padding: "10px 14px", fontSize: 13, fontWeight: 700, marginBottom: 14 },
  row: { display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, padding: "12px 0", borderBottom: "1px solid rgba(255,255,255,0.06)", fontSize: 13, color: "#d9d4ec", fontWeight: 700 },
  small: { fontSize: 11, color: "#9189b5", fontWeight: 600 },
  ghost: { width: "100%", padding: 12, borderRadius: 14, background: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.1)", color: "#b4acd0", fontWeight: 700, fontSize: 13, cursor: "pointer", marginTop: 12 },
};

export function StatusPill({ status }) {
  const m = STATUS_META[status] || { label: status, color: "#9189b5" };
  return <span style={{ color: m.color, fontWeight: 900, fontSize: 12 }}>● {m.label}</span>;
}
