import { useEffect, useState } from "react";
import { userApi } from "../lib/userApi";
import { Icon, WhatsAppIcon } from "../components/Icons";
import { openCommunity, SUPPORT_URL } from "../lib/community";

const STATUS = {
  successful: { c: "#3ddc97", icon: "✓", label: "Delivered" },
  delivered:  { c: "#3ddc97", icon: "✓", label: "Delivered" },
  processing: { c: "#a78bfa", icon: "…", label: "Processing" },
  paid:       { c: "#c8ff3e", icon: "●", label: "Paid" },
  failed:     { c: "#ff4d6a", icon: "✕", label: "Failed" },
};
const statusOf = (s) => STATUS[s] || { c: "#ffb020", icon: "◔", label: s || "Pending" };

const greeting = () => {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
};

export default function Dashboard({ setPage, user }) {
  const [supportOpen, setSupportOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState({ total_orders: 0, my_orders: 0, my_successful_orders: 0, transactions: [] });

  const isAgentActive = user?.role === "agent" && user?.agent_status === "approved";

  useEffect(() => { if (!user) setPage("login"); }, [user, setPage]);

  useEffect(() => {
    if (!user?.id) return;
    (async () => {
      try {
        const r = await userApi(user, `/today/${user.id}`);
        if (r.needsLogin) { setPage("login"); return; }
        const data = r.data;
        if (!r.ok || !data?.global) throw new Error("dashboard unavailable");
        setStats({
          total_orders: data.global.total_orders || 0,
          my_orders: data.user.my_orders || 0,
          my_successful_orders: data.user.my_successful_orders || 0,
          transactions: data.user.transactions || [],
        });
      } catch (error) {
        console.log("Dashboard error:", error);
      } finally {
        setLoading(false);
      }
    })();
  }, [user]);

  const handleAgentAccess = () => setPage(isAgentActive ? "agent-dashboard" : "become-agent");

  const rate = stats.my_orders ? Math.round((stats.my_successful_orders / stats.my_orders) * 100) : 0;
  const R = 34, C = 2 * Math.PI * R;

  const actions = [
    { icon: "bolt",   label: "Buy Data",     desc: "MTN · Telecel · AirtelTigo", go: () => setPage("shop"),      c: "#c8ff3e" },
    { icon: "box",    label: "My Orders",    desc: "Your full history",          go: () => setPage("orders"),    c: "#a78bfa" },
    { icon: "pin",    label: "Track Order",  desc: "Where's my data?",           go: () => setPage("eta-track"), c: "#ffb020" },
    { icon: isAgentActive ? "rocket" : "user", label: isAgentActive ? "Agent Hub" : "Become Agent", desc: isAgentActive ? "Store & earnings" : "Earn on every sale", go: handleAgentAccess, c: "#3ddc97" },
  ];

  return (
    <div className="db fade-in">
      <style>{css}</style>

      {/* HERO */}
      <section className="db-hero">
        <div className="db-orb" aria-hidden="true" />
        <div className="db-hero-in">
          <span className="db-live"><i /> System online</span>
          <p className="db-hi">{greeting()},</p>
          <h1 className="db-name">{user?.username || user?.email || "friend"}</h1>
          <div className="db-hero-btns">
            <button className="db-btn db-btn-lime" onClick={() => setPage("shop")}><Icon name="bolt" size={18} /> Buy data</button>
            <button className="db-btn db-btn-ghost" onClick={() => setPage("eta-track")}><Icon name="pin" size={18} /> Track</button>
          </div>
        </div>
      </section>

      {/* BENTO STATS */}
      <div className="db-h"><h2>Your overview</h2></div>
      {loading ? (
        <div className="db-skel-grid">{[0, 1, 2, 3].map((i) => <div key={i} className="db-skel" />)}</div>
      ) : (
        <div className="db-bento">
          <div className="db-tile db-tile-ring">
            <svg width="84" height="84" viewBox="0 0 84 84" aria-hidden="true">
              <circle cx="42" cy="42" r={R} fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="9" />
              <circle cx="42" cy="42" r={R} fill="none" stroke="url(#dbg)" strokeWidth="9" strokeLinecap="round"
                strokeDasharray={C} strokeDashoffset={C - (C * rate) / 100} transform="rotate(-90 42 42)" />
              <defs><linearGradient id="dbg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#c8ff3e" /><stop offset="1" stopColor="#ff4d8d" /></linearGradient></defs>
            </svg>
            <div>
              <div className="db-big">{rate}%</div>
              <div className="db-lbl">Success rate</div>
            </div>
          </div>
          <div className="db-tile"><div className="db-lbl">Global orders</div><div className="db-num" style={{ color: "#c8ff3e" }}>{stats.total_orders}</div></div>
          <div className="db-tile"><div className="db-lbl">My orders</div><div className="db-num" style={{ color: "#a78bfa" }}>{stats.my_orders}</div></div>
          <div className="db-tile"><div className="db-lbl">Successful</div><div className="db-num" style={{ color: "#3ddc97" }}>{stats.my_successful_orders}</div></div>
          <div className="db-tile"><div className="db-lbl">Transactions</div><div className="db-num" style={{ color: "#ffb020" }}>{stats.transactions.length}</div></div>
        </div>
      )}

      {/* QUICK ACTIONS */}
      <div className="db-h"><h2>Quick actions</h2></div>
      <div className="db-actions">
        {actions.map((a) => (
          <button key={a.label} className="db-act" onClick={a.go} style={{ "--c": a.c }}>
            <span className="db-act-ico"><Icon name={a.icon} size={22} /></span>
            <span className="db-act-t">{a.label}</span>
            <span className="db-act-d">{a.desc}</span>
            <span className="db-act-arrow">→</span>
          </button>
        ))}
      </div>

      {/* RECENT ORDERS */}
      {!loading && stats.transactions.length > 0 && (
        <>
          <div className="db-h"><h2>Recent orders</h2><button className="db-link" onClick={() => setPage("orders")}>See all →</button></div>
          <div className="db-list">
            {stats.transactions.slice(0, 5).map((tx, i) => {
              const st = statusOf(tx.status);
              return (
                <div key={i} className="db-row">
                  <div className="db-row-ico" style={{ color: st.c, background: st.c + "1f" }}>{st.icon}</div>
                  <div className="db-row-m">
                    <b>{tx.network} · {tx.amount?.split(" - ")[0]}</b>
                    <small>{tx.phone_number}</small>
                  </div>
                  <span className="db-chip" style={{ color: st.c, background: st.c + "1f", borderColor: st.c + "55" }}>{st.label}</span>
                </div>
              );
            })}
          </div>
        </>
      )}

      {/* HELP */}
      <div className="db-h"><h2>Need a hand?</h2></div>
      <div className="db-help">
        <a className="db-help-b" href={SUPPORT_URL} target="_blank" rel="noreferrer"><WhatsAppIcon size={20} /> WhatsApp support</a>
        <button className="db-help-b" onClick={openCommunity}><WhatsAppIcon size={20} /> Join community</button>
        <a className="db-help-b" href="mailto:support@evosdata.xyz"><Icon name="share" size={18} /> Email us</a>
      </div>

      <p className="db-foot">© 2026 Evoxera Technology · All rights reserved</p>

      {supportOpen && (
        <div className="db-modal" role="dialog" aria-modal="true">
          <div className="db-modal-s" onClick={() => setSupportOpen(false)} />
          <div className="db-modal-c">
            <h3>Become an agent</h3>
            <p>You need 20 successful orders to qualify. Message us and we'll get you onboarded.</p>
            <a className="db-btn db-btn-lime" href="https://wa.me/233537314125?text=Hi, I'd like to become an EVOS agent" target="_blank" rel="noreferrer">
              <WhatsAppIcon size={18} /> WhatsApp support
            </a>
            <button className="db-btn db-btn-ghost" onClick={() => setSupportOpen(false)}>Close</button>
          </div>
        </div>
      )}
    </div>
  );
}

const css = `
.db { padding: 14px 14px 8px; color: var(--text); }
.db-hero { position: relative; overflow: hidden; border-radius: 28px; padding: 26px 20px; border: 1px solid var(--line-strong);
  background: linear-gradient(135deg, rgba(200,255,62,0.16), rgba(139,92,246,0.22) 55%, rgba(255,77,141,0.18)); }
.db-orb { position: absolute; right: -50px; top: -50px; width: 220px; height: 220px; border-radius: 50%;
  background: conic-gradient(from 90deg, #c8ff3e, #8b5cf6, #ff4d8d, #c8ff3e); filter: blur(36px); opacity: .5; animation: dbSpin 14s linear infinite; }
@keyframes dbSpin { to { transform: rotate(360deg); } }
.db-hero-in { position: relative; }
.db-live { display: inline-flex; align-items: center; gap: 7px; padding: 5px 12px; border-radius: 999px; font-size: 11.5px; font-weight: 700; color: #3ddc97; background: rgba(61,220,151,0.12); border: 1px solid rgba(61,220,151,0.35); font-family: var(--font-mono); }
.db-live i { width: 7px; height: 7px; border-radius: 50%; background: #3ddc97; animation: dbPulse 1.8s ease-in-out infinite; }
@keyframes dbPulse { 50% { opacity: .3; } }
.db-hi { margin-top: 14px; font-size: 15px; color: var(--muted); }
.db-name { font-size: clamp(30px, 8vw, 46px); line-height: 1.05; font-weight: 800; margin: 2px 0 18px; overflow-wrap: anywhere;
  background: linear-gradient(90deg, #fff, #c8ff3e); -webkit-background-clip: text; background-clip: text; color: transparent; }
.db-hero-btns { display: flex; gap: 10px; flex-wrap: wrap; }
.db-btn { display: inline-flex; align-items: center; justify-content: center; gap: 8px; padding: 13px 20px; border-radius: 16px; border: 0; font-weight: 800; font-size: 14.5px; text-decoration: none; font-family: var(--font-display); }
.db-btn-lime { background: linear-gradient(135deg, #c8ff3e, #8fe600); color: #0a0814; box-shadow: 0 10px 28px rgba(200,255,62,0.3); }
.db-btn-ghost { background: rgba(255,255,255,0.08); color: var(--text); border: 1px solid var(--line); }
.db-h { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin: 26px 2px 12px; }
.db-h h2 { font-size: 13px; text-transform: uppercase; letter-spacing: .14em; color: var(--faint); font-weight: 800; }
.db-link { background: none; border: 0; color: var(--lime); font-size: 13px; font-weight: 700; }
.db-bento { display: grid; gap: 10px; grid-template-columns: repeat(2, minmax(0, 1fr)); }
.db-tile { padding: 16px; border-radius: 22px; background: var(--surface); border: 1px solid var(--line); min-width: 0; }
.db-tile-ring { grid-column: 1 / -1; display: flex; align-items: center; gap: 16px; background: linear-gradient(135deg, rgba(139,92,246,0.14), rgba(255,255,255,0.03)); }
.db-big { font-family: var(--font-display); font-size: 34px; font-weight: 800; line-height: 1; }
.db-lbl { font-size: 11.5px; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: .08em; }
.db-num { font-family: var(--font-display); font-size: 34px; font-weight: 800; margin-top: 8px; line-height: 1; }
.db-skel-grid { display: grid; gap: 10px; grid-template-columns: repeat(2, minmax(0, 1fr)); }
.db-skel { height: 92px; border-radius: 22px; background: linear-gradient(90deg, var(--surface), var(--surface-2), var(--surface)); background-size: 200% 100%; animation: dbSh 1.3s linear infinite; }
@keyframes dbSh { to { background-position: -200% 0; } }
.db-actions { display: grid; gap: 10px; grid-template-columns: repeat(2, minmax(0, 1fr)); }
.db-act { position: relative; text-align: left; padding: 16px; border-radius: 22px; border: 1px solid var(--line); background: var(--surface); color: var(--text); display: flex; flex-direction: column; gap: 4px; min-width: 0; overflow: hidden; }
.db-act::before { content: ""; position: absolute; inset: 0; background: radial-gradient(120% 90% at 0% 0%, color-mix(in srgb, var(--c) 22%, transparent), transparent 60%); pointer-events: none; }
.db-act-ico { position: relative; width: 42px; height: 42px; border-radius: 14px; display: grid; place-items: center; color: #0a0814; background: var(--c); margin-bottom: 8px; }
.db-act-t { position: relative; font-family: var(--font-display); font-weight: 800; font-size: 15.5px; }
.db-act-d { position: relative; font-size: 12px; color: var(--muted); line-height: 1.35; }
.db-act-arrow { position: absolute; right: 14px; top: 14px; color: var(--c); font-weight: 900; }
.db-list { display: grid; gap: 8px; }
.db-row { display: flex; align-items: center; gap: 12px; padding: 12px 14px; border-radius: 18px; background: var(--surface); border: 1px solid var(--line); min-width: 0; }
.db-row-ico { width: 40px; height: 40px; border-radius: 13px; display: grid; place-items: center; font-weight: 900; flex-shrink: 0; }
.db-row-m { flex: 1; min-width: 0; }
.db-row-m b { display: block; font-size: 14px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.db-row-m small { color: var(--muted); font-size: 12px; font-family: var(--font-mono); }
.db-chip { padding: 4px 10px; border-radius: 999px; border: 1px solid; font-size: 11px; font-weight: 800; text-transform: capitalize; flex-shrink: 0; }
.db-help { display: grid; gap: 8px; grid-template-columns: 1fr; }
.db-help-b { display: flex; align-items: center; gap: 10px; padding: 14px 16px; border-radius: 16px; border: 1px solid var(--line); background: var(--surface); color: var(--text); font-weight: 700; font-size: 14px; text-decoration: none; }
.db-help-b svg { color: #3ddc97; }
.db-foot { text-align: center; font-size: 11.5px; color: var(--faint); margin: 28px 0 6px; }
.db-modal { position: fixed; inset: 0; z-index: 10050; display: flex; align-items: center; justify-content: center; padding: 18px; }
.db-modal-s { position: absolute; inset: 0; background: rgba(5,3,12,0.72); backdrop-filter: blur(5px); }
.db-modal-c { position: relative; width: 100%; max-width: 380px; display: grid; gap: 12px; padding: 24px 20px; border-radius: 26px; background: linear-gradient(180deg,#1b1533,#110d1f); border: 1px solid var(--line-strong); }
.db-modal-c p { font-size: 14px; line-height: 1.5; }
@media (min-width: 640px) {
  .db { padding: 20px 22px 8px; }
  .db-hero { padding: 36px 32px; }
  .db-bento { grid-template-columns: repeat(4, minmax(0, 1fr)); }
  .db-tile-ring { grid-column: span 4; }
  .db-actions { grid-template-columns: repeat(4, minmax(0, 1fr)); }
  .db-help { grid-template-columns: repeat(3, 1fr); }
  .db-skel-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); }
}
`;
