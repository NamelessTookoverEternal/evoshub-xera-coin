import { useEffect, useMemo, useRef, useState } from "react";
import { userApi, errorText } from "../lib/userApi";

// Wheel: 1GB, Try again, 2GB, Try again ... 10GB, Try again (the server sends the same 20 labels).
const FALLBACK_SEGMENTS = Array.from({ length: 20 }, (_, i) => (i % 2 === 0 ? `${i / 2 + 1}GB` : "Try again"));
const PRIZE_COLORS = ["#c8ff3e", "#a3f03a", "#7be85a", "#3ddc97", "#22d3b6", "#38bdf8", "#818cf8", "#a78bfa", "#e879f9", "#ff4d8d"];
const NETWORK_LABEL = { MTN: "MTN", AIRTELTIGO: "AirtelTigo", TELECEL: "Telecel / Vodafone" };
const NETWORK_COLOR = { MTN: "#ffcc00", AIRTELTIGO: "#8b5cf6", TELECEL: "#ef4444" };
const SPIN_MS = 5200;

const polar = (cx, cy, r, deg) => {
  const a = ((deg - 90) * Math.PI) / 180;
  return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
};

function countdown(iso, now) {
  const ms = Math.max(0, new Date(iso).getTime() - now);
  const h = Math.floor(ms / 3600000), m = Math.floor((ms % 3600000) / 60000), s = Math.floor((ms % 60000) / 1000);
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

export function Confetti() {
  const bits = useMemo(() => Array.from({ length: 70 }, (_, i) => ({
    left: Math.random() * 100,
    delay: Math.random() * 0.8,
    dur: 2.2 + Math.random() * 2,
    size: 6 + Math.random() * 8,
    color: ["#c8ff3e", "#ff4d8d", "#a78bfa", "#3ddc97", "#ffb020", "#38bdf8"][i % 6],
    rot: Math.random() * 360,
  })), []);
  return (
    <div style={{ position: "fixed", inset: 0, pointerEvents: "none", zIndex: 1200, overflow: "hidden" }} aria-hidden="true">
      <style>{`@keyframes spin-fall{0%{transform:translateY(-12vh) rotate(0deg);opacity:1}100%{transform:translateY(112vh) rotate(720deg);opacity:.9}}`}</style>
      {bits.map((b, i) => (
        <span key={i} style={{
          position: "absolute", top: 0, left: `${b.left}%`, width: b.size, height: b.size * 0.5,
          background: b.color, borderRadius: 2, transform: `rotate(${b.rot}deg)`,
          animation: `spin-fall ${b.dur}s ${b.delay}s ease-in forwards`,
        }} />
      ))}
    </div>
  );
}

export default function SpinWheel({ user, setPage }) {
  const [loading, setLoading] = useState(true);
  const [segments, setSegments] = useState(FALLBACK_SEGMENTS);
  const [canSpin, setCanSpin] = useState(false);
  const [nextReset, setNextReset] = useState(null);
  const [spinning, setSpinning] = useState(false);
  const [rotation, setRotation] = useState(0);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [now, setNow] = useState(Date.now());
  const [prize, setPrize] = useState(null);      // { spin_id, prize_gb, networks } while a win is waiting to be claimed
  const [showClaim, setShowClaim] = useState(false);
  const [claimed, setClaimed] = useState(null);  // result of a successful claim
  const [confetti, setConfetti] = useState(false);
  const rotRef = useRef(0);

  const n = segments.length;
  const slice = 360 / n;

  useEffect(() => { if (!user) setPage("login"); }, [user, setPage]);
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t); }, []);

  const load = async () => {
    const r = await userApi(user, `/spin/status?user_id=${user.id}`);
    if (r.needsLogin) { setError("Please sign out and sign in again to use Spin to Win."); setLoading(false); return; }
    if (!r.ok) { setError(errorText(r, "Could not load the wheel.")); setLoading(false); return; }
    setSegments(r.data.segments?.length ? r.data.segments : FALLBACK_SEGMENTS);
    setCanSpin(!!r.data.can_spin);
    setNextReset(r.data.next_reset_at);
    if (r.data.pending_prize) setPrize(r.data.pending_prize);
    setLoading(false);
  };
  useEffect(() => { if (user?.id) load(); /* eslint-disable-next-line */ }, [user?.id]);

  // When the countdown hits zero the day has rolled over: refresh so the wheel unlocks.
  useEffect(() => {
    if (nextReset && !canSpin && now >= new Date(nextReset).getTime() + 1500 && !spinning) { load(); }
    // eslint-disable-next-line
  }, [now]);

  const spin = async () => {
    if (spinning || !canSpin) return;
    setError(""); setNotice(""); setClaimed(null);
    setSpinning(true);
    const r = await userApi(user, "/spin", { method: "POST", body: { user_id: user.id } });
    if (r.needsLogin) { setSpinning(false); setError("Please sign out and sign in again to use Spin to Win."); return; }
    if (!r.ok) { setSpinning(false); setError(errorText(r)); return; }
    if (r.data.status === "already_spun") {
      setSpinning(false); setCanSpin(false); setNextReset(r.data.next_reset_at);
      if (r.data.pending_prize) setPrize(r.data.pending_prize);
      setNotice("You have already used today's spin.");
      return;
    }

    // Land the pointer (top of the wheel) on the centre of the server's segment, with a little jitter.
    const idx = r.data.segment_index;
    const jitter = (Math.random() - 0.5) * slice * 0.6;
    const target = -((idx + 0.5) * slice) + jitter;
    const current = rotRef.current;
    const delta = ((target - (current % 360)) % 360 + 360) % 360;
    const next = current + 360 * 6 + delta;
    rotRef.current = next;
    setRotation(next);

    setTimeout(() => {
      setSpinning(false);
      setCanSpin(false);
      setNextReset(r.data.next_reset_at);
      if (r.data.won) {
        setPrize({ spin_id: r.data.spin_id, prize_gb: r.data.prize_gb, networks: r.data.networks });
        setConfetti(true);
        setShowClaim(true);
        setTimeout(() => setConfetti(false), 5200);
      } else {
        setNotice("Not this time. Come back tomorrow for another spin!");
      }
    }, SPIN_MS + 150);
  };

  const wheel = useMemo(() => {
    const R = 150, C = 160;
    return segments.map((label, i) => {
      const a0 = i * slice, a1 = (i + 1) * slice;
      const [x0, y0] = polar(C, C, R, a0), [x1, y1] = polar(C, C, R, a1);
      const isPrize = label !== "Try again";
      const gb = isPrize ? parseInt(label, 10) : 0;
      const fill = isPrize ? PRIZE_COLORS[Math.min(gb, 10) - 1] : (i % 4 === 1 ? "#1d1733" : "#27204a");
      const [tx, ty] = polar(C, C, R * 0.68, a0 + slice / 2);
      return (
        <g key={i}>
          <path d={`M${C} ${C} L${x0} ${y0} A${R} ${R} 0 0 1 ${x1} ${y1} Z`} fill={fill} stroke="rgba(0,0,0,0.35)" strokeWidth="1" />
          <text x={tx} y={ty} transform={`rotate(${a0 + slice / 2 - 90 + ((a0 + slice / 2) % 360 > 180 ? 180 : 0)} ${tx} ${ty})`} textAnchor="middle" dominantBaseline="middle"
            fontSize={isPrize ? 15 : 9} fontWeight="900" fill={isPrize ? "#0b0818" : "#b4acd0"}>
            {isPrize ? label : "Try again"}
          </text>
        </g>
      );
    });
  }, [segments, slice]);

  if (!user) return null;

  return (
    <div style={s.page}>
      {confetti && <Confetti />}

      <div style={s.head}>
        <h1 style={s.title}>🎡 Spin to Win</h1>
        <p style={s.sub}>One free spin every day. Win free data from 1GB up to 10GB.</p>
      </div>

      <div style={s.wheelWrap}>
        <div style={s.pointer} aria-hidden="true" />
        <svg viewBox="0 0 320 320" style={{
          ...s.wheel, transform: `rotate(${rotation}deg)`,
          transition: spinning ? `transform ${SPIN_MS}ms cubic-bezier(0.12, 0.7, 0.1, 1)` : "none",
        }} role="img" aria-label="Prize wheel">
          <circle cx="160" cy="160" r="156" fill="#0b0818" stroke="#c8ff3e" strokeWidth="3" />
          {wheel}
          <circle cx="160" cy="160" r="22" fill="#0b0818" stroke="#c8ff3e" strokeWidth="3" />
        </svg>
      </div>

      {loading ? (
        <p style={s.muted}>Loading…</p>
      ) : (
        <>
          {canSpin ? (
            <button style={{ ...s.spinBtn, opacity: spinning ? 0.6 : 1 }} disabled={spinning} onClick={spin}>
              {spinning ? "Spinning…" : "SPIN NOW"}
            </button>
          ) : (
            <div style={s.waitBox}>
              <div style={s.waitLabel}>Next spin in</div>
              <div style={s.waitTime}>{nextReset ? countdown(nextReset, now) : "--:--:--"}</div>
              <div style={s.waitSub}>Resets every day at midnight (Ghana time)</div>
            </div>
          )}

          {notice && <div style={s.notice}>{notice}</div>}
          {error && <div style={s.error}>{error}</div>}

          {prize && !showClaim && !claimed && (
            <div style={s.prizeBar}>
              <div>🎁 You won <b>{prize.prize_gb}GB</b> and haven't claimed it yet.</div>
              <button style={s.claimBtn} onClick={() => setShowClaim(true)}>Claim now</button>
            </div>
          )}
          {claimed && (
            <div style={s.claimedBox}>
              ✅ <b>{claimed.prize_gb}GB</b> is on its way to <b>{claimed.phone}</b> ({NETWORK_LABEL[claimed.network]}).
              {claimed.delivery === "queued" && <div style={{ marginTop: 6, fontSize: 12, color: "#b4acd0" }}>It is queued and will be delivered shortly.</div>}
              <div><button style={s.linkBtn} onClick={() => setPage("orders")}>Track it in My Orders →</button></div>
            </div>
          )}

          <div style={s.rules}>
            <div style={s.ruleTitle}>How it works</div>
            <ul style={s.ruleList}>
              <li>One spin per account every day.</li>
              <li>Win a prize, then enter the number and network to receive it.</li>
              <li>Telecel / Vodafone data starts at 10GB, so that network only opens when you win 10GB.</li>
            </ul>
          </div>
        </>
      )}

      {showClaim && prize && (
        <ClaimModal
          user={user}
          prize={prize}
          onClose={() => setShowClaim(false)}
          onDone={(res) => { setClaimed(res); setPrize(null); setShowClaim(false); }}
        />
      )}
    </div>
  );
}

