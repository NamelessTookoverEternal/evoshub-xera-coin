import { useEffect, useState, useRef } from "react";
import API, { verifyNumber } from "../api";
import { getCachedPrices, subscribePrices, refreshPrices } from "../lib/pricesStore";
import { isGhanaPhone, toGhanaPhone, GHANA_ONLY_MSG } from "../lib/ghanaPhone";

export default function Shop({ setPage } = {}) {
  const [step, setStep] = useState(1);
  const [network, setNetwork] = useState("");
  const [bundle, setBundle] = useState("");
  const [bundlePrice, setBundlePrice] = useState(0);
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState(localStorage.getItem("email") || "");
  const [prices, setPrices] = useState(getCachedPrices); // instant: saved copy / build snapshot
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [pendingMsg, setPendingMsg] = useState(""); // ← new
  const [agree, setAgree] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);
  const [verifyInfo, setVerifyInfo] = useState(null); // { checked, servable, recommendation, message }
  const [verifying, setVerifying] = useState(false);
  const [verifyTimedOut, setVerifyTimedOut] = useState(false); // watchdog: unblocks Buy if check is slow
  const [showVerifyResult, setShowVerifyResult] = useState(false); // popup stays up until the user proceeds or cancels
  const resultTimerRef = useRef(null);

  const user = JSON.parse(localStorage.getItem("user") || "{}");
  const user_id = user?.id || null;

  // ── XERA discount (hidden unless the server says it is switched on) ──
  const [xeraQuote, setXeraQuote] = useState(null);   // server answer for this bundle
  const [useXera, setUseXera] = useState(false);

  useEffect(() => {
    setUseXera(false);
    setXeraQuote(null);
    if (!user_id || !network || !bundle || !(Number(bundlePrice) > 0)) return undefined;
    let cancelled = false;
    (async () => {
      try {
        const res = await API.get("/xera-discount/quote", {
          params: { network, bundle, user_id },
          headers: { "X-User-Token": localStorage.getItem("userToken") || "" },
        });
        if (!cancelled && res.data?.enabled) setXeraQuote(res.data);
      } catch { /* quote is optional: the normal price still works */ }
    })();
    return () => { cancelled = true; };
  }, [user_id, network, bundle, bundlePrice]);

  const xeraOn = !!(useXera && xeraQuote?.eligible);
  const payAmount = xeraOn ? Number(xeraQuote.final_price) : Number(bundlePrice);

  // ── Wallet: the "scan". Asks the server if the wallet can pay (with or without the XERA discount). ──
  const [wallet, setWallet] = useState(null);          // server answer for this bundle
  const [payMethod, setPayMethod] = useState("paystack");
  const [shortPopup, setShortPopup] = useState(null);  // { balance, needed } when the wallet can't cover the order
  const [done, setDone] = useState(null);              // wallet order confirmation

  useEffect(() => {
    setWallet(null);
    if (!user_id || !network || !bundle || !(Number(bundlePrice) > 0)) return undefined;
    let cancelled = false;
    (async () => {
      try {
        const res = await API.get("/wallet/quote", {
          params: { user_id, network, bundle },
          headers: { "X-User-Token": localStorage.getItem("userToken") || "" },
        });
        if (!cancelled && res.data?.status === "ok") setWallet(res.data);
      } catch { /* no wallet info: Paystack still works */ }
    })();
    return () => { cancelled = true; };
  }, [user_id, network, bundle, bundlePrice]);

  const walletAmount = wallet ? Number(xeraOn ? (wallet.wallet_price_with_xera ?? wallet.wallet_price) : wallet.wallet_price) : 0;
  const walletEnough = !!wallet && (xeraOn && wallet.enough_with_xera !== null ? wallet.enough_with_xera : wallet.enough);
  const walletBalance = wallet ? Number(wallet.balance) : 0;
  const useWallet = payMethod === "wallet" && walletEnough;

  // Pick the wallet automatically when it can pay; fall back to Paystack when it can't.
  useEffect(() => {
    setPayMethod(wallet && walletEnough ? "wallet" : "paystack");
  }, [wallet, walletEnough, xeraOn]);

  useEffect(() => {
    const saved = localStorage.getItem("selectedNetwork");
    if (saved) {
      setNetwork(saved);
      setStep(2);
      localStorage.removeItem("selectedNetwork");
    }

    // Background refresh: the saved list is already on screen; this only swaps it if prices,
    // stock or a new bundle size changed on the server.
    const off = subscribePrices(setPrices);
    refreshPrices();
    return off;
  }, []);

  const OUT_OF_STOCK = [];
  const isOutOfStock = (name) => OUT_OF_STOCK.includes(name);

  const bundles = prices
    .filter((p) => p.network === network)
    .sort((a, b) => Number(a.price) - Number(b.price));

  const validPhone = (num) => isGhanaPhone(num);

  // Informational-only pre-check — never blocks a purchase, just warns.
  // Fired once, on submit (see handleBuy) rather than as-you-type, so the
  // scarce 2-checks/minute vendor quota is spent on real checkout attempts
  // instead of being burned by every keystroke.
  const checkNumber = async (num) => {
    if (network !== "MTN" || !validPhone(num)) return null;
    setVerifying(true);
    setVerifyTimedOut(false);
    if (resultTimerRef.current) clearTimeout(resultTimerRef.current);
    setShowVerifyResult(false);
    try {
      const res = await verifyNumber(num, network); // 7s timeout, see api.js
      setVerifyInfo(res.data);
      // Keep the result up until the user acts on it (Proceed/Cancel) —
      // this is no longer a passive toast, it's the gate before payment.
      setShowVerifyResult(true);
      return res.data;
    } catch {
      setVerifyInfo(null);
      setShowVerifyResult(true);
      return null;
    } finally {
      setVerifying(false);
    }
  };

  // Watchdog: pure safety net in case the request hangs outside axios's own
  // control. Set comfortably past verifyNumber's 12s timeout (see api.js) so
  // it never fires before the real check has a chance to resolve — firing
  // early would flash the popup away and briefly re-enable Pay mid-check.
  useEffect(() => {
    if (!verifying) return;
    const t = setTimeout(() => setVerifyTimedOut(true), 13000);
    return () => clearTimeout(t);
  }, [verifying]);

  // True only while we should keep the Buy button hidden behind the popup.
  const checkingBlocking = verifying && !verifyTimedOut;

  const handleBuy = async () => {
    setError("");
    setPendingMsg("");
    if (!network || !bundle) { setError("Select network and bundle"); return; }
    if (!phone) { setError("Enter phone number"); return; }
    if (!validPhone(phone)) { setError(GHANA_ONLY_MSG); return; }
    if (!agree) { setError("You must confirm the refund policy"); return; }

    // MTN: run the verify check first and stop — the popup then shows the
    // outcome (verified / on hold / unavailable) with its own Proceed
    // button, so the user always sees the status before paying instead of
    // it silently deciding for them.
    if (network === "MTN") {
      await checkNumber(phone);
      return;
    }

    // Other networks: no DataMart check exists, go straight to payment.
    await submitOrder();
  };

  const submitOrder = async () => {
    try {
      setShowVerifyResult(false);
      setLoading(true);

      const res = await API.post("/orders/create", {
        user_id, network, bundle, phone: toGhanaPhone(phone),
        email: email || "guest@evoshub.com",
        ...(xeraOn ? { use_xera: true } : {}),   // the server works out the price; this only asks for it
        ...(useWallet ? { pay_with: "wallet" } : {}),
      });

      const data = res.data;

      if (data?.paid_with === "wallet") {          // paid from the wallet: no redirect
        setLoading(false);
        setDone({ message: data.message, balance: data.new_wallet_balance, charged: data.charged, reference: data.reference });
        return;
      }

      const paymentUrl =
        data?.payment_url ||
        data?.authorization_url ||
        data?.data?.authorization_url;

      if (!paymentUrl) {
        setLoading(false);
        setError("Payment link not received");
        return;
      }

      localStorage.setItem("email", email);

      // ── Pending order found — show message then redirect ──
      if (data?.pending) {
        setPendingMsg(data.message);
        setTimeout(() => {
          window.location.href = paymentUrl;
        }, 2500);
        return;
      }

      window.location.href = paymentUrl;

    } catch (err) {
      setLoading(false);
      const d = err.response?.data?.detail;
      if (d && typeof d === "object") {
        if (d.code === "insufficient_wallet") {      // balance moved since the scan: show the same popup
          setShortPopup({ balance: Number(d.balance), needed: Number(d.needed) });
          setPayMethod("paystack");
          return;
        }
        setError(d.message || "Order failed");
        return;
      }
      setError(
        err.response?.data?.detail ||
        err.response?.data?.message ||
        "Order failed"
      );
    }
  };

  const networks = [
    {
      name: "MTN", label: "MTN", emoji: "🟡", color: "#FFC107",
      bg: "linear-gradient(135deg, rgba(255,193,7,0.18), rgba(255,193,7,0.06))",
      border: "rgba(255,193,7,0.4)", desc: "Ghana's largest network",
    },
    {
      name: "TELECEL", label: "Telecel", emoji: "🔴", color: "#ef4444",
      bg: "linear-gradient(135deg, rgba(239,68,68,0.18), rgba(239,68,68,0.06))",
      border: "rgba(239,68,68,0.4)", desc: "Formerly Vodafone Ghana",
    },
    {
      name: "AIRTELTIGO", label: "AirtelTigo", emoji: "🔵", color: "#2dd4bf",
      bg: "linear-gradient(135deg, rgba(45,212,191,0.18), rgba(45,212,191,0.06))",
      border: "rgba(45,212,191,0.4)", desc: "Nationwide coverage",
    },
  ];

  const selectedNetwork = networks.find((n) => n.name === network);

  return (
    <div style={styles.container}>
      <style>{`@keyframes evos-spin { to { transform: rotate(360deg); } }
.sh-head { margin: 0 0 16px; }
.sh-head h2 { margin: 0; font-size: 26px; }
.sh-head p { margin: 6px 0 0; display: flex; gap: 8px; align-items: center; font-size: 13px; color: var(--faint); }
.sh-head i { font-style: normal; }
.sh-head .on { color: var(--lime); font-weight: 700; }
.sh-tabs { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; padding: 5px; border-radius: 16px; background: var(--surface); border: 1px solid var(--line); }
.sh-tab { min-height: 48px; border: 0; border-radius: 12px; background: transparent; color: var(--muted); font: 700 14px var(--font-display); cursor: pointer; display: flex; flex-direction: column; align-items: center; justify-content: center; }
.sh-tab small { font-size: 10px; font-weight: 600; color: var(--danger); }
.sh-tab.on { background: var(--lime); color: #0b1017; }
.sh-tab:disabled { opacity: .4; cursor: not-allowed; }
.sh-hint { margin: 22px 0; text-align: center; font-size: 14px; color: var(--faint); }
.sh-list { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-top: 14px; }
@media (max-width: 340px) { .sh-list { grid-template-columns: repeat(2, 1fr); } }
.sh-row { aspect-ratio: 1 / 1; min-width: 0; display: flex; flex-direction: column; justify-content: center; align-items: center; gap: 6px; padding: 8px; border: 1px solid var(--line); border-radius: 16px; background: var(--surface); color: var(--text); font-family: inherit; cursor: pointer; text-align: center; transition: transform .12s, border-color .12s; }
.sh-row:hover:not(:disabled) { background: var(--surface-2); border-color: var(--lime); }
.sh-row:active:not(:disabled) { transform: scale(.97); }
.sh-row:disabled { opacity: .5; cursor: not-allowed; }
.sh-size { font: 800 clamp(17px, 5vw, 22px) var(--font-display); }
.sh-price { font-weight: 800; font-size: 14px; color: var(--lime); }
.sh-out { font-size: 12px; font-weight: 700; color: var(--danger); }
.sh-note { margin-top: 12px; text-align: center; font-size: 12.5px; color: var(--faint); }
.sh-tab:focus-visible, .sh-row:focus-visible { outline: 2px solid var(--lime); outline-offset: 2px; }
`}</style>

      {/* HEADER */}
      <div className="sh-head">
        <h2>Buy data</h2>
        <p>
          <span className={step < 3 ? "on" : ""}>{selectedNetwork?.label || "Network"}</span>
          <i>›</i>
          <span className={step === 3 ? "on" : ""}>{step === 3 ? bundle : "Bundle"}</span>
          <i>›</i>
          <span>Pay</span>
        </p>
      </div>

      {/* PENDING ORDER NOTICE */}
      {pendingMsg && (
        <div style={styles.pendingNotice}>
          ⏳ {pendingMsg}
        </div>
      )}

      {/* ERROR */}
      {error && (
        <div style={styles.error}>
          ⚠️ {error}
        </div>
      )}

      <div style={styles.wrapper}>

        {/* ============ NETWORK + BUNDLE (one screen) ============ */}
        {step < 3 && (
          <div className="sh-pick">
            <div className="sh-tabs" role="tablist" aria-label="Network">
              {networks.map((n) => {
                const disabled = isOutOfStock(n.name);
                return (
                  <button
                    key={n.name}
                    role="tab"
                    aria-selected={network === n.name}
                    disabled={disabled}
                    className={`sh-tab ${network === n.name ? "on" : ""}`}
                    style={{ "--c": n.color }}
                    onClick={() => { setNetwork(n.name); setStep(2); }}
                  >
                    {n.label}
                    {disabled && <small>Out of stock</small>}
                  </button>
                );
              })}
            </div>

            {!network && <p className="sh-hint">Choose a network to see its bundles.</p>}

            {network && bundles.length === 0 && (
              <p className="sh-hint">{prices.length === 0 ? "Loading bundles…" : "No bundles available for this network."}</p>
            )}

            <div className="sh-list">
              {bundles.map((b, i) => {
                const soldOut = b.in_stock === false;
                return (
                  <button
                    key={i}
                    className="sh-row"
                    disabled={soldOut}
                    onClick={() => {
                      setBundle(b.bundle);
                      setBundlePrice(b.price);
                      setStep(3);
                    }}
                  >
                    <span className="sh-size">{b.bundle}</span>
                    {soldOut ? <span className="sh-out">Out of stock</span> : <span className="sh-price">GH₵ {Number(b.price).toFixed(2)}</span>}
                  </button>
                );
              })}
            </div>

            <p className="sh-note">🔒 Paid through Paystack. Delivered automatically.</p>
          </div>
        )}

        {/* ============ STEP 3 — CHECKOUT ============ */}
        {step === 3 && done && (
          <div style={{ ...styles.box, textAlign: "center" }}>
            <p style={{ fontSize: 44, margin: "0 0 6px" }}>✅</p>
            <p style={{ ...styles.stepLabel, marginBottom: 6 }}>Order placed</p>
            <p style={{ fontSize: 14, opacity: 0.85, margin: "0 0 4px" }}>{done.message}</p>
            <p style={{ fontSize: 13, opacity: 0.65, margin: "0 0 18px" }}>
              Paid GH₵ {Number(done.charged).toFixed(2)} · wallet balance GH₵ {Number(done.balance).toFixed(2)}
            </p>
            <button style={styles.buyBtn} onClick={() => { setDone(null); setStep(1); setBundle(""); setPhone(""); setAgree(false); }}>
              Buy another
            </button>
            {setPage && (
              <button style={styles.verifyPopupCancelBtn} onClick={() => setPage("orders")}>View my orders</button>
            )}
          </div>
        )}

        {step === 3 && !done && (
          <div style={styles.box}>
            <button style={styles.backBtn} onClick={() => setStep(2)}>← Back</button>
            <p style={styles.stepLabel}>Complete your order</p>

            <div style={styles.summaryCard}>
              <div style={styles.summaryRow}>
                <span style={styles.summaryLabel}>Network</span>
                <span style={{ ...styles.summaryVal, color: selectedNetwork?.color, fontWeight: 800 }}>
                  {selectedNetwork?.emoji} {selectedNetwork?.label}
                </span>
              </div>
              <div style={styles.summaryRow}>
                <span style={styles.summaryLabel}>Bundle</span>
                <span style={styles.summaryVal}>{bundle}</span>
              </div>
              <div style={{ ...styles.summaryRow, borderBottom: "none" }}>
                <span style={styles.summaryLabel}>Amount</span>
                <span style={{ ...styles.summaryVal, color: "#ffb020", fontSize: 20, fontWeight: 900 }}>
                  {xeraOn && (
                    <span style={{ textDecoration: "line-through", opacity: 0.5, fontSize: 14, marginRight: 8 }}>
                      GH₵ {Number(bundlePrice).toFixed(2)}
                    </span>
                  )}
                  GH₵ {(useWallet ? walletAmount : payAmount).toFixed(2)}
                </span>
              </div>
            </div>

            {xeraQuote && (xeraQuote.eligible ? (
              <label style={{ display: "flex", gap: 10, alignItems: "flex-start", cursor: "pointer",
                              padding: "10px 12px", marginBottom: 14, borderRadius: 10,
                              border: "1px solid rgba(255,176,32,0.35)", background: "rgba(255,176,32,0.06)" }}>
                <input type="checkbox" checked={useXera} onChange={(e) => setUseXera(e.target.checked)}
                       style={{ marginTop: 3 }} />
                <span style={{ fontSize: 13, lineHeight: 1.45 }}>
                  Use <b>{Number(xeraQuote.xera_amount)} XERA</b> for <b>GH₵ {Number(xeraQuote.discount_ghs).toFixed(2)} off</b>
                  {" "}(pay GH₵ {Number(xeraQuote.final_price).toFixed(2)}).
                  <span style={{ display: "block", opacity: 0.6, fontSize: 11.5 }}>
                    Promotional discount. Your XERA balance: {Number(xeraQuote.spendable)}.
                    {" "}Complete your payment within {Number(xeraQuote.hold_minutes) || 60} minutes.
                  </span>
                  {xeraQuote.verified === false && Number(xeraQuote.xera_if_verified) < Number(xeraQuote.xera_amount) && (
                    <span style={{ display: "block", opacity: 0.8, fontSize: 11.5, marginTop: 2 }}>
                      Verify your identity in the XERA app to pay only {Number(xeraQuote.xera_if_verified)} XERA.
                    </span>
                  )}
                </span>
              </label>
            ) : (xeraQuote.message && xeraQuote.reason !== "disabled" && xeraQuote.reason !== "no_discount") ? (
              <p style={{ fontSize: 12, opacity: 0.65, margin: "0 0 14px" }}>🪙 {xeraQuote.message}</p>
            ) : null)}

            {wallet && (
              <div style={{ marginBottom: 14 }}>
                <p style={{ ...styles.inputLabel, marginBottom: 8 }}>How do you want to pay?</p>
                <div style={{ display: "grid", gap: 8 }}>
                  <button type="button"
                    onClick={() => walletEnough ? setPayMethod("wallet")
                      : setShortPopup({ balance: walletBalance, needed: walletAmount })}
                    style={{ textAlign: "left", padding: "12px 14px", borderRadius: 12, cursor: "pointer",
                             border: useWallet ? "2px solid #22c55e" : "1px solid rgba(255,255,255,0.12)",
                             background: useWallet ? "rgba(34,197,94,0.08)" : "rgba(255,255,255,0.03)",
                             color: "inherit", opacity: walletEnough ? 1 : 0.45, filter: walletEnough ? "none" : "grayscale(1)" }}>
                    <b>👛 Wallet · GH₵ {walletAmount.toFixed(2)}</b>
                    <span style={{ display: "block", fontSize: 12, opacity: 0.75 }}>
                      {walletEnough
                        ? `Wallet price: GH₵ ${Number(wallet.wallet_discount || 0).toFixed(2)} cheaper · balance GH₵ ${walletBalance.toFixed(2)}`
                        : `Balance GH₵ ${walletBalance.toFixed(2)} · not enough for this order`}
                    </span>
                  </button>
                  <button type="button" onClick={() => setPayMethod("paystack")}
                    style={{ textAlign: "left", padding: "12px 14px", borderRadius: 12, cursor: "pointer",
                             border: !useWallet ? "2px solid #22c55e" : "1px solid rgba(255,255,255,0.12)",
                             background: !useWallet ? "rgba(34,197,94,0.08)" : "rgba(255,255,255,0.03)", color: "inherit" }}>
                    <b>💳 Paystack · GH₵ {payAmount.toFixed(2)}</b>
                    <span style={{ display: "block", fontSize: 12, opacity: 0.75 }}>Mobile money or card</span>
                  </button>
                </div>
              </div>
            )}

            <label style={styles.inputLabel}>📱 Recipient Phone Number</label>
            <input
              style={{
                ...styles.input,
                borderColor: phone && !validPhone(phone)
                  ? "rgba(239,68,68,0.6)"
                  : phone && validPhone(phone)
                  ? "rgba(34,197,94,0.6)"
                  : "rgba(255,255,255,0.08)",
              }}
              type="tel"
              placeholder="e.g. 0244000000"
              value={phone}
              maxLength={16}
              onChange={(e) => {
                setPhone(e.target.value);
                setVerifyInfo(null);
                setVerifyTimedOut(false);
                setShowVerifyResult(false);
              }}
            />
            {phone.length > 0 && !validPhone(phone) && (
              <p style={styles.phoneHint}>⚠️ Enter a Ghana number (EVOS Data is Ghana only), e.g. 0551234567</p>
            )}
            {phone.length > 0 && validPhone(phone) && (
              <p style={styles.phoneHintGood}>✅ Looks good!</p>
            )}
            {checkingBlocking && (
              <p style={styles.verifyChecking}>🔎 Checking number...</p>
            )}
            {!checkingBlocking && verifyInfo?.checked && verifyInfo?.recommendation === "activate_first" && (
              <p style={styles.verifyWarning}>⚠️ {verifyInfo.message}</p>
            )}
            {!checkingBlocking && verifyInfo?.checked && verifyInfo?.recommendation === "sell_any" && (
              <p style={styles.phoneHintGood}>✅ Number is active on MTN's network</p>
            )}

            <label style={styles.inputLabel}>📧 Email (for receipt)</label>
            <input
              style={styles.input}
              type="email"
              placeholder="your@email.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />

            <label style={styles.checkWrap}>
              <input
                type="checkbox"
                checked={agree}
                onChange={() => setAgree(!agree)}
                style={{ accentColor: "#ffb020", width: 16, height: 16, flexShrink: 0, marginTop: 2 }}
              />
              <span style={styles.checkText}>
                I confirm this number is correct.{" "}
                <strong style={{ color: "#f87171" }}>Wrong numbers will NOT be refunded.</strong>{" "}
                I take full responsibility.
              </span>
            </label>

            {checkingBlocking ? (
              <button disabled style={{ ...styles.buyBtn, opacity: 0.4, cursor: "not-allowed" }}>
                🔎 Verifying number...
              </button>
            ) : showVerifyResult ? (
              <button disabled style={{ ...styles.buyBtn, opacity: 0.4, cursor: "not-allowed" }}>
                See popup to continue
              </button>
            ) : (
              <button
                onClick={handleBuy}
                disabled={loading}
                style={{ ...styles.buyBtn, opacity: loading ? 0.6 : 1 }}
              >
                {loading
                  ? pendingMsg ? "⏳ Redirecting to payment..." : "⏳ Processing..."
                  : useWallet
                    ? `👛 Pay GH₵ ${walletAmount.toFixed(2)} from wallet`
                    : `💳 Pay GH₵ ${payAmount.toFixed(2)} via Paystack`}
              </button>
            )}

            <p style={styles.secureNote}>{useWallet ? "🔒 Paid from your EVOS Data wallet" : "🔒 Secured & encrypted via Paystack"}</p>
          </div>
        )}
      </div>

      {/* WALLET TOO LOW POPUP */}
      {shortPopup && (
        <div style={styles.verifyOverlay}>
          <div style={styles.verifyPopup}>
            <p style={styles.verifyPopupText}>👛 Wallet balance too low</p>
            <p style={styles.verifyPopupSub}>
              You have GH₵ {Number(shortPopup.balance).toFixed(2)}; this order needs GH₵ {Number(shortPopup.needed).toFixed(2)}.
              Top up to get the cheaper wallet price, or pay with Paystack now.
            </p>
            <div style={styles.verifyPopupActions}>
              {setPage && (
                <button style={styles.verifyPopupProceedBtn}
                  onClick={() => { setShortPopup(null); setPage("wallet-topup"); }}>Top up wallet</button>
              )}
              <button style={styles.verifyPopupCancelBtn}
                onClick={() => { setShortPopup(null); setPayMethod("paystack"); }}>Pay with Paystack instead</button>
            </div>
          </div>
        </div>
      )}

      {/* VERIFY NUMBER POPUP */}
      {(checkingBlocking || showVerifyResult) && (
        <div style={styles.verifyOverlay}>
          <div style={styles.verifyPopup}>
            {checkingBlocking ? (
              <>
                <div style={styles.verifySpinner} />
                <p style={styles.verifyPopupText}>Checking number...</p>
                <p style={styles.verifyPopupSub}>Confirming this MTN number is active</p>
              </>
            ) : verifyInfo?.checked && verifyInfo?.recommendation === "activate_first" ? (
              <>
                <p style={styles.verifyPopupText}>⚠️ On hold — activation needed</p>
                <p style={styles.verifyPopupSub}>{verifyInfo.message}</p>
              </>
            ) : verifyInfo?.checked && verifyInfo?.recommendation === "sell_any" ? (
              <>
                <p style={styles.verifyPopupText}>✅ Number verified</p>
                <p style={styles.verifyPopupSub}>Active on MTN — any bundle size will deliver instantly</p>
              </>
            ) : (
              <>
                <p style={styles.verifyPopupText}>ℹ️ Couldn't confirm status</p>
                <p style={styles.verifyPopupSub}>{verifyInfo?.message || "You can still continue with your order"}</p>
              </>
            )}

            {showVerifyResult && !checkingBlocking && (
              <div style={styles.verifyPopupActions}>
                <button
                  onClick={() => {
                    setShowVerifyResult(false);
                  }}
                  style={styles.verifyPopupCancelBtn}
                >
                  Change number
                </button>
                <button
                  onClick={submitOrder}
                  disabled={loading}
                  style={{ ...styles.verifyPopupProceedBtn, opacity: loading ? 0.6 : 1 }}
                >
                  {loading
                    ? "⏳ Processing..."
                    : verifyInfo?.checked && verifyInfo?.recommendation === "activate_first"
                    ? "Proceed anyway"
                    : "Proceed to payment"}
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      {/* FLOATING SUPPORT */}
      <div style={styles.floatWrap}>
        {chatOpen && (
          <div style={styles.chatPopup}>
            <div style={styles.chatHeader}>
              <span style={{ fontWeight: 800, fontSize: 14, color: "#e5e7eb" }}>💬 EVOS Support</span>
              <button style={styles.chatClose} onClick={() => setChatOpen(false)}>✕</button>
            </div>
            <p style={styles.chatMsg}>Hi! Need help with your order? Choose an option below 👇</p>
            <div style={styles.chatOptions}>
              <button style={styles.chatOption}
                onClick={() => window.open("https://wa.me/233537314125", "_blank")}>
                💬 WhatsApp Chat
              </button>
              <button style={styles.chatOption}
                onClick={() => window.open("https://whatsapp.com/channel/0029VaTrnsZEgGfFXkIcjt1M", "_blank")}>
                👥 Community
              </button>
              <button style={styles.chatOption}
                onClick={() => window.location.href = "mailto:support@evoshub.xyz"}>
                📧 Email Support
              </button>
            </div>
          </div>
        )}
        <button style={styles.floatBtn} onClick={() => setChatOpen(!chatOpen)}>
          {chatOpen ? "✕" : "💬"}
        </button>
      </div>

    </div>
  );
}

const styles = {
  container: {
    padding: "24px 18px 60px", color: "#e5e7eb",
    fontFamily: "ui-sans-serif, system-ui, Arial", minHeight: "auto",
  },
  header: { textAlign: "center", marginBottom: 28 },
  headerBadge: {
    display: "inline-block", padding: "5px 16px", borderRadius: 50,
    background: "rgba(255,176,32,0.15)", border: "1px solid rgba(255,176,32,0.3)",
    color: "#ffb020", fontSize: 12, fontWeight: 700, marginBottom: 12,
  },
  title: { fontSize: 26, fontWeight: 900, color: "#f4f6f9", margin: "0 0 6px" },
  subtitle: { fontSize: 14, color: "#8b98ab", margin: 0 },

  progressWrap: {
    display: "flex", justifyContent: "center", alignItems: "center",
    gap: 0, marginBottom: 28, position: "relative",
    maxWidth: 340, margin: "0 auto 28px",
  },
  progressItem: {
    display: "flex", flexDirection: "column", alignItems: "center",
    gap: 6, flex: 1, position: "relative", zIndex: 1,
  },
  progressDot: {
    width: 32, height: 32, borderRadius: "50%",
    display: "flex", alignItems: "center", justifyContent: "center",
    fontSize: 13, fontWeight: 800, color: "white", transition: "all 0.3s",
  },
  progressLabel: { fontSize: 11, fontWeight: 700, transition: "color 0.3s" },
  progressLine: {
    position: "absolute", top: 16, left: "16%", right: "16%",
    height: 2, background: "rgba(255,255,255,0.08)", zIndex: 0,
  },

  pendingNotice: {
    background: "rgba(255,176,32,0.1)", border: "1px solid rgba(255,176,32,0.3)",
    color: "#ffb020", padding: "12px 16px", borderRadius: 12,
    marginBottom: 16, fontSize: 14, maxWidth: 480,
    margin: "0 auto 16px", textAlign: "center", fontWeight: 700,
  },
  error: {
    background: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.3)",
    color: "#f87171", padding: "12px 16px", borderRadius: 12,
    marginBottom: 16, fontSize: 14, maxWidth: 480,
    margin: "0 auto 16px", textAlign: "center",
  },

  wrapper: { maxWidth: 480, margin: "0 auto" },
  box: {
    background: "rgba(22,30,41,0.9)", backdropFilter: "blur(20px)",
    WebkitBackdropFilter: "blur(20px)", padding: "24px 20px",
    borderRadius: 22, border: "1px solid rgba(255,255,255,0.07)",
    boxShadow: "0 25px 60px rgba(0,0,0,0.4)",
  },
  stepLabel: {
    fontSize: 12, color: "#ffb020", fontWeight: 700,
    textTransform: "uppercase", letterSpacing: "0.8px", margin: "0 0 18px",
  },

  networkGrid: { display: "flex", flexDirection: "column", gap: 12, marginBottom: 20 },
  networkCard: {
    padding: "16px 18px", borderRadius: 16, cursor: "pointer",
    display: "flex", alignItems: "center", gap: 14,
    transition: "transform 0.15s", position: "relative",
  },
  networkEmoji: { fontSize: 26, flexShrink: 0 },
  networkName: { fontWeight: 800, fontSize: 16, flex: 1 },
  networkDesc: { fontSize: 12, color: "#8b98ab" },
  networkArrow: { fontSize: 18, fontWeight: 900 },
  stockBadge: {
    position: "absolute", right: 14, top: "50%", transform: "translateY(-50%)",
    background: "rgba(239,68,68,0.15)", border: "1px solid rgba(239,68,68,0.3)",
    color: "#ef4444", fontSize: 11, fontWeight: 800, padding: "3px 10px", borderRadius: 50,
  },
  infoRow: { display: "flex", justifyContent: "center", gap: 20 },
  infoText: { fontSize: 12, color: "#6c7a8f", fontWeight: 600 },

  backBtn: {
    background: "none", border: "none", color: "#ffb020",
    fontSize: 14, fontWeight: 700, cursor: "pointer",
    padding: 0, marginBottom: 14, display: "block",
  },
  networkPill: {
    display: "inline-block", padding: "6px 16px", borderRadius: 50,
    fontSize: 13, fontWeight: 800, marginBottom: 18,
  },
  emptyText: { color: "#6c7a8f", fontSize: 14, textAlign: "center", padding: "20px 0" },
  bundleGrid: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 8 },
  bundleCard: {
    background: "rgba(11,16,23,0.7)", border: "1px solid rgba(255,255,255,0.08)",
    borderRadius: 16, padding: "16px 14px", cursor: "pointer",
    textAlign: "center", transition: "border-color 0.15s",
  },
  bundleSize: { fontWeight: 900, fontSize: 18, color: "#f4f6f9", marginBottom: 6 },
  bundlePrice: { fontWeight: 800, fontSize: 16, color: "#ffb020", marginBottom: 8 },
  bundleTap: { fontSize: 11, color: "#ffb020", opacity: 0.6 },

  summaryCard: {
    background: "rgba(11,16,23,0.7)", border: "1px solid rgba(255,255,255,0.06)",
    borderRadius: 16, padding: "6px 16px", marginBottom: 22,
  },
  summaryRow: {
    display: "flex", justifyContent: "space-between", alignItems: "center",
    padding: "12px 0", borderBottom: "1px solid rgba(255,255,255,0.05)",
  },
  summaryLabel: { fontSize: 13, color: "#8b98ab" },
  summaryVal: { fontSize: 15, fontWeight: 700, color: "#e5e7eb" },

  inputLabel: { display: "block", fontSize: 12, color: "#8b98ab", fontWeight: 700, marginBottom: 6 },
  input: {
    width: "100%", padding: "13px 14px", marginBottom: 6, borderRadius: 12,
    border: "1.5px solid", background: "rgba(11,16,23,0.75)",
    color: "#fff", outline: "none", fontSize: 14, boxSizing: "border-box",
    transition: "border-color 0.2s",
  },
  phoneHint: { fontSize: 12, color: "#f87171", margin: "0 0 14px", paddingLeft: 2 },
  phoneHintGood: { fontSize: 12, color: "#22c55e", margin: "0 0 14px", paddingLeft: 2 },
  verifyChecking: { fontSize: 12, color: "#8b98ab", margin: "0 0 14px", paddingLeft: 2 },
  verifyWarning: { fontSize: 12, color: "#f59e0b", margin: "0 0 14px", paddingLeft: 2, lineHeight: 1.5 },

  checkWrap: {
    display: "flex", gap: 10, alignItems: "flex-start",
    background: "rgba(245,158,11,0.08)", border: "1px solid rgba(245,158,11,0.25)",
    padding: "12px 14px", borderRadius: 12, marginBottom: 16, cursor: "pointer", marginTop: 8,
  },
  checkText: { fontSize: 13, color: "#b3bece", lineHeight: 1.55 },
  buyBtn: {
    width: "100%", padding: "15px", borderRadius: 14, border: "none",
    background: "linear-gradient(135deg, #22c55e, #16a34a)", color: "white",
    fontWeight: 900, fontSize: 15, cursor: "pointer", marginBottom: 12,
    boxShadow: "0 4px 20px rgba(34,197,94,0.3)",
  },
  secureNote: { textAlign: "center", fontSize: 12, color: "#6c7a8f", margin: 0 },

  verifyOverlay: {
    position: "fixed", inset: 0, background: "rgba(11,16,23,0.7)",
    backdropFilter: "blur(2px)", display: "flex",
    alignItems: "center", justifyContent: "center", zIndex: 2000,
  },
  verifyPopup: {
    background: "#161e29", border: "1px solid rgba(255,255,255,0.1)",
    borderRadius: 20, padding: "28px 32px", textAlign: "center",
    boxShadow: "0 20px 60px rgba(0,0,0,0.5)", maxWidth: 280,
  },
  verifySpinner: {
    width: 34, height: 34, margin: "0 auto 14px", borderRadius: "50%",
    border: "3px solid rgba(255,176,32,0.2)", borderTopColor: "#ffb020",
    animation: "evos-spin 0.8s linear infinite",
  },
  verifyPopupText: { fontSize: 15, fontWeight: 800, color: "#f4f6f9", margin: "0 0 4px" },
  verifyPopupSub: { fontSize: 12, color: "#8b98ab", margin: 0 },
  verifyPopupActions: {
    display: "flex", flexDirection: "column", gap: 8, marginTop: 18,
  },
  verifyPopupProceedBtn: {
    background: "linear-gradient(135deg, #ffb020, #f59300)", color: "#fff",
    border: "none", borderRadius: 12, padding: "12px 16px",
    fontSize: 14, fontWeight: 800, cursor: "pointer",
  },
  verifyPopupCancelBtn: {
    background: "transparent", color: "#b3bece",
    border: "1px solid rgba(255,255,255,0.12)", borderRadius: 12,
    padding: "10px 16px", fontSize: 13, fontWeight: 700, cursor: "pointer",
  },

  floatWrap: {
    position: "fixed", bottom: "calc(var(--dock, 0px) + 20px)", right: 16, zIndex: 9999,
    display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 10,
  },
  chatPopup: {
    background: "#161e29", border: "1px solid rgba(255,255,255,0.1)",
    borderRadius: 18, padding: 18, width: 270, boxShadow: "0 8px 32px rgba(0,0,0,0.5)",
  },
  chatHeader: { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 },
  chatClose: { background: "none", border: "none", color: "#8b98ab", cursor: "pointer", fontSize: 14 },
  chatMsg: { fontSize: 13, color: "#b3bece", lineHeight: 1.55, margin: "0 0 12px" },
  chatOptions: { display: "flex", flexDirection: "column", gap: 8 },
  chatOption: {
    padding: "10px 14px", borderRadius: 10, border: "1px solid rgba(255,255,255,0.08)",
    background: "rgba(255,255,255,0.04)", color: "#e5e7eb",
    fontSize: 13, fontWeight: 700, cursor: "pointer", textAlign: "left",
  },
  floatBtn: {
    width: 54, height: 54, borderRadius: "50%",
    background: "linear-gradient(135deg, #25D366, #128C7E)",
    border: "none", color: "white", fontSize: 22, cursor: "pointer",
    boxShadow: "0 4px 20px rgba(37,211,102,0.45)",
    display: "flex", alignItems: "center", justifyContent: "center",
  },
};
