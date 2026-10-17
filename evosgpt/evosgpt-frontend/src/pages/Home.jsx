import { EVOSDATA_URL, openProduct } from "../config";
import { useCurrency } from "../lib/currency";

export default function Home({ setPage, user }) {
  const { format, note } = useCurrency();
  return (
    <div style={{ fontFamily: "Inter,sans-serif", background: "#070d1a", minHeight: "100vh", color: "#e2e8f0" }}>
      <style>{`
        @media (max-width: 600px) {
          .hero-btns { flex-direction: column !important; align-items: stretch !important; }
          .hero-btns button { max-width: 100% !important; }
          .stats-row { gap: 8px !important; }
          .stats-row > div { flex: 1 1 calc(50% - 8px) !important; min-width: 0 !important; }
          .who-grid { grid-template-columns: repeat(2, 1fr) !important; }
          .output-grid { grid-template-columns: 1fr !important; }
          .memory-grid { grid-template-columns: 1fr !important; gap: 20px !important; }
          .pricing-grid { grid-template-columns: 1fr !important; }
          .crossell-box { flex-direction: column !important; }
          .footer-inner { flex-direction: column !important; gap: 12px !important; }
          .footer-links { gap: 14px !important; }
          .nav-inner { padding: 12px 16px !important; }
          .hero-section { padding: 44px 16px 36px !important; }
          .section-pad { padding-left: 16px !important; padding-right: 16px !important; }
          .memory-pad { padding: 24px 18px !important; }
          .pricing-card { padding: 22px 16px !important; }
        }
        @media (min-width: 601px) and (max-width: 900px) {
          .who-grid { grid-template-columns: repeat(3, 1fr) !important; }
          .pricing-grid { grid-template-columns: repeat(2, 1fr) !important; }
        }
        @media (min-width: 901px) {
          .who-grid { grid-template-columns: repeat(6, 1fr) !important; }
          .pricing-grid { grid-template-columns: repeat(3, 1fr) !important; }
        }
      `}</style>

      {/* NAV */}
      <nav className="nav-inner" style={{ maxWidth: 1100, margin: "0 auto", padding: "16px 24px", display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 24 }}>⚡</span>
          <span style={{ fontSize: 18, fontWeight: 900, background: "linear-gradient(135deg,#38bdf8,#a78bfa)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>EVOSGPT</span>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          {user ? (
            <>
              <Btn ghost onClick={() => setPage("dashboard")}>Dashboard</Btn>
              <Btn onClick={() => setPage("chat")}>💬 Chat</Btn>
            </>
          ) : (
            <>
              <Btn ghost onClick={() => setPage("login")}>Login</Btn>
              <Btn onClick={() => setPage("register")}>Get Started</Btn>
            </>
          )}
        </div>
      </nav>

      {/* HERO */}
      <section className="hero-section" style={{ maxWidth: 800, margin: "0 auto", textAlign: "center", padding: "70px 24px 56px" }}>
        <div style={{ display: "inline-block", padding: "5px 16px", borderRadius: 50, background: "rgba(56,189,248,0.1)", border: "1px solid rgba(56,189,248,0.25)", color: "#38bdf8", fontSize: 12, fontWeight: 700, marginBottom: 24 }}>
          🇬🇭 Part of the EVOS Business Hub Ecosystem
        </div>
        <h1 style={{ fontSize: "clamp(30px,6vw,58px)", fontWeight: 900, lineHeight: 1.1, marginBottom: 18 }}>
          The AI That{" "}
          <span style={{ background: "linear-gradient(135deg,#38bdf8,#a78bfa,#22c55e)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>Evolves With You</span>
        </h1>
        <p style={{ fontSize: "clamp(14px,2vw,17px)", color: "#94a3b8", lineHeight: 1.8, margin: "0 auto 32px", maxWidth: 560 }}>
          EVOSGPT remembers your style, your goals, and your history — getting smarter every conversation. Built for developers, designers, writers and entrepreneurs.
        </p>
        <div className="hero-btns" style={{ display: "flex", justifyContent: "center", gap: 10, flexWrap: "wrap" }}>
          <button onClick={() => setPage(user ? "chat" : "register")} style={{ padding: "14px 28px", borderRadius: 14, border: "none", background: "linear-gradient(135deg,#38bdf8,#0ea5e9)", color: "#000", fontWeight: 900, fontSize: 15, cursor: "pointer", boxShadow: "0 4px 28px rgba(56,189,248,0.3)", flex: "1 1 auto", maxWidth: 280 }}>
            💬 Start Chatting — Free
          </button>
          {!user && (
            <button onClick={() => setPage("login")} style={{ padding: "14px 28px", borderRadius: 14, border: "1px solid rgba(255,255,255,0.15)", background: "transparent", color: "#e2e8f0", fontWeight: 800, fontSize: 15, cursor: "pointer", flex: "1 1 auto", maxWidth: 200 }}>
              Sign In
            </button>
          )}
        </div>

        <div className="stats-row" style={{ display: "flex", justifyContent: "center", gap: 10, flexWrap: "wrap", marginTop: 40 }}>
          {[["GPT-4o","Pro Engine"],["Memory","Evolves Per User"],["Clean Output","Code & Letters"],["24/7","Always On"]].map(([v, l]) => (
            <div key={v} style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.07)", borderRadius: 12, padding: "12px 16px", textAlign: "center", flex: "1 1 90px" }}>
              <div style={{ fontWeight: 900, fontSize: 14, color: "#38bdf8" }}>{v}</div>
              <div style={{ fontSize: 11, color: "#64748b", marginTop: 3 }}>{l}</div>
            </div>
          ))}
        </div>
      </section>

      {/* WHO IT'S FOR */}
      <section style={{ maxWidth: 1100, margin: "0 auto", padding: "10px 24px 60px" }}>
        <div style={{ textAlign: "center", marginBottom: 36 }}>
          <Tag>Who It's For</Tag>
          <h2 style={{ fontSize: "clamp(20px,3vw,30px)", fontWeight: 900, color: "#f1f5f9", margin: "12px 0 0" }}>Built for every professional</h2>
        </div>
        <div className="who-grid" style={{ display: "grid", gap: 12 }}>
          {[
            ["💻","Developers","Clean code, debugging, architecture — production-ready."],
            ["🎨","Designers","Flyer copy, design briefs, color ideas, creative concepts."],
            ["✍️","Writers","Polished letters, emails, CVs, blog posts — copy-paste ready."],
            ["📊","Entrepreneurs","Business plans, pitch decks, financial summaries."],
            ["🎓","Students","Essays, summaries, explanations, study guides."],
            ["📱","Creators","Captions, content calendars, hashtag strategies."],
          ].map(([icon, title, desc]) => (
            <div key={title} style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 18, padding: "20px 16px" }}>
              <div style={{ fontSize: 28, marginBottom: 10 }}>{icon}</div>
              <div style={{ fontWeight: 800, fontSize: 14, color: "#f1f5f9", marginBottom: 6 }}>{title}</div>
              <div style={{ fontSize: 12, color: "#64748b", lineHeight: 1.6 }}>{desc}</div>
            </div>
          ))}
        </div>
      </section>

      {/* SMART OUTPUT */}
      <section style={{ maxWidth: 1100, margin: "0 auto", padding: "0 24px 60px" }}>
        <div style={{ textAlign: "center", marginBottom: 36 }}>
          <Tag>Smart Output</Tag>
          <h2 style={{ fontSize: "clamp(20px,3vw,30px)", fontWeight: 900, color: "#f1f5f9", margin: "12px 0 0" }}>Formatted, clean, copy-paste ready</h2>
        </div>
        <div className="output-grid" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(280px,1fr))", gap: 16 }}>
          <div style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.07)", borderRadius: 18, overflow: "hidden" }}>
            <div style={{ padding: "12px 16px", borderBottom: "1px solid rgba(255,255,255,0.06)", fontWeight: 800, fontSize: 13, color: "#f1f5f9" }}>💻 Code Output</div>
            <div style={{ background: "#020817" }}>
              <div style={{ background: "rgba(56,189,248,0.1)", color: "#38bdf8", fontSize: 11, fontWeight: 700, padding: "5px 14px" }}>python</div>
              <pre style={{ padding: "14px", fontSize: 12, color: "#e2e8f0", fontFamily: "monospace", lineHeight: 1.7, overflow: "auto", margin: 0 }}>{`def calculate_profit(revenue, cost):
    profit = revenue - cost
    margin = (profit / revenue) * 100
    return round(margin, 2)

print(calculate_profit(5000, 3200))
# Output: 36.0`}</pre>
            </div>
            <div style={{ padding: "8px 14px", fontSize: 12, color: "#38bdf8" }}>📋 Copy the above and paste directly.</div>
          </div>
          <div style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.07)", borderRadius: 18, padding: "18px 20px" }}>
            <div style={{ fontWeight: 800, fontSize: 13, color: "#f1f5f9", marginBottom: 14 }}>✍️ Letter Output</div>
            <p style={{ color: "#64748b", fontSize: 13, marginBottom: 8 }}>12th June, 2026</p>
            <p style={{ fontWeight: 700, color: "#f1f5f9", marginBottom: 8 }}>Dear Hiring Manager,</p>
            <p style={{ color: "#94a3b8", fontSize: 13, lineHeight: 1.7, marginBottom: 8 }}>I write to formally apply for the Software Engineer position. With three years of experience in full-stack development...</p>
            <p style={{ color: "#64748b", fontSize: 13 }}>Yours faithfully,<br /><strong style={{ color: "#f1f5f9" }}>Kwame Asante</strong></p>
            <div style={{ marginTop: 12, fontSize: 12, color: "#38bdf8" }}>📋 Copy the above and paste directly.</div>
          </div>
        </div>
      </section>

      {/* MEMORY */}
      <section style={{ maxWidth: 1100, margin: "0 auto", padding: "0 24px 60px" }}>
        <div className="memory-grid" style={{ background: "linear-gradient(135deg,rgba(56,189,248,0.07),rgba(167,139,250,0.07))", border: "1px solid rgba(255,255,255,0.07)", borderRadius: 22, padding: "40px 32px", display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(240px,1fr))", gap: 32, alignItems: "center" }}>
          <div>
            <Tag>Evolving Memory</Tag>
            <h2 style={{ fontSize: "clamp(20px,3vw,28px)", fontWeight: 900, color: "#f1f5f9", margin: "12px 0 12px" }}>EVOSGPT gets smarter every session</h2>
            <p style={{ color: "#94a3b8", lineHeight: 1.8, fontSize: 14 }}>Unlike other AI tools, EVOSGPT builds a memory of who you are — your goals, your writing style, your projects. Each conversation makes it more tailored to you.</p>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {[
              ["🧠","Short-term Memory","Remembers the full context of your current conversation"],
              ["📚","Long-term Memory","AI-generated summary of all your past sessions"],
              ["🎯","Persona Calibration","Adapts its tone and depth to match your tier and style"],
            ].map(([icon, title, desc]) => (
              <div key={title} style={{ display: "flex", gap: 12, alignItems: "flex-start", background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.07)", borderRadius: 12, padding: "12px 14px" }}>
                <span style={{ fontSize: 22, flexShrink: 0 }}>{icon}</span>
                <div>
                  <div style={{ fontWeight: 800, fontSize: 13, color: "#f1f5f9", marginBottom: 3 }}>{title}</div>
                  <div style={{ fontSize: 12, color: "#64748b" }}>{desc}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* PRICING */}
      <section style={{ maxWidth: 1100, margin: "0 auto", padding: "0 24px 60px" }}>
        <div style={{ textAlign: "center", marginBottom: 36 }}>
          <Tag>Pricing</Tag>
          <h2 style={{ fontSize: "clamp(20px,3vw,30px)", fontWeight: 900, color: "#f1f5f9", margin: "12px 0 0" }}>Simple, honest pricing</h2>
          {note && <p style={{ color: "#64748b", fontSize: 12, margin: "10px auto 0", maxWidth: 520 }}>{note}</p>}
        </div>
        <div className="pricing-grid" style={{ display: "grid", gap: 16, maxWidth: 860, margin: "0 auto" }}>
          {[
            { name:"Basic", icon:"🧊", price:"Free", color:"#64748b", rgb:"100,116,139", model:"GPT-4o-mini",
              perks:["10 chats per day","20 message memory","General AI assistant","Access to EVOS ecosystem"],
              cta:"Start Free", primary:false },
            { name:"Pro", icon:"⚡", price:`${format(20)}/mo`, color:"#38bdf8", rgb:"56,189,248", model:"GPT-4o",
              perks:["Unlimited chats","100 message memory","Code & dev expert","Design & flyer briefs","Letter & document writing","Evolving long-term memory"],
              cta:"Upgrade to Pro", primary:true },
            { name:"Core", icon:"🔥", price:`${format(70)}/mo`, color:"#a78bfa", rgb:"167,139,250", model:"GPT-4o (Max Power)",
              perks:["Unlimited chats","300 message memory","All Pro features","Deepest AI responses","Priority everything","Full persona calibration"],
              cta:"Go Core", primary:false },
          ].map(t => (
            <div className="pricing-card" key={t.name} style={{ background: `rgba(${t.rgb},0.07)`, border: `1px solid ${t.color}33`, borderRadius: 22, padding: "26px 22px", position: "relative" }}>
              {t.primary && (
                <div style={{ position: "absolute", top: -12, left: "50%", transform: "translateX(-50%)", background: "#38bdf8", color: "#000", fontWeight: 900, fontSize: 11, padding: "4px 14px", borderRadius: 50, whiteSpace: "nowrap" }}>
                  ⭐ MOST POPULAR
                </div>
              )}
              <div style={{ fontSize: 32, marginBottom: 8 }}>{t.icon}</div>
              <div style={{ fontSize: 20, fontWeight: 900, color: t.color, marginBottom: 3 }}>{t.name}</div>
              <div style={{ fontSize: 11, color: "#475569", marginBottom: 12 }}>{t.model}</div>
              <div style={{ fontSize: 26, fontWeight: 900, color: t.color, marginBottom: 18 }}>{t.price}</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 22 }}>
                {t.perks.map(p => (
                  <div key={p} style={{ fontSize: 13, color: "#94a3b8", display: "flex", gap: 8 }}>
                    <span style={{ color: t.color, fontWeight: 700 }}>✓</span> {p}
                  </div>
                ))}
              </div>
              <button onClick={() => setPage(user ? (t.name === "Basic" ? "chat" : "upgrade") : "register")}
                style={{ width: "100%", padding: "13px", borderRadius: 12, border: `1px solid ${t.color}`, background: t.primary ? t.color : "transparent", color: t.primary ? "#000" : t.color, fontWeight: 900, fontSize: 14, cursor: "pointer" }}>
                {t.cta}
              </button>
            </div>
          ))}
        </div>
      </section>

      {/* EVOSDATA */}
      <section style={{ maxWidth: 1100, margin: "0 auto", padding: "0 24px 60px" }}>
        <div className="crossell-box" style={{ background: "linear-gradient(135deg,rgba(34,197,94,0.08),rgba(16,185,129,0.05))", border: "1px solid rgba(34,197,94,0.2)", borderRadius: 22, padding: "30px 28px", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 20 }}>
          <div>
            <div style={{ fontSize: 12, color: "#22c55e", fontWeight: 700, marginBottom: 6 }}>🔗 EVOS Ecosystem</div>
            <h3 style={{ fontSize: "clamp(16px,2.5vw,20px)", fontWeight: 900, color: "#f1f5f9", marginBottom: 6 }}>Need data to keep chatting?</h3>
            <p style={{ color: "#64748b", fontSize: 13, margin: 0 }}>Buy affordable Ghana data bundles instantly on EvosData.</p>
          </div>
          <button onClick={() => openProduct(EVOSDATA_URL)} style={{ padding: "12px 24px", borderRadius: 12, border: "none", background: "linear-gradient(135deg,#22c55e,#16a34a)", color: "#fff", fontWeight: 900, fontSize: 14, cursor: "pointer", whiteSpace: "nowrap", flexShrink: 0 }}>
            📶 Buy Data on EvosData
          </button>
        </div>
      </section>

      {/* FOOTER */}
      <footer style={{ borderTop: "1px solid rgba(255,255,255,0.06)", padding: "28px 24px 20px", maxWidth: 1100, margin: "0 auto" }}>
        <div className="footer-inner" style={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 16, marginBottom: 16 }}>
          <div>
            <div style={{ fontSize: 16, fontWeight: 900, color: "#38bdf8", marginBottom: 4 }}>⚡ EVOSGPT</div>
            <div style={{ fontSize: 12, color: "#334155" }}>Part of the EVOS Business Hub</div>
          </div>
          <div className="footer-links" style={{ display: "flex", gap: 20, flexWrap: "wrap", alignItems: "center" }}>
            {[["Login","login"],["Register","register"],["Chat","chat"]].map(([l,p]) => (
              <span key={p} onClick={() => setPage(p)} style={{ fontSize: 13, color: "#475569", cursor: "pointer", fontWeight: 600 }}>{l}</span>
            ))}
            <span onClick={() => openProduct(EVOSDATA_URL)} style={{ fontSize: 13, color: "#475569", cursor: "pointer", fontWeight: 600 }}>EvosData</span>
          </div>
        </div>
        <div style={{ fontSize: 12, color: "#334155", textAlign: "center" }}>© 2026 Evoxera Technology · All Rights Reserved</div>
      </footer>
    </div>
  );
}

const Btn = ({ children, onClick, ghost }) => (
  <button onClick={onClick} style={{ padding: "8px 16px", borderRadius: 10, border: ghost ? "1px solid rgba(255,255,255,0.12)" : "none", background: ghost ? "transparent" : "linear-gradient(135deg,#38bdf8,#0ea5e9)", color: ghost ? "#e2e8f0" : "#000", fontWeight: 800, fontSize: 13, cursor: "pointer" }}>
    {children}
  </button>
);

const Tag = ({ children }) => (
  <span style={{ display: "inline-block", padding: "4px 14px", borderRadius: 50, background: "rgba(167,139,250,0.1)", border: "1px solid rgba(167,139,250,0.25)", color: "#a78bfa", fontSize: 12, fontWeight: 700 }}>{children}</span>
);