function ClaimModal({ user, prize, onClose, onDone }) {
  const [phone, setPhone] = useState("");
  const [network, setNetwork] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const nets = prize.networks || {};
  const valid = /^\d{9,15}$/.test(phone.replace(/[\s\-()]/g, "")) && network;

  const submit = async () => {
    if (!valid || busy) return;
    setBusy(true); setErr("");
    const r = await userApi(user, "/spin/claim", {
      method: "POST",
      body: { user_id: user.id, spin_id: prize.spin_id, phone: phone.replace(/[\s\-()]/g, ""), network },
    });
    setBusy(false);
    if (r.ok && r.data.status === "claimed") { onDone(r.data); return; }
    setErr(errorText(r));
  };

  return (
    <div style={s.scrim} role="dialog" aria-modal="true" aria-label="Claim your prize">
      <div style={s.modal}>
        <div style={{ fontSize: 54, textAlign: "center" }}>🎉</div>
        <h2 style={s.mTitle}>You won {prize.prize_gb}GB!</h2>
        <p style={s.mSub}>Enter the number that should receive it and choose its network.</p>

        <label style={s.label}>Phone number</label>
        <input style={s.input} inputMode="tel" placeholder="e.g. 0241234567" value={phone}
          onChange={(e) => setPhone(e.target.value)} autoFocus />

        <label style={s.label}>Network</label>
        <div style={s.netRow}>
          {["MTN", "AIRTELTIGO", "TELECEL"].map((k) => {
            const info = nets[k] || { available: k !== "TELECEL" };
            const on = network === k;
            return (
              <button key={k} disabled={!info.available} onClick={() => setNetwork(k)}
                style={{
                  ...s.netBtn,
                  borderColor: on ? NETWORK_COLOR[k] : "rgba(255,255,255,0.1)",
                  background: on ? `${NETWORK_COLOR[k]}22` : "rgba(255,255,255,0.04)",
                  opacity: info.available ? 1 : 0.35,
                  cursor: info.available ? "pointer" : "not-allowed",
                  filter: info.available ? "none" : "grayscale(1)",
                }}>
                <span style={{ fontWeight: 800 }}>{NETWORK_LABEL[k]}</span>
                {!info.available && <span style={{ fontSize: 10, color: "#9189b5" }}>{info.reason}</span>}
              </button>
            );
          })}
        </div>

        {err && <div style={s.error}>{err}</div>}

        <button style={{ ...s.spinBtn, marginTop: 14, opacity: valid && !busy ? 1 : 0.5 }} disabled={!valid || busy} onClick={submit}>
          {busy ? "Sending…" : `Send my ${prize.prize_gb}GB`}
        </button>
        <button style={s.later} onClick={onClose}>I'll claim later</button>
      </div>
    </div>
  );
}

