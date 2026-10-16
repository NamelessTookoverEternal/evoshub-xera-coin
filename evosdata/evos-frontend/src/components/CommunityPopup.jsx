import { useCallback, useEffect, useRef, useState } from "react";
import { COMMUNITY_URL } from "../lib/community";
import { WhatsAppIcon } from "./Icons";

const JOINED_KEY = "evosCommunityJoined";
const SESSION_COUNT = "evosCommunityShown";
const SESSION_LAST = "evosCommunityLast";
const MAX_PER_SESSION = 4;       // never nag more than this per visit
const MIN_GAP_MS = 40 * 1000;    // and never twice within 40s

// Buttons that mean "I'm closing / cancelling something" — when one of these is
// pressed anywhere in the app, the community invite pops up.
const CANCEL_RE = /^(✕|×|✖|x|cancel|close|dismiss|maybe later|not now|no thanks|no,? thanks|skip|never mind|later)\b/i;
const CANCEL_LABEL_RE = /(close|cancel|dismiss)/i;

const read = (k, area = sessionStorage) => { try { return area.getItem(k); } catch { return null; } };
const write = (k, v, area = sessionStorage) => { try { area.setItem(k, v); } catch { /* ignore */ } };

export default function CommunityPopup() {
  const [open, setOpen] = useState(false);
  const [joined, setJoined] = useState(() => read(JOINED_KEY, localStorage) === "1");
  const timer = useRef(null);

  const show = useCallback((force = false) => {
    if (!force) {
      if (read(JOINED_KEY, localStorage) === "1") return;
      const count = Number(read(SESSION_COUNT) || 0);
      const last = Number(read(SESSION_LAST) || 0);
      if (count >= MAX_PER_SESSION || Date.now() - last < MIN_GAP_MS) return;
      write(SESSION_COUNT, String(count + 1));
    }
    write(SESSION_LAST, String(Date.now()));
    setOpen(true);
  }, []);

  // 1) a friendly nudge shortly after arriving (once per visit)
  useEffect(() => {
    if (read(JOINED_KEY, localStorage) === "1" || read("evosCommunityWelcome")) return;
    const t = setTimeout(() => { write("evosCommunityWelcome", "1"); show(); }, 14000);
    return () => clearTimeout(t);
  }, [show]);

  // 2) pop up whenever the person cancels / closes any popup, sheet or dialog
  useEffect(() => {
    const onClick = (e) => {
      const btn = e.target?.closest?.("button, [role='button'], a");
      if (!btn || btn.closest("[data-community-root]") || btn.closest("[data-no-community]")) return;
      const text = (btn.textContent || "").trim();
      const label = btn.getAttribute("aria-label") || "";
      if (CANCEL_RE.test(text) || (!text || text.length <= 2) && CANCEL_LABEL_RE.test(label) || btn.hasAttribute("data-cancel")) {
        clearTimeout(timer.current);
        timer.current = setTimeout(() => show(), 450);
      }
    };
    document.addEventListener("click", onClick);
    return () => { document.removeEventListener("click", onClick); clearTimeout(timer.current); };
  }, [show]);

  // 3) explicit trigger from other code: openCommunity()
  useEffect(() => {
    const fn = () => show(true);
    window.addEventListener("evos:community", fn);
    return () => window.removeEventListener("evos:community", fn);
  }, [show]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e) => { if (e.key === "Escape") setOpen(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  const join = () => {
    write(JOINED_KEY, "1", localStorage);
    setJoined(true);
    setOpen(false);
  };

  return (
    <div data-community-root>
      {/* Floating community button with the red attention badge */}
      {!open && (
        <button className="cm-fab" onClick={() => show(true)} aria-label="Join our WhatsApp community">
          <span className="ico">
            <WhatsAppIcon size={30} />
            {!joined && <span className="badge">1</span>}
          </span>
          <span className="lbl">{joined ? "Community" : "Join community"}</span>
        </button>
      )}

      {open && (
        <div className="cm-wrap" role="dialog" aria-modal="true" aria-label="Join the EVOS community">
          <div className="cm-scrim" onClick={() => setOpen(false)} />
          <div className="cm-card">
            <button className="cm-x" onClick={() => setOpen(false)} aria-label="Close">✕</button>
            <div className="cm-hero">
              <WhatsAppIcon size={46} />
              {!joined && <span className="badge">1</span>}
            </div>
            <h2>Join the <em>EVOS Community</em></h2>
            <p>Get price drops, restock alerts and quick help straight from our WhatsApp channel.</p>
            <div className="cm-perks">
              <div className="cm-perk"><i>⚡</i> Be first to know about cheap bundle deals</div>
              <div className="cm-perk"><i>🔔</i> Restock &amp; network-status alerts</div>
              <div className="cm-perk"><i>🤝</i> Real people helping real people</div>
            </div>
            <a className="cm-join" href={COMMUNITY_URL} target="_blank" rel="noreferrer" onClick={join}>
              <WhatsAppIcon size={22} /> Join community
            </a>
            <button className="cm-later" onClick={() => setOpen(false)}>Maybe later</button>
          </div>
        </div>
      )}
    </div>
  );
}
