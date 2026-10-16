import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { smartFetch } from "../config";

/**
 * DashXera — internal admin operations console for EVOS Data Services.
 *
 * Sign-in is the same admin_agents-gated login used across the Evoxera
 * ecosystem (see admin_auth.py / POST /admin/login): your existing
 * public.users username and password, valid here only if that account also
 * has an active admin_agents row. There's no separate DashXera password to
 * remember, and the same session works the way EvosHub/XERA admin access
 * already does.
 *
 * The session token is held in sessionStorage only, so closing the tab
 * signs you out. It expires after 12 hours regardless, and access can be
 * revoked instantly from admin_agents — the backend re-checks that on
 * every single request, not just at login. No provider key, Paystack
 * secret or Supabase credential is ever sent to or stored by this page.
 */

const WINDOWS = [7, 14, 30, 60, 90];
const REFRESH_MS = 60000;
const TOKEN_KEY = "dashxeraToken";
const USER_KEY = "dashxeraUser";
const PAGE_SIZE = 25;

const SECTIONS = [
  { id: "overview", label: "Overview", icon: "▤" },
  { id: "orders", label: "Orders", icon: "☰" },
  { id: "undispatched", label: "Paid / Undispatched", icon: "!" },
  { id: "financials", label: "Financials", icon: "₵" },
  { id: "agents", label: "Agents", icon: "◎" },
  { id: "providers", label: "Providers", icon: "◇" },
  { id: "incidents", label: "Incidents", icon: "△" },
  { id: "ecosystem", label: "Ecosystem Sales", icon: "◈" },
  { id: "audit", label: "Reprocessing / Audit", icon: "✓" },
];

const cedi = (n) =>
  `GH₵ ${Number(n || 0).toLocaleString("en-GH", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;

const HEALTH = {
  HEALTHY: { color: "#4ade80", bg: "rgba(34,197,94,0.12)" },
  IDLE: { color: "#9189b5", bg: "rgba(100,116,139,0.12)" },
  DEGRADED: { color: "#fbbf24", bg: "rgba(245,158,11,0.12)" },
  LOW: { color: "#fb923c", bg: "rgba(249,115,22,0.14)" },
  ERROR: { color: "#f87171", bg: "rgba(239,68,68,0.12)" },
  UNKNOWN: { color: "#9189b5", bg: "rgba(100,116,139,0.12)" },
};

const KIND_LABELS = {
  low_balance: "Provider balance",
  rate_limited: "Rate limited",
  provider_down: "Provider unreachable",
  out_of_stock: "Bundle unavailable",
  auth: "Credentials rejected",
  purchase_failed: "Purchase rejected",
  reprocess_failed: "Reprocess rejected",
  payment: "Payment issue",
};

const timeAgo = (iso) => {
  if (!iso) return "—";
  const mins = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.round(hrs / 24)}d ago`;
};

const when = (iso) => (iso ? new Date(iso).toLocaleString("en-GH") : "—");

