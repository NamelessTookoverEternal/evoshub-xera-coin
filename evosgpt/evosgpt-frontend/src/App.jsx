import { useState, useEffect, useRef } from "react";
import Home      from "./pages/Home";
import Login     from "./pages/Login";
import Register  from "./pages/Register";
import Chat      from "./pages/Chat";
import Dashboard from "./pages/Dashboard";
import Upgrade   from "./pages/Upgrade";
import { TOKEN_KEY, LOGOUT_EVENT, getToken, hubSession, verifyUpgrade } from "./api";
import { IS_HUB_MOUNT, HUB_TOKEN_KEY } from "./config";

const PENDING_REF_KEY = "evosgpt_pending_ref";

// Paystack sends the customer back to ?upgrade=success&reference=EVOS-GPT-... — remember it,
// then clean the address bar. The upgrade itself is confirmed with the backend below.
function capturePaystackReturn() {
  try {
    const p = new URLSearchParams(window.location.search);
    const ref = p.get("reference") || p.get("trxref");
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
  useEffect(() => { userRef.current = user; }, [user]);

  useEffect(() => {
    let restored = null;
    try {
      const s = localStorage.getItem("evosgpt_user");
      if (s) { restored = JSON.parse(s); setUser(restored); }
    } catch { localStorage.removeItem("evosgpt_user"); }

    // Hub build: already signed in to the Hub? Use that session — no second login.
    if (IS_HUB_MOUNT && !restored) {
      let hubToken = "";
      try { hubToken = localStorage.getItem(HUB_TOKEN_KEY) || ""; } catch { /* ignore */ }
      if (hubToken) {
        hubSession(hubToken)
          .then(({ data }) => { if (data?.user) handleSetUser(data.user); })
          .catch(() => { /* expired Hub session: they just sign in */ });
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
    verifyUpgrade(ref)
      .then(({ data }) => {
        try { sessionStorage.removeItem(PENDING_REF_KEY); } catch { /* ignore */ }
        if (data?.paid) {
          const next = { ...user, evosgpt_tier: data.tier };
          setUser(next);
          localStorage.setItem("evosgpt_user", JSON.stringify(next));
          setPage("chat");
        }
      })
      .catch(() => { /* keep the reference; the next load tries again */ });
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

  const PROTECTED = { chat: "use EVOSGPT chat", dashboard: "open your dashboard", upgrade: "upgrade your plan" };
  const go = (p) => {
    const signedIn = !!userRef.current;
    if (p === "login" && signedIn) p = pendingRef.current || "chat";
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

  return <div style={{ minHeight: "100vh", background: "#070d1a" }}>{pages[page] ?? pages.home}</div>;
}
