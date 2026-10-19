import { useState } from "react";
import { hubSignInUrl } from "../lib/hubSession";

const KEY = "evos_guest_banner_dismissed";
const read = () => { try { return sessionStorage.getItem(KEY) === "1"; } catch { return false; } };

// Non-blocking guest notice. Honest about what EVOS Data keeps: a guest's cart
// and form entries are not saved; orders can still be tracked by phone number.
export default function GuestBanner() {
  const [hidden, setHidden] = useState(read);
  if (hidden) return null;
  const dismiss = () => { try { sessionStorage.setItem(KEY, "1"); } catch { /* ignore */ } setHidden(true); };
  return (
    <div role="status" style={{ display: "flex", alignItems: "center", gap: ".75rem", flexWrap: "wrap",
      margin: "0 0 1rem", padding: ".6rem .9rem", borderRadius: 12, fontSize: ".85rem", lineHeight: 1.4,
      background: "var(--surface, #14141c)", border: "1px solid var(--line, #2c2c3a)", color: "var(--muted, #bbb)" }}>
      <span style={{ flex: 1, minWidth: 220 }}>
        You're browsing as a guest. Some progress, preferences, or activity may be lost if you leave or refresh.
        Sign in to help save and sync across EVOS products.
      </span>
      <a href={hubSignInUrl()} style={{ color: "var(--lime, #b6ff3c)", fontWeight: 700, textDecoration: "none" }}>Sign in</a>
      <button type="button" onClick={dismiss} aria-label="Dismiss"
        style={{ background: "none", border: "none", color: "inherit", cursor: "pointer", fontSize: "1.1rem" }}>×</button>
    </div>
  );
}