const s = {
  page: { maxWidth: 480, margin: "0 auto", padding: "22px 16px 70px", color: "#e5e7eb", textAlign: "center" },
  head: { marginBottom: 10 },
  title: { fontSize: 28, fontWeight: 900, margin: "0 0 6px", color: "#f3f0fb" },
  sub: { fontSize: 14, color: "#9189b5", margin: 0 },
  wheelWrap: { position: "relative", width: "min(86vw, 340px)", margin: "26px auto 22px" },
  wheel: { width: "100%", height: "auto", display: "block", filter: "drop-shadow(0 12px 36px rgba(200,255,62,0.18))" },
  pointer: {
    position: "absolute", top: -12, left: "50%", marginLeft: -14, zIndex: 3, width: 0, height: 0,
    borderLeft: "14px solid transparent", borderRight: "14px solid transparent", borderTop: "30px solid #ff4d8d",
    filter: "drop-shadow(0 3px 4px rgba(0,0,0,0.5))",
  },
  spinBtn: {
    width: "100%", maxWidth: 340, padding: "16px", borderRadius: 16, border: "none", cursor: "pointer",
    background: "linear-gradient(135deg,#c8ff3e,#8fe600)", color: "#000", fontWeight: 900, fontSize: 17, letterSpacing: "0.06em",
    boxShadow: "0 8px 28px rgba(200,255,62,0.3)",
  },
  waitBox: { maxWidth: 340, margin: "0 auto", padding: "16px", borderRadius: 16, background: "rgba(22,17,38,0.9)", border: "1px solid rgba(255,255,255,0.08)" },
  waitLabel: { fontSize: 12, color: "#9189b5", textTransform: "uppercase", letterSpacing: "0.08em" },
  waitTime: { fontSize: 34, fontWeight: 900, color: "#c8ff3e", fontVariantNumeric: "tabular-nums", margin: "4px 0" },
  waitSub: { fontSize: 12, color: "#7a6fa3" },
  muted: { color: "#9189b5" },
  notice: { maxWidth: 340, margin: "14px auto 0", padding: "12px 14px", borderRadius: 12, background: "rgba(167,139,250,0.12)", border: "1px solid rgba(167,139,250,0.3)", color: "#d8ccff", fontSize: 14 },
  error: { maxWidth: 340, margin: "14px auto 0", padding: "12px 14px", borderRadius: 12, background: "rgba(239,68,68,0.12)", border: "1px solid rgba(239,68,68,0.35)", color: "#f87171", fontSize: 13 },
  prizeBar: { maxWidth: 340, margin: "14px auto 0", padding: "14px", borderRadius: 14, background: "rgba(200,255,62,0.1)", border: "1px solid rgba(200,255,62,0.35)", fontSize: 14, display: "grid", gap: 10 },
  claimBtn: { padding: "11px", borderRadius: 12, border: "none", background: "#c8ff3e", color: "#000", fontWeight: 900, cursor: "pointer" },
  claimedBox: { maxWidth: 340, margin: "14px auto 0", padding: "14px", borderRadius: 14, background: "rgba(34,197,94,0.12)", border: "1px solid rgba(34,197,94,0.35)", fontSize: 14, lineHeight: 1.5 },
  linkBtn: { marginTop: 8, background: "none", border: "none", color: "#c8ff3e", fontWeight: 700, cursor: "pointer", fontSize: 13 },
  rules: { maxWidth: 340, margin: "24px auto 0", textAlign: "left", padding: "14px 16px", borderRadius: 14, background: "rgba(22,17,38,0.7)", border: "1px solid rgba(255,255,255,0.06)" },
  ruleTitle: { fontWeight: 800, fontSize: 13, color: "#f3f0fb", marginBottom: 6 },
  ruleList: { margin: 0, paddingLeft: 18, fontSize: 12.5, color: "#9189b5", lineHeight: 1.65 },
  scrim: { position: "fixed", inset: 0, zIndex: 1100, background: "rgba(5,3,12,0.82)", backdropFilter: "blur(6px)", display: "flex", alignItems: "center", justifyContent: "center", padding: 16, overflowY: "auto" },
  modal: { width: "100%", maxWidth: 380, background: "rgba(22,17,38,0.98)", border: "1px solid rgba(200,255,62,0.35)", borderRadius: 24, padding: "24px 20px", boxShadow: "0 30px 80px rgba(0,0,0,0.6)", textAlign: "left", position: "relative", zIndex: 1250 },
  mTitle: { margin: "4px 0 6px", textAlign: "center", fontSize: 26, fontWeight: 900, color: "#c8ff3e" },
  mSub: { textAlign: "center", color: "#b4acd0", fontSize: 14, margin: "0 0 16px" },
  label: { display: "block", fontSize: 12, color: "#b4acd0", textTransform: "uppercase", letterSpacing: "0.04em", margin: "12px 0 6px" },
  input: { width: "100%", boxSizing: "border-box", padding: "13px 14px", borderRadius: 12, border: "1px solid rgba(255,255,255,0.1)", background: "rgba(10,8,20,0.7)", color: "#e5e7eb", fontSize: 16, outline: "none" },
  netRow: { display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 8 },
  netBtn: { display: "grid", gap: 2, justifyItems: "center", padding: "12px 4px", borderRadius: 12, border: "2px solid", color: "#e5e7eb", fontSize: 12, textAlign: "center" },
  later: { width: "100%", marginTop: 8, background: "none", border: "none", color: "#9189b5", cursor: "pointer", fontSize: 13, padding: 8 },
};
