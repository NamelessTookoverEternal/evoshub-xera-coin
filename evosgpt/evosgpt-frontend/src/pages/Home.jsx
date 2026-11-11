import { EVOSDATA_URL, openProduct } from "../config";
import { useCurrency } from "../lib/currency";

const PROMPTS = [
  ["✍️", "Write a letter", "Write a professional job application letter for a customer service role in Accra."],
  ["💻", "Fix my code", "Help me debug this code and explain what was wrong: "],
  ["📊", "Business plan", "Draft a one-page business plan for a small data-reselling business in Ghana."],
  ["🎨", "Create an image", "Create an image of a modern Ghanaian market at sunrise, warm colours."],
  ["📄", "Make a PDF", "Create a clean one-page PDF CV for a graphic designer."],
  ["🎓", "Explain simply", "Explain how blockchain works in simple terms, with an everyday example."],
];

const FEATURES = [
  ["🧠", "It remembers you", "Your goals, your style and your projects carry over, so every chat starts where the last one ended."],
  ["🎨", "Makes images", "Describe it and EVOSGPT draws it. Edit your own photos too. (Pro and Core)"],
  ["📄", "PDF and Word files", "Letters, CVs and reports, ready to download in A4, Letter or Legal."],
  ["💻", "Code that works", "Clean, copy-ready code with the reasoning behind it, for real projects."],
];

export default function Home({ setPage, user }) {
  const { format, note } = useCurrency();
  const first = user?.full_name?.split(" ")[0] || user?.username;

  const ask = (text) => {
    try { if (text) sessionStorage.setItem("evosgpt_prefill", text); } catch { /* ignore */ }
    setPage(user ? "chat" : "register");
  };

  const plans = [
    { name: "Basic", icon: "🧊", price: "Free", model: "GPT-4o-mini", color: "#94a3b8",
      perks: ["10 chats per day", "20 message memory", "General AI assistant", "Part of the EVOS ecosystem"],
      cta: user ? "Open chat" : "Start free", to: user ? "chat" : "register" },
    { name: "Pro", icon: "⚡", price: `${format(20)}/mo`, model: "GPT-4o", color: "#38bdf8", pop: true,
      perks: ["Unlimited chats", "Images, PDF and Word", "100 message memory", "Code and design briefs", "Evolving long-term memory"],
      cta: "Get Pro", to: user ? "upgrade" : "register" },
    { name: "Core", icon: "🔥", price: `${format(70)}/mo`, model: "GPT-4o, max power", color: "#a78bfa",
      perks: ["Everything in Pro", "300 message memory", "Deepest, longest answers", "Priority processing", "Full persona calibration"],
      cta: "Go Core", to: user ? "upgrade" : "register" },
  ];

  return (
    <div className="hm">
      <header className="hm-top">
        <div className="hm-brand"><span className="orb sm" /> <span className="grad-text">EVOSGPT</span></div>
        {user
          ? <button className="btn btn-ghost" style={{ padding: "9px 16px" }} onClick={() => setPage("dashboard")}>{first}</button>
          : <button className="btn btn-ghost" style={{ padding: "9px 16px" }} onClick={() => setPage("login")}>Sign in</button>}
      </header>

      <section className="hm-hero">
        <div className="orb" aria-hidden="true" />
        <h1>{user ? <>Hi {first}.<br /></> : null}<span className="grad-text">{user ? "What shall we build today?" : "The AI that evolves with you"}</span></h1>
        <p>{user ? "Pick up where you left off, or start something new." : "It remembers your style, your goals and your history, and gets sharper every conversation."}</p>

        <div className="hm-ask glass" role="button" tabIndex={0} onClick={() => ask("")} onKeyDown={(e) => e.key === "Enter" && ask("")}>
          <span>Ask EVOSGPT anything…</span>
          <button className="go" aria-label="Start chatting" onClick={(e) => { e.stopPropagation(); ask(""); }}>➤</button>
        </div>
        <div className="rail" style={{ justifyContent: "flex-start" }}>
          {PROMPTS.map(([icon, label, text]) => (
            <button key={label} className="chip" onClick={() => ask(text)}><span>{icon}</span>{label}</button>
          ))}
        </div>
      </section>

      <section className="hm-sec">
        <div className="eyebrow">What it does</div>
        <h2>Built to get real work done</h2>
        <div className="rail">
          {FEATURES.map(([ic, t, d]) => (
            <div key={t} className="feat glass"><div className="ic">{ic}</div><b>{t}</b><span>{d}</span></div>
          ))}
        </div>
      </section>

      <section className="hm-sec">
        <div className="eyebrow">Plans</div>
        <h2>Simple, honest pricing</h2>
        {note && <p style={{ color: "var(--dim)", fontSize: 12, margin: "-4px 0 12px" }}>{note}</p>}
        <div className="plans">
          {plans.map((p) => (
            <div key={p.name} className={`plan glass ${p.pop ? "pop" : ""}`}>
              {p.pop && <div className="tag">MOST POPULAR</div>}
              <div style={{ display: "flex", alignItems: "center", gap: 8, fontWeight: 800, fontSize: 18, color: p.color }}>
                <span style={{ fontSize: 22 }}>{p.icon}</span>{p.name}
              </div>
              <div style={{ fontSize: 11.5, color: "var(--dim)", marginTop: 2 }}>{p.model}</div>
              <div className="price" style={{ color: p.color }}>{p.price}</div>
              <ul>{p.perks.map((x) => <li key={x}>{x}</li>)}</ul>
              <button className={`btn ${p.pop ? "btn-primary" : "btn-ghost"}`} style={{ width: "100%" }} onClick={() => setPage(p.to)}>{p.cta}</button>
            </div>
          ))}
        </div>
      </section>

      <section className="hm-sec">
        <div className="hm-cross glass">
          <div>
            <div style={{ fontSize: 12, color: "var(--mint)", fontWeight: 800, marginBottom: 4 }}>🔗 EVOS ecosystem</div>
            <div className="display" style={{ fontSize: 18, fontWeight: 700 }}>Need data to keep chatting?</div>
            <div style={{ color: "var(--muted)", fontSize: 13, marginTop: 2 }}>Buy affordable Ghana data bundles on EvosData.</div>
          </div>
          <button className="btn" style={{ background: "linear-gradient(135deg,#34d399,#10b981)", color: "#04130d" }} onClick={() => openProduct(EVOSDATA_URL)}>📶 Buy data</button>
        </div>
      </section>

      <footer className="hm-foot">© 2026 Evoxera Technology · Part of the EVOS Business Hub</footer>
    </div>
  );
}
