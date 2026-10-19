import { hubSignInUrl } from "../lib/hubSession";

// Action-specific sign-in prompt. Shown in place of a protected page so the
// protected operation never runs for a guest. Guests can cancel and keep browsing.
const LABELS = {
  dashboard: "view your dashboard",
  orders: "see your order history",
  spin: "spin the wheel",
  "become-agent": "apply to become an agent",
  "agent-dashboard": "open the agent dashboard",
  "agent-store-settings": "manage your agent store",
  "agent-pricing": "set your agent prices",
  "agent-withdraw": "withdraw from your wallet",
  "agent-buy-data": "buy data from your agent wallet",
  "agent-buy-checker": "buy checkers from your agent wallet",
  "agent-buy-afa": "register AFA from your agent wallet",
  "agent-checker-pricing": "set checker prices",
  "agent-deposit": "top up your wallet",
};

export const authActionLabel = (page) => LABELS[page] || "continue";

export default function AuthPrompt({ page, back, onCancel }) {
  const action = authActionLabel(page);
  return (
    <div role="dialog" aria-modal="false" aria-labelledby="auth-prompt-title"
      style={{ maxWidth: 440, margin: "3rem auto", padding: "1.5rem", borderRadius: 16,
        background: "var(--surface, #14141c)", border: "1px solid var(--line-strong, #2c2c3a)",
        color: "var(--text, #fff)", textAlign: "center" }}>
      <h2 id="auth-prompt-title" style={{ margin: "0 0 .5rem", fontSize: "1.25rem" }}>
        Sign in to {action}
      </h2>
      <p style={{ margin: "0 0 1.25rem", color: "var(--muted, #aaa)", lineHeight: 1.5 }}>
        This needs your EVOS account so it stays private and tied to you. You can keep browsing the shop as a guest.
      </p>
      <div style={{ display: "flex", gap: ".6rem", justifyContent: "center", flexWrap: "wrap" }}>
        <a href={hubSignInUrl(back)} className="btn"
          style={{ padding: ".65rem 1.2rem", borderRadius: 10, background: "var(--lime, #b6ff3c)", color: "#000", fontWeight: 700, textDecoration: "none" }}>
          Log in
        </a>
        <a href={hubSignInUrl(back) + "&mode=register"} className="btn"
          style={{ padding: ".65rem 1.2rem", borderRadius: 10, border: "1px solid var(--line-strong, #2c2c3a)", color: "var(--text, #fff)", fontWeight: 600, textDecoration: "none" }}>
          Sign up
        </a>
        <button type="button" onClick={onCancel}
          style={{ padding: ".65rem 1.2rem", borderRadius: 10, background: "transparent", border: "none", color: "var(--muted, #aaa)", cursor: "pointer" }}>
          Continue as guest
        </button>
      </div>
    </div>
  );
}
