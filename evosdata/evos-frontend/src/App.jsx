import { useState, useEffect } from "react";
import Home               from "./pages/Home";
import Shop               from "./pages/Shop";
import Dashboard          from "./pages/Dashboard";
import Orders             from "./pages/Orders";
import Login              from "./pages/Login";
import Register           from "./pages/Register";
import Success            from "./pages/Success";
import AgentDashboard     from "./pages/AgentDashboard";
import AgentStoreSettings from "./pages/AgentStoreSettings";
import AgentPricing       from "./pages/AgentPricing";
import AgentWithdraw      from "./pages/AgentWithdraw";
import StorePage          from "./pages/StorePage";
import OrderTracking      from "./pages/OrderTracking";
import ETATrack           from "./pages/ETATrack";
import AgentBuyData       from "./pages/AgentBuyData";
import AgentDeposit       from "./pages/AgentDeposit";
import ForgotPassword     from "./pages/ForgotPassword";
import Checkers           from "./pages/Checkers";
import AgentBuyChecker    from "./pages/AgentBuyChecker";
import AgentCheckerPricing from "./pages/AgentCheckerPricing";
import DashXera           from "./pages/DashXera";
import Afa                from "./pages/Afa";
import AgentBuyAfa        from "./pages/AgentBuyAfa";
import SpinWheel          from "./pages/SpinWheel";
import BecomeAgent        from "./pages/BecomeAgent";
import SpinPopup          from "./components/SpinPopup";
import CommunityPopup     from "./components/CommunityPopup";
import { InstallBanner, InstallHelp, useInstall } from "./components/InstallApp";
import { Icon } from "./components/Icons";
import { withBase, stripBase, asset } from "./lib/basePath";
import { ssoFromHub, clearEvosdataSession, hubSessionEnded } from "./lib/hubSession";
import XeraPromo from "./components/XeraPromo";

