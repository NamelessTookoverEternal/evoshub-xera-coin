import { useState, useEffect, useRef } from "react";
import Home      from "./pages/Home";
import Login     from "./pages/Login";
import Register  from "./pages/Register";
import Chat      from "./pages/Chat";
import Dashboard from "./pages/Dashboard";
import Upgrade   from "./pages/Upgrade";
import TabBar    from "./components/TabBar";
import { TOKEN_KEY, LOGOUT_EVENT, getToken, hubSession, verifyUpgrade } from "./api";
import { IS_HUB_MOUNT, HUB_TOKEN_KEY } from "./config";

const PENDING_REF_KEY = "evosgpt_pending_ref";
const PROTECTED = { chat: "use EVOSGPT chat", dashboard: "open your dashboard", upgrade: "upgrade your plan" };
const readHubToken = () => { try { return localStorage.getItem(HUB_TOKEN_KEY) || ""; } catch { return ""; } };

// Paystack sends the customer back to ?upgrade=success&reference=EVOS-GPT-... — remember it,
// then clean the address bar. The upgrade itself is confirmed with the backend below.
function capturePaystackReturn() {
  try {
    const p = new URLSearchParams(window.location.search);
    const ref = p.get("reference") || p.get("trxref");
    if (p.get("upgrade") === "crypto") {
      // NOWPayments sends no reference back; the order reference was saved in this browser when the invoice was created.
      p.delete("upgrade");
      const q = p.toString();
      window.history.replaceState({}, "", window.location.pathname + (q ? `?${q}` : ""));
    }
    if (p.get("upgrade") === "success" && ref) {
      sessionStorage.setItem(PENDING_REF_KEY, ref);
      p.delete("upgrade"); p.delete("reference"); p.delete("trxref");
      const q = p.toString();
      window.history.replaceState({}, "", window.location.pathname + (q ? `?${q}` : ""));
    }
  } catch { /* ignore */ }
}
capturePaystackReturn();

const hasReferralLink = () => {
  try { return !!new URLSearchParams(window.location.search).get("ref"); } catch { return false; }
};