export default function DashXera() {
  const [token, setToken] = useState(() => sessionStorage.getItem(TOKEN_KEY) || "");
  const [adminUser, setAdminUser] = useState(() => {
    try { return JSON.parse(sessionStorage.getItem(USER_KEY) || "null"); }
    catch { return null; }
  });
  const [identifierDraft, setIdentifierDraft] = useState("");
  const [passwordDraft, setPasswordDraft] = useState("");
  const [loginBusy, setLoginBusy] = useState(false);
  const [loginError, setLoginError] = useState("");
  const [authed, setAuthed] = useState(false);

  const [section, setSection] = useState("overview");
  const [days, setDays] = useState(7);
  const [navOpen, setNavOpen] = useState(false);

  const [summary, setSummary] = useState(null);
  const [attention, setAttention] = useState(null);
  const [providers, setProviders] = useState(null);
  const [ecosystem, setEcosystem] = useState(null);
  const [agents, setAgents] = useState(null);
  const [orders, setOrders] = useState(null);
  const [undispatched, setUndispatched] = useState(null);
  const [incidents, setIncidents] = useState(null);
  const [audit, setAudit] = useState(null);

  const [ordersPage, setOrdersPage] = useState(1);
  const [undispatchedPage, setUndispatchedPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState("");
  const [search, setSearch] = useState("");

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [busyIds, setBusyIds] = useState([]);
  const [selected, setSelected] = useState([]);
  const [toast, setToast] = useState(null);
  const [lastSync, setLastSync] = useState(null);
  const [providerChoice, setProviderChoice] = useState({}); // { [orderId]: "DATAMART" | "" }
  const [bulkProvider, setBulkProvider] = useState("");
  const timer = useRef(null);

  const call = useCallback(
    async (path, options = {}) => {
      const res = await smartFetch(path, {
        ...options,
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
          ...(options.headers || {}),
        },
      });
      // 401 = the token itself is missing, malformed or expired. 403 = the
      // token is fine but admin_agents.is_active was flipped off since it
      // was issued — the backend re-checks that live on every request.
      // Distinct messages so someone whose access was pulled isn't told
      // their session merely "timed out".
      if (res.status === 401) throw new Error("SESSION_EXPIRED");
      if (res.status === 403) throw new Error("ACCESS_REVOKED");
      if (!res.ok) throw new Error(`Request failed (${res.status})`);
      return res.json();
    },
    [token]
  );

  const load = useCallback(
    async (quiet = false) => {
      if (!token) return;
      if (!quiet) setLoading(true);
      setError("");
      try {
        // Every section needs the header numbers; the rest is fetched per tab
        // so a 90-day window never pulls nine endpoints at once.
        const tasks = [call(`/admin/dashxera/summary?days=${days}`).then(setSummary)];

        if (section === "overview") {
          tasks.push(
            call(`/admin/dashxera/attention?days=${days}`).then(setAttention),
            call(`/admin/dashxera/providers?days=${days}`).then(setProviders),
            call(`/admin/dashxera/ecosystem?days=${days}`).then(setEcosystem)
          );
        }
        if (section === "providers") {
          tasks.push(call(`/admin/dashxera/providers?days=${days}`).then(setProviders));
        }
        if (section === "ecosystem") {
          tasks.push(call(`/admin/dashxera/ecosystem?days=${days}`).then(setEcosystem));
        }
        if (section === "agents") {
          tasks.push(call(`/admin/dashxera/agents?days=${days}`).then(setAgents));
        }
        if (section === "orders") {
          const params = new URLSearchParams({
            days, page: ordersPage, page_size: PAGE_SIZE,
          });
          if (statusFilter) params.set("status", statusFilter);
          if (search.trim()) params.set("search", search.trim());
          tasks.push(call(`/admin/dashxera/orders?${params}`).then(setOrders));
        }
        if (section === "undispatched") {
          tasks.push(
            call(`/admin/dashxera/undispatched?days=${days}&page=${undispatchedPage}&page_size=${PAGE_SIZE}`)
              .then(setUndispatched),
            // Needed to populate the "reassign provider" dropdowns below —
            // the eligible provider list can change (routes get disabled),
            // so it's fetched fresh rather than reused from another tab.
            call(`/admin/dashxera/providers?days=${days}`).then(setProviders)
          );
        }
        if (section === "incidents") {
          tasks.push(call(`/admin/dashxera/incidents?days=${days}&page_size=50`).then(setIncidents));
        }
        if (section === "audit") {
          tasks.push(call(`/admin/dashxera/audit?days=${days}&page_size=50`).then(setAudit));
        }

        await Promise.all(tasks);
        setAuthed(true);
        setLastSync(new Date());
      } catch (err) {
        if (err.message === "SESSION_EXPIRED") {
          signOut();
          setLoginError("Your session expired. Please sign in again.");
        } else if (err.message === "ACCESS_REVOKED") {
          signOut();
          setLoginError("Your admin access has been revoked.");
        } else {
          setError(err.message || "Could not reach the dashboard API.");
        }
      } finally {
        setLoading(false);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [call, days, token, section, ordersPage, undispatchedPage, statusFilter, search]
  );

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (!authed) return undefined;
    timer.current = setInterval(() => load(true), REFRESH_MS);
    return () => clearInterval(timer.current);
  }, [authed, load]);

  const flash = (message, tone = "ok") => {
    setToast({ message, tone });
    setTimeout(() => setToast(null), 6000);
  };

  const signIn = async (event) => {
    event.preventDefault();
    const identifier = identifierDraft.trim();
    if (!identifier || !passwordDraft) return;

    setLoginBusy(true);
    setLoginError("");
    try {
      const res = await smartFetch("/admin/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ identifier, password: passwordDraft }),
      });

      // 429 = brute-force lockout, returned as a plain-text detail rather
      // than the {status: ...} shape every other outcome uses.
      if (res.status === 429) {
        const body = await res.json().catch(() => ({}));
        setLoginError(body.detail || "Too many attempts. Please wait and try again.");
        return;
      }

      const data = await res.json();

      if (data.status === "ok" && data.token) {
        sessionStorage.setItem(TOKEN_KEY, data.token);
        sessionStorage.setItem(USER_KEY, JSON.stringify(data.user));
        setToken(data.token);
        setAdminUser(data.user);
        setPasswordDraft("");
        return;
      }

      if (data.status === "not_authorized") {
        setLoginError("This account doesn't have admin access.");
        return;
      }

      // Covers "invalid_credentials" and anything unrecognized —
      // deliberately generic, matching the backend's own refusal to
      // distinguish "wrong password" from "unknown account".
      setLoginError("Incorrect username/email or password.");
    } catch {
      setLoginError("Couldn't reach the server. Check your connection and try again.");
    } finally {
      setLoginBusy(false);
    }
  };

  const signOut = () => {
    sessionStorage.removeItem(TOKEN_KEY);
    sessionStorage.removeItem(USER_KEY);
    setToken("");
    setAdminUser(null);
    setAuthed(false);
    setSummary(null);
  };

  const goTo = (id) => {
    setSection(id);
    setNavOpen(false);
    setSelected([]);
  };

  const reprocess = async (orderId) => {
    setBusyIds((prev) => [...prev, orderId]);
    try {
      // An explicit provider picked in that row's dropdown overrides the
      // priority chain. The backend still refuses it if it isn't routed for
      // that order's network, so a bad pick errors instead of silently
      // falling back to auto.
      const provider = providerChoice[orderId] || undefined;
      const res = await call(`/admin/dashxera/reprocess/${orderId}`, {
        method: "POST",
        body: JSON.stringify({ force: false, provider }),
      });
      if (res.outcome === "success") {
        flash(`Order ${orderId} dispatched via ${res.provider} — ${res.provider_ref}`);
        setProviderChoice((prev) => {
          const next = { ...prev };
          delete next[orderId];
          return next;
        });
      } else {
        flash(`Order ${orderId} ${res.outcome}: ${res.reason}`, "warn");
      }
      await load(true);
    } catch (err) {
      flash(err.message, "warn");
    } finally {
      setBusyIds((prev) => prev.filter((id) => id !== orderId));
    }
  };

  const reprocessSelected = async () => {
    if (!selected.length) return;
    setBusyIds((prev) => [...prev, ...selected]);
    try {
      const res = await call(`/admin/dashxera/reprocess-bulk`, {
        method: "POST",
        body: JSON.stringify({
          order_ids: selected,
          force: false,
          provider: bulkProvider || undefined,
        }),
      });
      const parts = Object.entries(res.summary || {}).map(([k, v]) => `${v} ${k}`);
      flash(`${selected.length} orders: ${parts.join(", ")}`);
      setSelected([]);
      setBulkProvider("");
      await load(true);
    } catch (err) {
      flash(err.message, "warn");
    } finally {
      setBusyIds([]);
    }
  };

  const resolveIncident = async (id) => {
    try {
      await call(`/admin/dashxera/incidents/${id}/resolve`, {
        method: "POST",
        body: JSON.stringify({ note: "Cleared from DashXera" }),
      });
      await load(true);
    } catch (err) {
      flash(err.message, "warn");
    }
  };

  const toggle = (id) =>
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));

  const eligible = useMemo(
    () => (undispatched?.orders || []).filter((o) => o.eligible),
    [undispatched]
  );

  /* ------------------------------------------------------------- sign in */
  if (!token) {
    return (
      <div style={styles.gate}>
        <form style={styles.gateCard} onSubmit={signIn}>
          <div style={styles.gateMark}>DX</div>
          <h1 style={styles.gateTitle}>DashXera</h1>
          <p style={styles.gateSub}>
            Operations console for EVOS Data Services. Sign in with your admin account —
            the same username and password used across the Evoxera ecosystem.
          </p>
          <input
            style={styles.input}
            autoComplete="username"
            placeholder="Username or email"
            value={identifierDraft}
            onChange={(e) => setIdentifierDraft(e.target.value)}
          />
          <input
            style={styles.input}
            type="password"
            autoComplete="current-password"
            placeholder="Password"
            value={passwordDraft}
            onChange={(e) => setPasswordDraft(e.target.value)}
          />
          <button style={styles.primaryBtn} type="submit" disabled={loginBusy}>
            {loginBusy ? "Signing in…" : "Sign in"}
          </button>
          {loginError && <div style={styles.gateError}>{loginError}</div>}
          <p style={styles.gateFoot}>
            Access is limited to active admin agents. Ask an existing admin to add you if
            your account isn't recognized.
          </p>
        </form>
      </div>
    );
  }

  const counts = summary?.orders;
  const fin = summary?.financials;

  return (
    <div style={styles.shell}>
      {/* ------------------------------------------------------- sidebar */}
      {navOpen && <div style={styles.navScrim} onClick={() => setNavOpen(false)} />}
      <aside style={styles.sidebar(navOpen)}>
        <div style={styles.sidebarTop}>
          <span style={styles.mark}>DX</span>
          <div>
            <div style={styles.sidebarBrand}>DashXera</div>
            <div style={styles.sidebarSub}>EVOS Data Services</div>
          </div>
        </div>

        <nav style={styles.nav}>
          {SECTIONS.map((item) => {
            const badge =
              item.id === "undispatched" ? counts?.undispatched
              : item.id === "incidents" ? incidents?.counts?.open
              : null;
            return (
              <button
                key={item.id}
                style={styles.navBtn(section === item.id)}
                onClick={() => goTo(item.id)}
              >
                <span style={styles.navIcon}>{item.icon}</span>
                <span style={{ flex: 1, textAlign: "left" }}>{item.label}</span>
                {badge ? <span style={styles.navBadge}>{badge}</span> : null}
              </button>
            );
          })}
        </nav>

        {adminUser?.display_name && (
          <div style={styles.signedInAs}>Signed in as {adminUser.display_name}</div>
        )}
        <button style={styles.signOutBtn} onClick={signOut}>Sign out</button>
      </aside>

      {/* ---------------------------------------------------------- main */}
      <main style={styles.main}>
        <header style={styles.header}>
          <div style={styles.headerLeft}>
            <button style={styles.navToggle} onClick={() => setNavOpen(true)}>☰</button>
            <div>
              <h1 style={styles.title}>
                {SECTIONS.find((s) => s.id === section)?.label}
              </h1>
              <p style={styles.subtitle}>
                {lastSync ? `Synced ${lastSync.toLocaleTimeString("en-GH")}` : "Loading…"}
                {loading && " · refreshing"}
              </p>
            </div>
          </div>

          <div style={styles.rangeGroup}>
            {WINDOWS.map((w) => (
              <button key={w} style={styles.rangeBtn(w === days)} onClick={() => setDays(w)}>
                {w}d
              </button>
            ))}
          </div>
        </header>

        {error && <div style={styles.errorBar}>{error}</div>}

        {/* ======================================================= OVERVIEW */}
        {section === "overview" && (
          <>
            {attention?.items?.length > 0 && (
              <div style={styles.attentionStack}>
                {attention.items.map((item, i) => (
                  <button key={i} style={styles.attentionRow} onClick={() => goTo(item.link)}>
                    <span style={styles.attentionDot} />
                    <span style={{ flex: 1, textAlign: "left" }}>
                      <strong style={{ color: "#fecaca" }}>{item.title}</strong>
                      <span style={styles.attentionDetail}>{item.detail}</span>
                    </span>
                    <span style={styles.attentionGo}>Open</span>
                  </button>
                ))}
              </div>
            )}

            <div style={styles.kpiGrid}>
              <Kpi label="Total orders" value={counts?.total} tone="#e9e5f6"
                   foot={`Last ${days} days`} />
              <Kpi label="Successful" value={counts?.successful} tone="#4ade80"
                   foot={`${summary?.quality?.success_rate ?? 0}% of settled`} />
              <Kpi label="Processing" value={counts?.processing} tone="#c8ff3e"
                   foot={counts?.awaiting_payment
                     ? `${counts.awaiting_payment} awaiting payment`
                     : "All payments settled"} />
              <Kpi label="Failed" value={counts?.failed} tone="#f87171"
                   foot={fin ? `${cedi(fin.failed_value)} affected` : ""} />
            </div>

            <div style={styles.kpiGrid}>
              <Kpi label="Total sold" value={fin && cedi(fin.total_sold)} tone="#e9e5f6"
                   foot={`${fin?.paid_orders ?? 0} paid orders`} small />
              <Kpi label="Base cost" value={fin && cedi(fin.total_base_cost)} tone="#b4acd0"
                   foot={fin?.estimated_base_cost
                     ? `${cedi(fin.estimated_base_cost)} estimated`
                     : "All recorded"} small />
              <Kpi label="Gross margin" value={fin && cedi(fin.gross_margin)}
                   tone={fin && fin.gross_margin >= 0 ? "#4ade80" : "#f87171"}
                   foot={fin ? `${fin.margin_pct}% of takings` : ""} small />
              <Kpi label="Paid / undispatched" value={counts?.undispatched}
                   tone={counts?.undispatched ? "#fb923c" : "#9189b5"}
                   foot={fin ? cedi(fin.undispatched_value) : ""} small />
            </div>

            <Panel title="Provider health"
                   note="Balances shown only where the provider publishes one">
              <ProviderTable providers={providers} />
            </Panel>

            <Panel title="Sold and base cost by day">
              <Chart series={summary?.series || []} />
            </Panel>

            <Panel title="Ecosystem sales">
              <EcosystemGrid ecosystem={ecosystem} />
            </Panel>
          </>
        )}

        {/* ===================================================== FINANCIALS */}
        {section === "financials" && fin && (
          <>
            <div style={styles.explainer}>
              Three different numbers. <strong style={{ color: "#e9e5f6" }}>Sold</strong> is what
              the customer was charged. <strong style={{ color: "#e9e5f6" }}>Base cost</strong> is
              what the bundle cost us. <strong style={{ color: "#e9e5f6" }}>Agent price</strong> is
              the agent's tier price. They are never substituted for one another.
            </div>

            <Panel title={`Selected period — last ${days} days`}>
              <Row label="Total sold" hint="SUM of orders.price, excluding abandoned checkouts"
                   value={cedi(fin.total_sold)} tone="#e9e5f6" big />
              <Row label="Total base cost" hint="Recorded historical cost plus estimate for the gap"
                   value={cedi(fin.total_base_cost)} tone="#b4acd0" />
              <Divider />
              <Row label="Gross margin" value={cedi(fin.gross_margin)}
                   tone={fin.gross_margin >= 0 ? "#4ade80" : "#f87171"}
                   hint={`${fin.margin_pct}% of takings`} big />
            </Panel>

            <Panel title="Cost breakdown"
                   note="Recorded and estimated are kept apart on purpose">
              <Row label="Recorded base cost" value={cedi(fin.recorded_base_cost)} tone="#d9d4ec"
                   hint={`${fin.cost_coverage.orders_with_recorded_cost} orders carry their own historical cost`} />
              <Row label="Estimated base cost" value={cedi(fin.estimated_base_cost)} tone="#fbbf24"
                   hint={`${fin.cost_coverage.orders_without_recorded_cost} orders priced at today's cost list`} />
              <Divider />
              <Row label="Margin on recorded orders only" value={cedi(fin.recorded_margin)}
                   tone="#4ade80" hint="The figure grounded entirely in history" />
              {fin.cost_coverage.orders_without_recorded_cost > 0 && (
                <div style={styles.caveat}>
                  {fin.cost_coverage.coverage_pct}% of paid orders carry a recorded cost.
                  {" "}{fin.cost_coverage.note}
                </div>
              )}
            </Panel>

            <Panel title="Averages and split">
              <Row label="Average selling price" value={cedi(fin.average_sold)} tone="#d9d4ec" />
              <Row label="Average base price" value={cedi(fin.average_base_cost)} tone="#b4acd0"
                   hint="Across orders with a recorded cost" />
              <Divider />
              <Row label="Agent sales" value={cedi(fin.agent_sold)} tone="#a78bfa"
                   hint={`${fin.agent_orders} orders · agent price total ${cedi(fin.agent_price_total)}`} />
              <Row label="Direct sales" value={cedi(fin.direct_sold)} tone="#c8ff3e"
                   hint={`${fin.direct_orders} orders`} />
            </Panel>

            <Panel title="Sold and base cost by day">
              <Chart series={summary?.series || []} />
            </Panel>
          </>
        )}

        {/* ========================================================= AGENTS */}
        {section === "agents" && (
          <>
            <div style={styles.kpiGrid}>
              <Kpi label="Agents with sales" value={agents?.agent_count} tone="#a78bfa" small />
              <Kpi label="Sold through agents" value={agents && cedi(agents.total_agent_sold)}
                   tone="#e9e5f6" small />
              <Kpi label="Agent price total" value={agents && cedi(agents.total_agent_price)}
                   tone="#b4acd0" small foot="What agents were charged" />
            </div>

            <Panel title="Agent sales" note={agents?.note}>
              {agents?.agents?.length ? (
                <TableWrap>
                  <thead>
                    <tr>
                      <Th>Agent</Th>
                      <ThNum>Orders</ThNum>
                      <ThNum>Sold</ThNum>
                      <ThNum>Agent price</ThNum>
                      <ThNum>Base cost</ThNum>
                      <ThNum>Margin</ThNum>
                      <ThNum>Success</ThNum>
                    </tr>
                  </thead>
                  <tbody>
                    {agents.agents.map((a) => (
                      <tr key={a.agent_id}>
                        <Td>
                          <div style={styles.strong}>{a.agent_name}</div>
                          <div style={styles.dim}>
                            {a.agent_username ? `@${a.agent_username} · ` : ""}#{a.agent_id}
                          </div>
                        </Td>
                        <TdNum>{a.orders}</TdNum>
                        <TdNum>{cedi(a.sold)}</TdNum>
                        <TdNum style={{ color: "#a78bfa" }}>{cedi(a.agent_price_total)}</TdNum>
                        <TdNum style={{ color: "#b4acd0" }}>
                          {cedi(a.recorded_base_cost)}
                          {a.cost_coverage_pct < 100 && (
                            <div style={styles.dim}>{a.cost_coverage_pct}% recorded</div>
                          )}
                        </TdNum>
                        <TdNum style={{ color: a.margin_vs_recorded_cost >= 0 ? "#4ade80" : "#f87171" }}>
                          {cedi(a.margin_vs_recorded_cost)}
                        </TdNum>
                        <TdNum>
                          {a.successful_orders}
                          {a.failed_orders > 0 && (
                            <span style={{ color: "#f87171" }}> / {a.failed_orders} failed</span>
                          )}
                        </TdNum>
                      </tr>
                    ))}
                  </tbody>
                </TableWrap>
              ) : (
                <Empty>No agent sales in the last {days} days. Direct sales appear under Orders.</Empty>
              )}
            </Panel>
          </>
        )}

        {/* ========================================================= ORDERS */}
        {section === "orders" && (
          <>
            <div style={styles.filterBar}>
              <select
                style={styles.select}
                value={statusFilter}
                onChange={(e) => { setStatusFilter(e.target.value); setOrdersPage(1); }}
              >
                <option value="">All statuses</option>
                <option value="successful">Successful</option>
                <option value="processing">Processing</option>
                <option value="paid">Paid</option>
                <option value="failed">Failed</option>
                <option value="pending_payment">Awaiting payment</option>
              </select>
              <input
                style={{ ...styles.input, margin: 0, flex: 1, minWidth: 160 }}
                placeholder="Search reference or phone"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") { setOrdersPage(1); load(); } }}
              />
            </div>

            <Panel title={`${orders?.total ?? 0} orders`}>
              {orders?.orders?.length ? (
                <>
                  <TableWrap min={960}>
                    <thead>
                      <tr>
                        <Th>Order</Th>
                        <Th>Date</Th>
                        <Th>Customer</Th>
                        <Th>Agent</Th>
                        <Th>Product</Th>
                        <ThNum>Sold</ThNum>
                        <ThNum>Base</ThNum>
                        <ThNum>Agent price</ThNum>
                        <Th>Status</Th>
                        <Th>Provider</Th>
                      </tr>
                    </thead>
                    <tbody>
                      {orders.orders.map((o) => (
                        <tr key={o.id}>
                          <Td>
                            <div style={styles.strong}>#{o.id}</div>
                            <div style={styles.ref}>{o.datamart_ref || o.paystack_ref || "—"}</div>
                          </Td>
                          <Td><span style={styles.dim}>{when(o.created_at)}</span></Td>
                          <Td>{o.customer || "—"}</Td>
                          <Td>
                            {o.agent_name
                              ? <span style={{ color: "#a78bfa" }}>{o.agent_name}</span>
                              : <span style={styles.dim}>Direct</span>}
                          </Td>
                          <Td>{o.network} {o.bundle}</Td>
                          <TdNum>{cedi(o.price)}</TdNum>
                          <TdNum style={{ color: "#b4acd0" }}>
                            {o.base_cost_source === "missing" ? "—" : cedi(o.base_cost)}
                            {o.base_cost_source === "estimated" && (
                              <div style={styles.estTag}>estimated</div>
                            )}
                          </TdNum>
                          <TdNum style={{ color: "#a78bfa" }}>
                            {o.agent_price ? cedi(o.agent_price) : "—"}
                          </TdNum>
                          <Td>
                            <StatusPill status={o.status} />
                            {o.last_error && (
                              <div style={styles.rowError} title={o.last_error}>
                                {o.last_error.slice(0, 48)}
                              </div>
                            )}
                          </Td>
                          <Td>
                            {o.provider || "—"}
                            {o.provider && !o.provider_recorded && (
                              <div style={styles.estTag}>inferred</div>
                            )}
                          </Td>
                        </tr>
                      ))}
                    </tbody>
                  </TableWrap>
                  <Pager page={ordersPage} setPage={setOrdersPage}
                         total={orders.total} hasMore={orders.has_more} />
                </>
              ) : (
                <Empty>No orders match this filter in the last {days} days.</Empty>
              )}
            </Panel>
          </>
        )}

        {/* =================================================== UNDISPATCHED */}
        {section === "undispatched" && (
          <>
            <div style={styles.explainer}>
              Payment was taken but no provider reference was ever written. This is the
              money-and-customer queue. Only eligible rows can be reprocessed — an order that
              already has a provider reference or is already fulfilled is never re-sent.
            </div>

            {selected.length > 0 && (
              <div style={styles.bulkBar}>
                <span>{selected.length} selected</span>
                <select
                  style={styles.selectSmall}
                  value={bulkProvider}
                  onChange={(e) => setBulkProvider(e.target.value)}
                  title="Provider to dispatch all selected orders through — leave on Auto to use each order's own priority chain"
                >
                  <option value="">Auto (priority chain)</option>
                  {(providers?.providers || []).map((p) => (
                    <option key={p.provider} value={p.provider}>{p.provider}</option>
                  ))}
                </select>
                <button style={styles.primaryBtnSmall} onClick={reprocessSelected}>
                  Reprocess selected
                </button>
                <button style={styles.linkBtn} onClick={() => setSelected([])}>Clear</button>
              </div>
            )}

            <Panel title={`${undispatched?.total ?? 0} orders · ${undispatched?.eligible_on_page ?? 0} eligible on this page`}
                   note={undispatched ? `${cedi(undispatched.value_on_page)} eligible value on this page` : ""}>
              {undispatched?.orders?.length ? (
                <>
                  <TableWrap min={1000}>
                    <thead>
                      <tr>
                        <Th>
                          <input
                            type="checkbox"
                            checked={eligible.length > 0 && selected.length === eligible.length}
                            onChange={(e) => setSelected(e.target.checked ? eligible.map((o) => o.id) : [])}
                          />
                        </Th>
                        <Th>Order</Th>
                        <Th>Customer</Th>
                        <Th>Product</Th>
                        <ThNum>Paid</ThNum>
                        <ThNum>Base</ThNum>
                        <Th>Status</Th>
                        <Th>Provider tried</Th>
                        <ThNum>Age</ThNum>
                        <Th>Action</Th>
                      </tr>
                    </thead>
                    <tbody>
                      {undispatched.orders.map((o) => {
                        const busy = busyIds.includes(o.id);
                        return (
                          <tr key={o.id} style={o.eligible ? undefined : styles.rowMuted}>
                            <Td>
                              <input
                                type="checkbox"
                                disabled={!o.eligible}
                                checked={selected.includes(o.id)}
                                onChange={() => toggle(o.id)}
                              />
                            </Td>
                            <Td>
                              <div style={styles.strong}>#{o.id}</div>
                              <div style={styles.ref}>{o.paystack_ref}</div>
                              {o.wallet_order && <div style={styles.walletTag}>agent wallet</div>}
                            </Td>
                            <Td>
                              {o.customer || "—"}
                              {o.agent_name && (
                                <div style={{ ...styles.dim, color: "#a78bfa" }}>{o.agent_name}</div>
                              )}
                            </Td>
                            <Td>{o.network} {o.bundle}</Td>
                            <TdNum>{cedi(o.price)}</TdNum>
                            <TdNum style={{ color: "#b4acd0" }}>
                              {o.base_cost_source === "missing" ? "—" : cedi(o.base_cost)}
                            </TdNum>
                            <Td>
                              <StatusPill status={o.status} />
                              <div style={styles.dim}>{o.payment_state}</div>
                            </Td>
                            <Td>
                              {o.provider_attempted || "—"}
                              {o.last_error && (
                                <div style={styles.rowError} title={o.last_error}>
                                  {o.last_error.slice(0, 44)}
                                </div>
                              )}
                              {o.reprocess_count > 0 && (
                                <div style={styles.dim}>
                                  {o.reprocess_count} attempt{o.reprocess_count === 1 ? "" : "s"}
                                </div>
                              )}
                            </Td>
                            <TdNum>{o.age_hours}h</TdNum>
                            <Td>
                              {o.eligible ? (
                                <div style={styles.reprocessCell}>
                                  <select
                                    style={styles.selectSmall}
                                    value={providerChoice[o.id] || ""}
                                    disabled={busy}
                                    onChange={(e) =>
                                      setProviderChoice((prev) => ({ ...prev, [o.id]: e.target.value }))
                                    }
                                    title="Reassign the provider this order dispatches through — writes to orders.dispatch_provider on success"
                                  >
                                    <option value="">Auto ({o.network} chain)</option>
                                    {(providers?.providers || []).map((p) => (
                                      <option key={p.provider} value={p.provider}>{p.provider}</option>
                                    ))}
                                  </select>
                                  <button style={styles.rowBtn(busy)} disabled={busy}
                                          onClick={() => reprocess(o.id)}>
                                    {busy ? "Sending…" : "Reprocess"}
                                  </button>
                                </div>
                              ) : (
                                <span style={styles.dim} title={o.eligibility_reason}>
                                  {o.eligibility_reason}
                                </span>
                              )}
                            </Td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </TableWrap>
                  <Pager page={undispatchedPage} setPage={setUndispatchedPage}
                         total={undispatched.total}
                         hasMore={undispatched.total > undispatchedPage * PAGE_SIZE} />
                </>
              ) : (
                <Empty>
                  Nothing stuck. Every paid order in the last {days} days reached a provider.
                </Empty>
              )}
            </Panel>
          </>
        )}

        {/* ====================================================== PROVIDERS */}
        {section === "providers" && (
          <>
            <Panel title="Provider health"
                   note="Health is derived from dispatch outcomes and captured failures">
              <ProviderTable providers={providers} detailed />
            </Panel>

            <Panel title="Paystack">
              {providers?.paystack && (
                <>
                  <Row label="Status"
                       value={providers.paystack.health}
                       tone={(HEALTH[providers.paystack.health] || HEALTH.UNKNOWN).color} />
                  {providers.paystack.balance_available ? (
                    <Row label="Balance" value={cedi(providers.paystack.balance)}
                         tone={providers.paystack.low ? "#f87171" : "#4ade80"}
                         hint={providers.paystack.low
                           ? `Below the ${cedi(providers.paystack.threshold)} floor`
                           : providers.paystack.note} />
                  ) : (
                    <Row label="Balance" value="Unavailable" tone="#9189b5"
                         hint={providers.paystack.reason} />
                  )}
                  <Row label="Open incidents" value={providers.paystack.open_incidents}
                       tone={providers.paystack.open_incidents ? "#fbbf24" : "#9189b5"} />
                </>
              )}
            </Panel>

            {providers?.unattributed_orders > 0 && (
              <div style={styles.caveat}>
                {providers.unattributed_orders} orders in this window predate provider
                attribution. {providers.unattributed_note}
              </div>
            )}
          </>
        )}

        {/* ====================================================== INCIDENTS */}
        {section === "incidents" && (
          <Panel title={`${incidents?.counts?.open ?? 0} open incidents`}
                 note={incidents?.capture_note}>
            {incidents?.incidents?.length ? (
              <div style={styles.incidentList}>
                {incidents.incidents.map((inc) => (
                  <div key={inc.id} style={styles.incident(inc.severity)}>
                    <div style={styles.incidentHead}>
                      <span style={styles.incidentKind(inc.severity)}>
                        {KIND_LABELS[inc.kind] || inc.kind}
                      </span>
                      <span style={styles.dim}>{inc.provider}</span>
                      {inc.occurrences > 1 && (
                        <span style={styles.incidentCount}>×{inc.occurrences}</span>
                      )}
                      <span style={{ ...styles.dim, marginLeft: "auto" }}>
                        {timeAgo(inc.last_seen_at)}
                      </span>
                    </div>
                    <div style={styles.incidentMessage}>{inc.message}</div>
                    <div style={styles.incidentFoot}>
                      {inc.order_id ? `Order ${inc.order_id}` : "No order attached"}
                      {" · first seen "}{timeAgo(inc.first_seen_at)}
                      <button style={styles.linkBtn} onClick={() => resolveIncident(inc.id)}>
                        Mark handled
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <Empty>
                No provider or payment failures captured in the last {days} days.
              </Empty>
            )}
          </Panel>
        )}

        {/* ====================================================== ECOSYSTEM */}
        {section === "ecosystem" && (
          <Panel title="Ecosystem sales"
                 note={ecosystem?.includes_estimates
                   ? "Some figures are estimated where the source table has no amount column"
                   : ""}>
            <EcosystemGrid ecosystem={ecosystem} detailed />
            <div style={styles.totalLine}>
              Connected products total{" "}
              <strong style={{ color: "#e9e5f6" }}>{cedi(ecosystem?.total_revenue)}</strong>
            </div>
          </Panel>
        )}

        {/* ========================================================== AUDIT */}
        {section === "audit" && (
          <Panel title="Reprocessing and audit trail"
                 note="Every admin action against an order is recorded here">
            {audit?.actions?.length ? (
              <TableWrap min={860}>
                <thead>
                  <tr>
                    <Th>When</Th>
                    <Th>Admin</Th>
                    <Th>Action</Th>
                    <Th>Order</Th>
                    <Th>Status change</Th>
                    <Th>Provider</Th>
                    <Th>Outcome</Th>
                  </tr>
                </thead>
                <tbody>
                  {audit.actions.map((a) => (
                    <tr key={a.id}>
                      <Td><span style={styles.dim}>{when(a.created_at)}</span></Td>
                      <Td>{a.actor || "—"}</Td>
                      <Td>{a.action}</Td>
                      <Td>{a.order_id ? `#${a.order_id}` : "—"}</Td>
                      <Td>
                        {a.previous_status || "—"}
                        {a.new_status && a.new_status !== a.previous_status
                          ? ` → ${a.new_status}` : ""}
                      </Td>
                      <Td>
                        {a.provider || "—"}
                        {a.provider_ref && <div style={styles.ref}>{a.provider_ref}</div>}
                      </Td>
                      <Td>
                        <span style={styles.outcomePill(a.outcome)}>{a.outcome}</span>
                        {a.detail && a.outcome !== "success" && (
                          <div style={styles.rowError} title={a.detail}>
                            {a.detail.slice(0, 60)}
                          </div>
                        )}
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </TableWrap>
            ) : (
              <Empty>No admin actions recorded in the last {days} days.</Empty>
            )}
          </Panel>
        )}
      </main>

      {toast && (
        <div style={styles.toast(toast.tone)} onClick={() => setToast(null)}>
          {toast.message}
        </div>
      )}
    </div>
  );
}

/* ================================ pieces ================================ */

function Kpi({ label, value, tone, foot, small }) {
  return (
    <div style={styles.kpi}>
      <div style={styles.kpiLabel}>{label}</div>
      <div style={{ ...(small ? styles.kpiValueSmall : styles.kpiValue), color: tone }}>
        {value === undefined || value === null ? "—" : value}
      </div>
      {foot && <div style={styles.kpiFoot}>{foot}</div>}
    </div>
  );
}

function Panel({ title, note, children }) {
  return (
    <section style={styles.panel}>
      <div style={styles.panelHead}>
        <h2 style={styles.panelTitle}>{title}</h2>
        {note && <span style={styles.panelNote}>{note}</span>}
      </div>
      {children}
    </section>
  );
}

function Row({ label, value, tone, hint, big }) {
  return (
    <div style={styles.row}>
      <div>
        <div style={styles.rowLabel}>{label}</div>
        {hint && <div style={styles.rowHint}>{hint}</div>}
      </div>
      <div style={{ ...(big ? styles.rowValueBig : styles.rowValue), color: tone }}>
        {value ?? "—"}
      </div>
    </div>
  );
}

const Divider = () => <div style={styles.divider} />;
const Th = ({ children }) => <th style={styles.th}>{children}</th>;
const ThNum = ({ children }) => <th style={styles.thNum}>{children}</th>;
const Td = ({ children, style }) => <td style={{ ...styles.td, ...style }}>{children}</td>;
const TdNum = ({ children, style }) => <td style={{ ...styles.tdNum, ...style }}>{children}</td>;
const Empty = ({ children }) => <div style={styles.empty}>{children}</div>;

function TableWrap({ children, min = 640 }) {
  return (
    <div style={styles.tableWrap}>
      <table style={{ ...styles.table, minWidth: min }}>{children}</table>
    </div>
  );
}

function StatusPill({ status }) {
  const map = {
    successful: "#4ade80",
    failed: "#f87171",
    processing: "#c8ff3e",
    paid: "#c8ff3e",
    pending_payment: "#b4acd0",
  };
  const color = map[status] || "#b4acd0";
  return (
    <span style={{ ...styles.pill, color, background: `${color}1f` }}>{status}</span>
  );
}

function Pager({ page, setPage, total, hasMore }) {
  return (
    <div style={styles.pager}>
      <button style={styles.pagerBtn(page <= 1)} disabled={page <= 1}
              onClick={() => setPage(page - 1)}>
        Previous
      </button>
      <span style={styles.dim}>Page {page}{total ? ` · ${total} total` : ""}</span>
      <button style={styles.pagerBtn(!hasMore)} disabled={!hasMore}
              onClick={() => setPage(page + 1)}>
        Next
      </button>
    </div>
  );
}

function ProviderTable({ providers, detailed }) {
  if (!providers?.providers?.length) {
    return <Empty>No providers configured in provider_routes.</Empty>;
  }
  return (
    <TableWrap min={detailed ? 820 : 620}>
      <thead>
        <tr>
          <Th>Provider</Th>
          <Th>Health</Th>
          <ThNum>Orders</ThNum>
          <ThNum>Failed</ThNum>
          {detailed && <Th>Last success</Th>}
          <Th>Balance</Th>
        </tr>
      </thead>
      <tbody>
        {providers.providers.map((p) => {
          const tone = HEALTH[p.health] || HEALTH.UNKNOWN;
          return (
            <tr key={p.provider}>
              <Td><span style={styles.strong}>{p.provider}</span></Td>
              <Td>
                <span style={{ ...styles.pill, color: tone.color, background: tone.bg }}>
                  {p.health}
                </span>
                {p.latest_low_balance && (
                  <div style={styles.rowError}>{p.latest_low_balance.slice(0, 60)}</div>
                )}
              </Td>
              <TdNum>{p.orders}</TdNum>
              <TdNum style={{ color: p.failed_orders ? "#f87171" : "#9189b5" }}>
                {p.failed_orders}
                {p.orders > 0 && <div style={styles.dim}>{p.failure_rate_pct}%</div>}
              </TdNum>
              {detailed && (
                <Td><span style={styles.dim}>{timeAgo(p.last_success_at)}</span></Td>
              )}
              <Td>
                <span style={styles.dim}>Not published</span>
              </Td>
            </tr>
          );
        })}
        {providers.paystack && (
          <tr>
            <Td><span style={styles.strong}>PAYSTACK</span></Td>
            <Td>
              <span style={{
                ...styles.pill,
                color: (HEALTH[providers.paystack.health] || HEALTH.UNKNOWN).color,
                background: (HEALTH[providers.paystack.health] || HEALTH.UNKNOWN).bg,
              }}>
                {providers.paystack.health}
              </span>
            </Td>
            <TdNum>—</TdNum>
            <TdNum>{providers.paystack.open_incidents || 0}</TdNum>
            {detailed && <Td><span style={styles.dim}>—</span></Td>}
            <Td>
              {providers.paystack.balance_available ? (
                <span style={{ color: providers.paystack.low ? "#f87171" : "#4ade80" }}>
                  {cedi(providers.paystack.balance)}
                </span>
              ) : (
                <span style={styles.dim}>Unavailable</span>
              )}
            </Td>
          </tr>
        )}
      </tbody>
    </TableWrap>
  );
}

function EcosystemGrid({ ecosystem, detailed }) {
  const meta = [
    ["evosdata", "EVOSDATA", "#c8ff3e", "orders"],
    ["evosgpt", "EVOSGPT", "#a78bfa", "upgrades"],
    ["evoshub", "EVOSHUB", "#fbbf24", "projects"],
    ["xera", "XERA", "#34d399", "purchases"],
  ];
  return (
    <div style={styles.productGrid}>
      {meta.map(([key, name, accent, unit]) => {
        const data = ecosystem?.products?.[key];
        if (!data?.available) {
          return (
            <div key={key} style={styles.product}>
              <div style={{ ...styles.productName, color: accent }}>{name}</div>
              <div style={styles.productOffline}>
                {data?.status_label || "Not connected"}
              </div>
              {detailed && data?.reason && (
                <div style={styles.kpiFoot}>{data.reason}</div>
              )}
            </div>
          );
        }
        return (
          <div key={key} style={styles.product}>
            <div style={{ ...styles.productName, color: accent }}>{name}</div>
            <div style={styles.productValue}>{cedi(data.revenue)}</div>
            <div style={styles.kpiFoot}>
              {data.count} {unit}
              {data.pending ? ` · ${data.pending} pending` : ""}
            </div>
            {data.estimated && (
              <div style={styles.estTag}>
                estimated{detailed && data.estimate_reason ? ` — ${data.estimate_reason}` : ""}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

/** Sold vs base cost by day. No charting dependency for two lines. */
function Chart({ series }) {
  if (!series.length) return <Empty>No data in this window.</Empty>;
  const width = 700;
  const height = 120;
  const max = Math.max(...series.map((p) => p.sold), 1);
  const step = series.length > 1 ? width / (series.length - 1) : width;
  const line = (key) =>
    series
      .map((p, i) => `${(i * step).toFixed(1)},${(height - (p[key] / max) * height).toFixed(1)}`)
      .join(" ");

  const peak = series.reduce((a, b) => (b.sold > a.sold ? b : a), series[0]);

  return (
    <div>
      <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" style={styles.chartSvg}>
        <polyline points={line("sold")} fill="none" stroke="#c8ff3e" strokeWidth="2"
                  vectorEffect="non-scaling-stroke" />
        <polyline points={line("base_cost")} fill="none" stroke="#9189b5" strokeWidth="1.5"
                  strokeDasharray="4 4" vectorEffect="non-scaling-stroke" />
      </svg>
      <div style={styles.chartLegend}>
        <span><span style={{ ...styles.swatch, background: "#c8ff3e" }} />Sold</span>
        <span><span style={{ ...styles.swatch, background: "#9189b5" }} />Base cost</span>
        <span style={{ marginLeft: "auto" }}>Best day: {peak.date} · {cedi(peak.sold)}</span>
      </div>
    </div>
  );
}

/* ================================ styles ================================ */

const card = {
  background: "rgba(22,17,38,0.72)",
  border: "1px solid rgba(200,255,62,0.12)",
  borderRadius: 14,
};

const styles = {
  shell: {
    display: "flex",
    minHeight: "100vh",
    color: "#e9e5f6",
    fontFamily: "ui-sans-serif, system-ui, Arial",
  },

  gate: { minHeight: "70vh", display: "flex", alignItems: "center", justifyContent: "center", padding: 20 },
  gateCard: { ...card, padding: 28, width: "100%", maxWidth: 380, display: "flex", flexDirection: "column", gap: 12 },
  gateMark: { width: 44, height: 44, borderRadius: 12, display: "grid", placeItems: "center",
    background: "linear-gradient(135deg,#c8ff3e,#8b5cf6)", color: "#0a0814", fontWeight: 900, fontSize: 16 },
  gateTitle: { margin: 0, fontSize: 24, fontWeight: 800, letterSpacing: "-0.5px" },
  gateSub: { margin: 0, fontSize: 13, color: "#b4acd0", lineHeight: 1.5 },
  gateError: { fontSize: 13, color: "#f87171" },
  gateFoot: { margin: "4px 0 0", fontSize: 11.5, color: "#7a6fa3", lineHeight: 1.5 },

  input: { padding: "11px 13px", borderRadius: 10, border: "1px solid rgba(148,163,184,0.2)",
    background: "rgba(10,8,20,0.6)", color: "#e9e5f6", fontSize: 14, outline: "none" },
  selectSmall: { padding: "5px 8px", borderRadius: 8, border: "1px solid rgba(148,163,184,0.2)",
    background: "#161126", color: "#e9e5f6", fontSize: 11, minWidth: 130 },
  reprocessCell: { display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" },
  select: { padding: "10px 12px", borderRadius: 10, border: "1px solid rgba(148,163,184,0.2)",
    background: "rgba(10,8,20,0.6)", color: "#e9e5f6", fontSize: 13.5, outline: "none" },

  navScrim: { position: "fixed", inset: 0, background: "rgba(0,0,0,0.55)", zIndex: 190 },
  sidebar: (open) => ({
    position: "fixed", top: 0, left: 0, height: "100vh", width: 230, zIndex: 200,
    background: "rgba(10,8,20,0.97)", borderRight: "1px solid rgba(200,255,62,0.12)",
    display: "flex", flexDirection: "column", padding: "18px 12px",
    transform: open ? "translateX(0)" : "translateX(-100%)",
    transition: "transform 0.25s ease",
  }),
  sidebarTop: { display: "flex", alignItems: "center", gap: 10, padding: "0 6px 16px" },
  mark: { width: 32, height: 32, borderRadius: 9, display: "grid", placeItems: "center",
    background: "linear-gradient(135deg,#c8ff3e,#8b5cf6)", color: "#0a0814", fontWeight: 900, fontSize: 13 },
  sidebarBrand: { fontWeight: 800, fontSize: 15, letterSpacing: "-0.3px" },
  sidebarSub: { fontSize: 10.5, color: "#7a6fa3" },
  nav: { display: "flex", flexDirection: "column", gap: 2, flex: 1, overflowY: "auto" },
  navBtn: (active) => ({
    display: "flex", alignItems: "center", gap: 10, padding: "10px 11px", borderRadius: 9,
    border: "none", cursor: "pointer", fontSize: 13.5, width: "100%",
    background: active ? "rgba(200,255,62,0.12)" : "transparent",
    color: active ? "#c8ff3e" : "#b4acd0", fontWeight: active ? 700 : 500,
  }),
  navIcon: { width: 16, textAlign: "center", fontSize: 13, opacity: 0.8 },
  navBadge: { fontSize: 10.5, fontWeight: 800, color: "#fb923c",
    background: "rgba(249,115,22,0.16)", padding: "2px 7px", borderRadius: 6 },
  signedInAs: { marginTop: 10, padding: "0 6px", fontSize: 11, color: "#7a6fa3" },
  signOutBtn: { marginTop: 6, padding: "10px 12px", borderRadius: 9, cursor: "pointer",
    fontSize: 13, fontWeight: 600, background: "rgba(148,163,184,0.08)",
    border: "1px solid rgba(148,163,184,0.14)", color: "#b4acd0" },

  main: { flex: 1, padding: "18px 16px 80px", display: "flex", flexDirection: "column",
    gap: 18, maxWidth: 1280, margin: "0 auto", width: "100%", minWidth: 0 },

  header: { display: "flex", flexWrap: "wrap", gap: 12, justifyContent: "space-between", alignItems: "flex-end" },
  headerLeft: { display: "flex", alignItems: "center", gap: 12 },
  navToggle: { width: 38, height: 38, borderRadius: 10, cursor: "pointer", fontSize: 16,
    background: "rgba(148,163,184,0.08)", border: "1px solid rgba(148,163,184,0.16)", color: "#b4acd0" },
  title: { margin: 0, fontSize: 22, fontWeight: 800, letterSpacing: "-0.5px" },
  subtitle: { margin: "4px 0 0", fontSize: 11.5, color: "#9189b5" },

  rangeGroup: { display: "flex", gap: 4, padding: 4, borderRadius: 11,
    background: "rgba(22,17,38,0.8)", border: "1px solid rgba(148,163,184,0.12)" },
  rangeBtn: (active) => ({ padding: "6px 12px", borderRadius: 8, border: "none", cursor: "pointer",
    fontSize: 13, fontWeight: 700,
    background: active ? "rgba(200,255,62,0.16)" : "transparent",
    color: active ? "#c8ff3e" : "#9189b5" }),

  errorBar: { ...card, padding: "12px 14px", borderColor: "rgba(239,68,68,0.3)",
    background: "rgba(239,68,68,0.08)", color: "#f87171", fontSize: 13 },

  attentionStack: { display: "flex", flexDirection: "column", gap: 8 },
  attentionRow: { ...card, padding: "13px 15px", display: "flex", alignItems: "center", gap: 11,
    borderColor: "rgba(239,68,68,0.3)", background: "rgba(239,68,68,0.08)",
    cursor: "pointer", width: "100%", fontSize: 13.5, color: "#fecaca" },
  attentionDot: { width: 7, height: 7, borderRadius: "50%", background: "#f87171", flexShrink: 0 },
  attentionDetail: { display: "block", fontSize: 12, color: "#fca5a5", marginTop: 3 },
  attentionGo: { fontSize: 12, fontWeight: 700, color: "#f87171" },

  kpiGrid: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 12 },
  kpi: { ...card, padding: "15px 15px 13px" },
  kpiLabel: { fontSize: 11.5, color: "#9189b5", fontWeight: 600 },
  kpiValue: { fontSize: 30, fontWeight: 800, letterSpacing: "-1px", marginTop: 6, lineHeight: 1 },
  kpiValueSmall: { fontSize: 20, fontWeight: 800, letterSpacing: "-0.5px", marginTop: 6, lineHeight: 1.15 },
  kpiFoot: { fontSize: 11, color: "#7a6fa3", marginTop: 7, lineHeight: 1.4 },

  panel: { ...card, padding: 17 },
  panelHead: { display: "flex", flexWrap: "wrap", gap: 6, justifyContent: "space-between",
    alignItems: "baseline", marginBottom: 12 },
  panelTitle: { margin: 0, fontSize: 15, fontWeight: 700, color: "#d9d4ec" },
  panelNote: { fontSize: 11.5, color: "#7a6fa3", maxWidth: 420, textAlign: "right" },

  explainer: { ...card, padding: "13px 15px", fontSize: 13, color: "#b4acd0", lineHeight: 1.6,
    borderColor: "rgba(200,255,62,0.16)" },
  caveat: { marginTop: 12, padding: "10px 12px", borderRadius: 10, fontSize: 12,
    color: "#fcd34d", background: "rgba(245,158,11,0.08)",
    border: "1px solid rgba(245,158,11,0.22)", lineHeight: 1.5 },

  row: { display: "flex", justifyContent: "space-between", alignItems: "center", padding: "9px 0", gap: 12 },
  rowLabel: { fontSize: 13.5, color: "#b4acd0", fontWeight: 600 },
  rowHint: { fontSize: 11.5, color: "#7a6fa3", marginTop: 2, maxWidth: 420, lineHeight: 1.4 },
  rowValue: { fontSize: 17, fontWeight: 700, whiteSpace: "nowrap" },
  rowValueBig: { fontSize: 25, fontWeight: 800, letterSpacing: "-0.5px", whiteSpace: "nowrap" },
  divider: { height: 1, background: "rgba(148,163,184,0.12)", margin: "6px 0" },

  filterBar: { display: "flex", gap: 8, flexWrap: "wrap" },

  tableWrap: { overflowX: "auto" },
  table: { width: "100%", borderCollapse: "collapse", fontSize: 12.5 },
  th: { textAlign: "left", padding: "10px 12px", color: "#9189b5", fontWeight: 600, fontSize: 11.5,
    borderBottom: "1px solid rgba(148,163,184,0.12)", whiteSpace: "nowrap" },
  thNum: { textAlign: "right", padding: "10px 12px", color: "#9189b5", fontWeight: 600, fontSize: 11.5,
    borderBottom: "1px solid rgba(148,163,184,0.12)", whiteSpace: "nowrap" },
  td: { padding: "10px 12px", borderBottom: "1px solid rgba(148,163,184,0.06)",
    color: "#d9d4ec", verticalAlign: "top" },
  tdNum: { padding: "10px 12px", borderBottom: "1px solid rgba(148,163,184,0.06)",
    color: "#d9d4ec", textAlign: "right", whiteSpace: "nowrap", verticalAlign: "top" },
  rowMuted: { opacity: 0.55 },

  strong: { fontWeight: 700, color: "#e9e5f6" },
  dim: { fontSize: 11, color: "#9189b5" },
  ref: { fontSize: 10.5, color: "#7a6fa3", marginTop: 2, wordBreak: "break-all", maxWidth: 150 },
  estTag: { fontSize: 10, color: "#fbbf24", marginTop: 3 },
  walletTag: { fontSize: 10, color: "#a78bfa", marginTop: 3 },
  rowError: { fontSize: 10.5, color: "#f87171", marginTop: 4, maxWidth: 170, lineHeight: 1.35 },

  pill: { display: "inline-block", padding: "3px 9px", borderRadius: 7, fontSize: 10.5, fontWeight: 700 },
  outcomePill: (outcome) => ({
    display: "inline-block", padding: "3px 9px", borderRadius: 7, fontSize: 10.5, fontWeight: 700,
    color: outcome === "success" ? "#4ade80" : outcome === "failed" ? "#f87171" : "#b4acd0",
    background: outcome === "success" ? "rgba(34,197,94,0.12)"
      : outcome === "failed" ? "rgba(239,68,68,0.12)" : "rgba(148,163,184,0.12)",
  }),

  rowBtn: (busy) => ({ padding: "6px 12px", borderRadius: 8, fontSize: 12, fontWeight: 700,
    cursor: busy ? "default" : "pointer", opacity: busy ? 0.55 : 1,
    background: "rgba(200,255,62,0.12)", border: "1px solid rgba(200,255,62,0.3)",
    color: "#c8ff3e", whiteSpace: "nowrap" }),
  primaryBtn: { padding: "12px 16px", borderRadius: 10, border: "none", cursor: "pointer",
    fontSize: 14, fontWeight: 800, background: "linear-gradient(135deg,#c8ff3e,#8fe600)", color: "#0a0814" },
  primaryBtnSmall: { padding: "7px 14px", borderRadius: 9, border: "none", cursor: "pointer",
    fontSize: 12.5, fontWeight: 700, background: "linear-gradient(135deg,#c8ff3e,#8fe600)", color: "#0a0814" },
  linkBtn: { background: "none", border: "none", color: "#c8ff3e", cursor: "pointer",
    fontSize: 11.5, fontWeight: 600, padding: 0, marginLeft: 10 },

  pager: { display: "flex", alignItems: "center", justifyContent: "space-between",
    gap: 10, marginTop: 12, flexWrap: "wrap" },
  pagerBtn: (disabled) => ({ padding: "7px 14px", borderRadius: 9, fontSize: 12.5, fontWeight: 600,
    cursor: disabled ? "default" : "pointer", opacity: disabled ? 0.4 : 1,
    background: "rgba(148,163,184,0.08)", border: "1px solid rgba(148,163,184,0.16)", color: "#b4acd0" }),

  bulkBar: { ...card, padding: "10px 14px", display: "flex", alignItems: "center", gap: 12,
    fontSize: 13, color: "#b4acd0" },

  productGrid: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 12 },
  product: { padding: 14, borderRadius: 12, background: "rgba(10,8,20,0.5)",
    border: "1px solid rgba(148,163,184,0.1)" },
  productName: { fontSize: 12, fontWeight: 800, letterSpacing: "0.3px" },
  productValue: { fontSize: 20, fontWeight: 800, marginTop: 7, color: "#e9e5f6", letterSpacing: "-0.5px" },
  productOffline: { fontSize: 15, fontWeight: 700, marginTop: 7, color: "#7a6fa3" },
  totalLine: { fontSize: 13, color: "#9189b5", marginTop: 14 },

  incidentList: { display: "flex", flexDirection: "column", gap: 9 },
  incident: (severity) => ({
    padding: "12px 14px", borderRadius: 11,
    border: `1px solid ${severity === "critical" ? "rgba(239,68,68,0.3)" : "rgba(245,158,11,0.24)"}`,
    background: severity === "critical" ? "rgba(239,68,68,0.08)" : "rgba(245,158,11,0.07)",
  }),
  incidentHead: { display: "flex", alignItems: "center", gap: 9, flexWrap: "wrap" },
  incidentKind: (severity) => ({ fontSize: 12.5, fontWeight: 800,
    color: severity === "critical" ? "#f87171" : "#fbbf24" }),
  incidentCount: { fontSize: 10.5, color: "#e9e5f6", background: "rgba(148,163,184,0.16)",
    padding: "2px 7px", borderRadius: 6, fontWeight: 700 },
  incidentMessage: { fontSize: 12.5, color: "#d9d4ec", marginTop: 7, lineHeight: 1.5, wordBreak: "break-word" },
  incidentFoot: { fontSize: 11, color: "#7a6fa3", marginTop: 8, display: "flex",
    alignItems: "center", flexWrap: "wrap" },

  chartSvg: { width: "100%", height: 120, display: "block" },
  chartLegend: { display: "flex", gap: 14, fontSize: 11, color: "#9189b5", marginTop: 8, flexWrap: "wrap" },
  swatch: { display: "inline-block", width: 10, height: 2, marginRight: 6, verticalAlign: "middle" },

  empty: { padding: "22px 16px", color: "#9189b5", fontSize: 13, textAlign: "center", lineHeight: 1.5 },

  toast: (tone) => ({ position: "fixed", left: 16, right: 16, bottom: 20, maxWidth: 480,
    margin: "0 auto", padding: "13px 16px", borderRadius: 12, cursor: "pointer", zIndex: 400,
    fontSize: 13.5, fontWeight: 600,
    background: tone === "warn" ? "rgba(239,68,68,0.94)" : "rgba(16,185,129,0.94)",
    color: "#02150f", boxShadow: "0 12px 40px rgba(0,0,0,0.5)" }),
};