export default function App() {
    const [page, setPage]         = useState("home");
    const [menuOpen, setMenuOpen] = useState(false);
    const [user, setUser]         = useState(null);

    const theme = "dark";

    // =========================
    // INITIAL LOAD
    // =========================
    useEffect(() => {
        const savedUser = localStorage.getItem("user");
        if (savedUser) {
            try {
                const parsed = JSON.parse(savedUser);
                setUser(parsed);

                // FIX: re-sync agentToken to sessionStorage on every page load/refresh
                // so all components that read sessionStorage also get a valid token
                if (parsed?.agent_token) {
                    sessionStorage.setItem("agentToken", parsed.agent_token);
                    localStorage.setItem("agentToken",   parsed.agent_token);
                }
            } catch {
                localStorage.removeItem("user");
            }
        }

        // Hub single sign-on: no Evosdata user yet, but a Hub session exists.
        // If the Hub session has ended, drop the Evosdata session too.
        if (hubSessionEnded()) {
            clearEvosdataSession();
            setUser(null);
        } else if (!savedUser) {
            ssoFromHub().then((u) => { if (u) setUser(u); });
        }

        detectRoute();

        window.addEventListener("popstate", detectRoute);
        return () => window.removeEventListener("popstate", detectRoute);
    }, []);

    // Close sidebar on Escape key
    useEffect(() => {
        const onKey = (e) => { if (e.key === "Escape") { setMenuOpen(false); setSheetOpen(false); } };
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, []);

    // =========================
    // ROUTE DETECTOR
    // =========================
    const detectRoute = () => {
        const path = stripBase(window.location.pathname);

        if (path.startsWith("/store/")) {
            setPage("store");
            return;
        }

        const routeMap = {
            "/":                   "home",
            "/shop":               "shop",
            "/checkers":           "checkers",
            "/afa":                "afa",
            "/orders":             "orders",
            "/dashboard":          "dashboard",
            "/login":              "login",
            "/register":           "register",
            "/success":            "success",
            "/agent-dashboard":    "agent-dashboard",
            "/agent-store-settings": "agent-store-settings",
            "/agent-pricing":      "agent-pricing",
            "/agent-withdraw":     "agent-withdraw",
            "/agent-buy-data":     "agent-buy-data",
            "/agent-buy-checker":  "agent-buy-checker",
            "/agent-buy-afa":      "agent-buy-afa",
            "/agent-checker-pricing": "agent-checker-pricing",
            "/agent-deposit":      "agent-deposit",
            "/spin":               "spin",
            "/become-agent":       "become-agent",
            "/track":              "track-order",
            "/eta-track":          "eta-track",
            "/forgot-password":    "forgot-password",
            "/dashxera":           "dashxera",
        };

        setPage(routeMap[path] || "home");
    };

    const isAgentActive = user?.role === "agent" && user?.agent_status === "approved";
    const isAdmin       = user?.role === "admin";

    // Customers on a public agent store link (/store/{agentId}) should never
    // get bounced to the homepage or full site nav — that's how they end up
    // leaving mid-checkout and losing their place. See logoWrap and the
    // hamburger button below.
    const isStorePage   = page === "store";
    const isBare        = page === "dashxera";           // admin console draws its own chrome
    const hasChrome     = !isBare;
    const hasRail       = hasChrome && !isStorePage;      // desktop sidebar
    const hasDock       = hasChrome && !isStorePage;      // phone/tablet bottom bar
    const [sheetOpen, setSheetOpen] = useState(false);
    const inst = useInstall();

    useEffect(() => {
        document.documentElement.classList.toggle("has-dock", hasDock);
        document.documentElement.classList.toggle("has-rail", hasRail);
        return () => document.documentElement.classList.remove("has-dock", "has-rail");
    }, [hasDock, hasRail]);

    useEffect(() => { window.scrollTo({ top: 0 }); setSheetOpen(false); }, [page]);

    // =========================
    // LOGOUT
    // =========================
    const logout = () => {
        // FIX: explicitly clear both storages so no stale token lingers
        clearEvosdataSession();
        setUser(null);
        navigate("home");
    };

    // =========================
    // NAVIGATE
    // =========================
    const navigate = (target) => {
        setMenuOpen(false);
        setPage(target);

        const routes = {
            home:               "/",
            shop:               "/shop",
            checkers:           "/checkers",
            afa:                "/afa",
            orders:             "/orders",
            dashboard:          "/dashboard",
            login:              "/login",
            register:           "/register",
            success:            "/success",
            "agent-dashboard":  "/agent-dashboard",
            "agent-store-settings": "/agent-store-settings",
            "agent-pricing":    "/agent-pricing",
            "agent-withdraw":   "/agent-withdraw",
            "agent-buy-data":   "/agent-buy-data",
            "agent-buy-checker":      "/agent-buy-checker",
            "agent-buy-afa":          "/agent-buy-afa",
            "agent-checker-pricing":  "/agent-checker-pricing",
            "agent-deposit":    "/agent-deposit",
            spin:               "/spin",
            "become-agent":     "/become-agent",
            store:              "/store",
            "track-order":      "/track",
            "eta-track":        "/eta-track",
            "order-tracking":   "/eta-track",
            "forgot-password":  "/forgot-password",
            dashxera:           "/dashxera",
        };

        window.history.pushState({}, "", withBase(routes[target] || "/"));
    };

    // =========================
    // PAGE RENDER
    // =========================
    const renderPage = () => {
        switch (page) {
            case "home":
                return <Home setPage={navigate} theme={theme} />;
            case "shop":
                return <Shop user={user} theme={theme} />;
            case "checkers":
                return <Checkers user={user} theme={theme} />;
            case "afa":
                return <Afa />;
            case "orders":
                return <Orders user={user} theme={theme} />;
            case "login":
                return <Login setUser={setUser} setPage={navigate} theme={theme} />;
            case "register":
                return <Register setPage={navigate} theme={theme} />;
            case "dashboard":
                return <Dashboard user={user} setPage={navigate} theme={theme} />;
            case "agent-dashboard":
                return <AgentDashboard user={user} setPage={navigate} theme={theme} />;
            case "agent-store-settings":
                return <AgentStoreSettings user={user} setPage={navigate} />;
            case "agent-pricing":
                return <AgentPricing user={user} setPage={navigate} />;
            case "agent-withdraw":
                return <AgentWithdraw user={user} setPage={navigate} />;
            case "agent-buy-data":
                return <AgentBuyData user={user} setPage={navigate} />;
            case "agent-buy-checker":
                return <AgentBuyChecker user={user} setPage={navigate} />;
            case "agent-buy-afa":
                return <AgentBuyAfa user={user} setPage={navigate} />;
            case "agent-checker-pricing":
                return <AgentCheckerPricing user={user} setPage={navigate} />;
            case "agent-deposit":
                return <AgentDeposit user={user} setPage={navigate} />;
            case "spin":
                return <SpinWheel user={user} setPage={navigate} />;
            case "become-agent":
                return <BecomeAgent user={user} setUser={setUser} setPage={navigate} />;
            case "store":
                return <StorePage setPage={navigate} theme={theme} />;
            case "track-order":
                return <OrderTracking user={user} setPage={navigate} />;
            case "success":
                return <Success theme={theme} />;
            case "eta-track":
            case "order-tracking":
                return <ETATrack setPage={navigate} />;
            case "forgot-password":
                return <ForgotPassword setPage={navigate} />;
            case "dashxera":
                // Guarded again on the server by X-Admin-Secret — hiding the
                // route is convenience, not the actual access control.
                return <DashXera />;
            default:
                return <Home setPage={navigate} theme={theme} />;
        }
    };

    // ---------- navigation model (shared by the desktop rail + the phone sheet) ----------
    const groups = [
        { label: "Main", items: [
            { icon: "home",   label: "Home",            target: "home" },
            { icon: "bolt",   label: "Buy Data",        target: "shop" },
            { icon: "gift",   label: "Spin to Win",     target: "spin", green: true },
            { icon: "box",    label: "My Orders",       target: "orders" },
            { icon: "chart",  label: "Dashboard",       target: "dashboard" },
            { icon: "pin",    label: "Track Order",     target: "eta-track" },
            { icon: "cap",    label: "Result Checkers", target: "checkers", green: true },
            { icon: "user",   label: "AFA Registration", target: "afa" },
        ] },
        ...(user ? [{ label: "Agent", items: [
            { icon: "rocket", label: isAgentActive ? "Agent Dashboard" : "Become Agent", target: isAgentActive ? "agent-dashboard" : "become-agent" },
            ...(isAgentActive ? [
                { icon: "store",  label: "Store Settings",        target: "agent-store-settings" },
                { icon: "signal", label: "Buy Data (Base Price)", target: "agent-buy-data" },
                { icon: "tag",    label: "Manage Pricing",        target: "agent-pricing" },
                { icon: "cap",    label: "Buy Checker (Base)",    target: "agent-buy-checker" },
                { icon: "tag",    label: "Checker Pricing",       target: "agent-checker-pricing" },
                { icon: "user",   label: "AFA Registration",      target: "agent-buy-afa" },
                { icon: "wallet", label: "Withdraw Funds",        target: "agent-withdraw" },
            ] : []),
        ] }] : []),
        ...(isAdmin ? [{ label: "Admin", items: [{ icon: "chart", label: "DashXera", target: "dashxera" }] }] : []),
    ];

    const NavList = () => (
        <>
            {groups.map((g) => (
                <div key={g.label}>
                    <div className="vy-sec">{g.label}</div>
                    {g.items.map((it) => (
                        <button
                            key={it.target + it.label}
                            className={`vy-nav ${g.items && it.green ? "green" : ""} ${page === it.target ? "on" : ""}`}
                            onClick={() => navigate(it.target)}
                        >
                            <Icon name={it.icon} size={19} />
                            <span>{it.label}</span>
                        </button>
                    ))}
                </div>
            ))}
        </>
    );

    const UserCard = () => user ? (
        <div className="vy-user">
            <div className="vy-avatar">{user.username?.[0]?.toUpperCase() || "U"}</div>
            <div style={{ minWidth: 0 }}>
                <b style={{ overflow: "hidden", textOverflow: "ellipsis" }}>@{user.username}</b>
                <small>{isAgentActive ? "Active agent" : isAdmin ? "Admin" : "Customer"}</small>
            </div>
        </div>
    ) : null;

    const InstallCard = () => (!inst.standalone ? (
        <div className="vy-install-card">
            <b>Get the app</b>
            <p>Install EVOS Data on your phone or PC for one-tap ordering.</p>
            <button className="vy-pill vy-pill-solid" style={{ width: "100%", justifyContent: "center" }} onClick={() => { setSheetOpen(false); inst.install(); }}>
                <Icon name="download" size={16} /> Install app
            </button>
        </div>
    ) : null);

    const AuthButtons = () => user ? (
        <button className="vy-nav danger" data-no-community onClick={logout}><Icon name="logout" size={19} /><span>Sign Out</span></button>
    ) : (
        <>
            <button className="vy-nav" onClick={() => navigate("login")}><Icon name="login" size={19} /><span>Login</span></button>
            <button className="vy-pill vy-pill-solid" style={{ width: "100%", justifyContent: "center", height: 44 }} onClick={() => navigate("register")}>Create account</button>
        </>
    );

    const Brand = ({ onClick }) => (
        <button className="vy-brand" onClick={onClick} aria-label="EVOS Data home">
            <img className="vy-logo" src={asset("evosdata.png")} alt="" onError={(e) => { e.target.style.display = "none"; }} />
            <span className="vy-brand-t">
                <span className="vy-brand-n">EVOSDATA</span>
                <span className="vy-brand-s">by EVOS Business HUB</span>
            </span>
        </button>
    );

    const goHome = () => {
        // On a public agent store, "home" would pull the customer out mid-checkout.
        if (isStorePage) { window.location.reload(); return; }
        navigate("home");
    };

    if (isBare) {
        return (
            <div className="vy-app">
                <div className="vy-aurora"><i /></div>
                {renderPage()}
            </div>
        );
    }

    return (
        <div className={`vy-app ${hasRail ? "with-rail" : ""}`}>
            <div className="vy-aurora"><i /></div>
            <div className="vy-grain" />

            {/* ======= DESKTOP RAIL ======= */}
            {hasRail && (
                <aside className="vy-rail" aria-label="Main navigation">
                    <div className="vy-rail-inner">
                        <div className="vy-rail-brand">{Brand({ onClick: goHome })}</div>
                        {UserCard()}
                        {NavList()}
                        <div className="vy-grow" />
                        {InstallCard()}
                        <div style={{ display: "grid", gap: 8, paddingTop: 6 }}>{AuthButtons()}</div>
                    </div>
                </aside>
            )}

            {/* ======= TOP BAR (phones / tablets, and store pages everywhere) ======= */}
            <header className="vy-top">
                {Brand({ onClick: goHome })}
                <div className="vy-top-r">
                    {!isStorePage && !inst.standalone && (
                        <button className="vy-pill" onClick={inst.install} aria-label="Install app">
                            <Icon name="download" size={15} /><span className="t">Install</span>
                        </button>
                    )}
                    {!isStorePage && (user ? (
                        <button className="vy-avatar" onClick={() => setSheetOpen(true)} aria-label="Account menu">{user.username?.[0]?.toUpperCase() || "U"}</button>
                    ) : (
                        <button className="vy-pill vy-pill-solid" onClick={() => navigate("login")}>Login</button>
                    ))}
                </div>
            </header>

            {/* ======= PAGE ======= */}
            <main className="vy-main">
                {(page === "home" || page === "dashboard") && <XeraPromo.Card />}
                {renderPage()}
            </main>
            <XeraPromo.Popup page={page} />

            {/* ======= BOTTOM DOCK ======= */}
            {hasDock && (
                <nav className="vy-dock" aria-label="Quick navigation">
                    <button className={`vy-tab ${page === "home" ? "on" : ""}`} onClick={() => navigate("home")}><Icon name="home" size={22} /><span>Home</span></button>
                    <button className={`vy-tab ${page === "orders" ? "on" : ""}`} onClick={() => navigate("orders")}><Icon name="box" size={22} /><span>Orders</span></button>
                    <button className="vy-tab vy-tab-cta" onClick={() => navigate("shop")} aria-label="Buy data">
                        <span className="orb"><Icon name="bolt" size={26} /></span>
                        <span style={{ position: "relative", top: -2 }}>Buy</span>
                    </button>
                    <button className={`vy-tab ${page === "eta-track" ? "on" : ""}`} onClick={() => navigate("eta-track")}><Icon name="pin" size={22} /><span>Track</span></button>
                    <button className={`vy-tab ${sheetOpen ? "on" : ""}`} onClick={() => setSheetOpen(true)}><Icon name="menu" size={22} /><span>More</span></button>
                </nav>
            )}

            {/* ======= MORE SHEET ======= */}
            {sheetOpen && (
                <>
                    <div className="vy-scrim" onClick={() => setSheetOpen(false)} />
                    <div className="vy-sheet" role="dialog" aria-label="Menu">
                        <div className="vy-grab" />
                        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, marginBottom: 6 }}>
                            <div style={{ flex: 1, minWidth: 0 }}>{UserCard()}</div>
                            <button className="cm-x" style={{ position: "static", flexShrink: 0 }} data-no-community onClick={() => setSheetOpen(false)} aria-label="Close menu">✕</button>
                        </div>
                        {NavList()}
                        {InstallCard()}
                        <div style={{ display: "grid", gap: 8, marginTop: 12 }}>{AuthButtons()}</div>
                    </div>
                </>
            )}

            {/* ======= INSTALL + COMMUNITY ======= */}
            {!isStorePage && <InstallBanner {...inst} hidden={sheetOpen} />}
            {inst.help && <InstallHelp ios={inst.ios} onClose={() => inst.setHelp(false)} />}
            <CommunityPopup />
            <SpinPopup user={user} page={page} setPage={navigate} />
        </div>
    );
}