export default function App() {
  const [page, setPage] = useState(() => (hasReferralLink() ? "register" : "home"));
  const [user, setUser] = useState(null);
  // Guest-first: browse freely; asking for a protected page (chat, dashboard,
  // upgrade) shows sign-in, remembers where they were headed, and returns them there.
  const userRef = useRef(null);
  const pendingRef = useRef("");
  const [pendingNotice, setPendingNotice] = useState("");
  // Inside the Hub we re-check the Hub session every time EVOSGPT opens. Until that finishes, protected pages show
  // "Signing you in..." instead of bouncing the person to the login page.
  const [checking, setChecking] = useState(() => IS_HUB_MOUNT && !!readHubToken());
  useEffect(() => { userRef.current = user; }, [user]);

  useEffect(() => {
    let restored = null;
    try {
      const s = localStorage.getItem("evosgpt_user");
      if (s) { restored = JSON.parse(s); setUser(restored); }
    } catch { localStorage.removeItem("evosgpt_user"); }

    // Hub build: already signed in to the Hub? Use that session, no second login. Always ask the Hub for a fresh
    // session (even when a user was saved earlier): the saved copy can be a day old or belong to another account.
    if (IS_HUB_MOUNT) {
      const hubToken = readHubToken();
      if (hubToken) {
        const giveUp = setTimeout(() => setChecking(false), 45000);   // a cold server can be slow; never hang forever
        hubSession(hubToken)
          .then(({ data }) => { if (data?.user) handleSetUser(data.user); })
          .catch((e) => {
            // Expired Hub session: drop a saved user that only came from that Hub session, they sign in again.
            const savedCopy = (() => { try { return localStorage.getItem(TOKEN_KEY) || ""; } catch { return ""; } })();
            if (restored && e?.response?.status === 401 && savedCopy === hubToken) handleSetUser(null);
          })
          .finally(() => { clearTimeout(giveUp); setChecking(false); });
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Session rejected by the server (expired / wrong user): back to login.
  useEffect(() => {
    const onLogout = () => { handleSetUser(null); setPage("login"); };
    window.addEventListener(LOGOUT_EVENT, onLogout);
    return () => window.removeEventListener(LOGOUT_EVENT, onLogout);
  }, []);

  // Back from Paystack: confirm the payment with the backend, then land in the chat.
  useEffect(() => {
    if (!user || !getToken()) return;
    let ref = "";
    try { ref = sessionStorage.getItem(PENDING_REF_KEY) || ""; } catch { /* ignore */ }
    if (!ref) return;
    let stopped = false, tries = 0, timer = null;
    const check = () => {
      verifyUpgrade(ref)
        .then(({ data }) => {
          if (stopped) return;
          if (data?.paid) {
            try { sessionStorage.removeItem(PENDING_REF_KEY); } catch { /* ignore */ }
            const next = { ...user, evosgpt_tier: data.tier };
            setUser(next);
            localStorage.setItem("evosgpt_user", JSON.stringify(next));
            setPage("chat");
          } else if (data?.pending && ++tries < 60) {
            timer = setTimeout(check, 10000);   // USDT: the network confirmation can take a few minutes
          } else {
            try { sessionStorage.removeItem(PENDING_REF_KEY); } catch { /* ignore */ }
          }
        })
        .catch(() => { /* keep the reference; the next load tries again */ });
    };
    check();
    return () => { stopped = true; clearTimeout(timer); };
  }, [user?.id]);

  // The session token lives in its own key so refreshing the user object can never drop it.
  const handleSetUser = (u) => {
    if (u) {
      const { user_token, ...rest } = u;
      if (user_token) localStorage.setItem(TOKEN_KEY, user_token);
      userRef.current = rest;
      setUser(rest);
      localStorage.setItem("evosgpt_user", JSON.stringify(rest));
    } else {
      userRef.current = null;
      setUser(null);
      localStorage.removeItem("evosgpt_user");
      localStorage.removeItem(TOKEN_KEY);
    }
  };

  const handleLogout = () => { handleSetUser(null); setPage("home"); };

  // Once the Hub check is done, a protected page with nobody signed in goes to login (and returns here after).
  useEffect(() => {
    if (checking || userRef.current || !PROTECTED[page]) return;
    pendingRef.current = page;
    setPendingNotice(`Sign in to ${PROTECTED[page]}. You can go back and keep browsing as a guest.`);
    setPage("login");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [checking]);

  const go = (p) => {
    const signedIn = !!userRef.current;
    if (p === "login" && signedIn) p = pendingRef.current || "chat";
    if (PROTECTED[p] && !signedIn && checking) {   // the Hub check is still running: wait for it, do not bounce
      pendingRef.current = p;
      setPage(p);
      return;
    }
    if (PROTECTED[p] && !signedIn) {
      pendingRef.current = p;
      setPendingNotice(`Sign in to ${PROTECTED[p]}. You can go back and keep browsing as a guest.`);
      setPage("login");
      return;
    }
    if (p === "chat" && signedIn && pendingRef.current) p = pendingRef.current;
    if (signedIn && PROTECTED[p]) { pendingRef.current = ""; setPendingNotice(""); }
    if (!PROTECTED[p] && p !== "login" && p !== "register") { pendingRef.current = ""; setPendingNotice(""); }
    setPage(p);
  };

  const pages = {
    home:      <Home      setPage={go} user={user} />,
    login:     <Login     setPage={go} setUser={handleSetUser} notice={pendingNotice} onBack={() => go("home")} />,
    register:  <Register  setPage={go} setUser={handleSetUser} />,
    chat:      <Chat      setPage={go} user={user} setUser={handleSetUser} />,
    dashboard: <Dashboard setPage={go} user={user} onLogout={handleLogout} />,
    upgrade:   <Upgrade   setPage={go} user={user} setUser={handleSetUser} />,
  };

  const waiting = checking && !!PROTECTED[page];
  const showTabs = !waiting && (page === "home" || page === "dashboard" || page === "upgrade");
  return (
    <>
      <div className="aurora" aria-hidden="true"><i /><i /><i /></div>
      <div className={`app-root ${showTabs ? "has-tabs" : ""}`}>
        {waiting
          ? <div role="status" style={{ minHeight: "60vh", display: "flex", alignItems: "center", justifyContent: "center", opacity: 0.8 }}>Signing you in…</div>
          : (pages[page] ?? pages.home)}
      </div>
      {showTabs && <TabBar page={page} setPage={go} user={user} />}
    </>
  );
}
