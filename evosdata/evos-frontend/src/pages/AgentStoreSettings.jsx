import { useEffect, useState } from "react";
import { asset, withBase } from "../lib/basePath";

import { smartFetch } from "../config";

const slugify = (name) =>
    name.trim().toLowerCase()
        .replace(/[^a-z0-9\s-]/g, "")
        .replace(/\s+/g, "-")
        .replace(/-+/g, "-")
        .replace(/^-|-$/g, "");

const buildStoreLink = (agentId, storeName) => {
    const base = `${window.location.origin}${withBase(`/store/${agentId}`)}`;
    const slug = storeName ? slugify(storeName) : "";
    return slug ? `${base}/${slug}` : base;
};

const MAX_LOGO_DIM = 320;

export default function AgentStoreSettings({ user, setPage }) {
    const [loading, setLoading]     = useState(true);
    const [error, setError]         = useState("");
    const [copied, setCopied]       = useState(false);
    const [storeLink, setStoreLink] = useState("");

    const [storeName, setStoreName]           = useState("");
    const [storeNameInput, setStoreNameInput] = useState("");
    const [storeNameSaving, setStoreNameSaving] = useState(false);
    const [storeNameMsg, setStoreNameMsg]     = useState("");

    const [storeLogo, setStoreLogo]               = useState("");   // saved (base64 data URI or "")
    const [storeLogoPreview, setStoreLogoPreview] = useState(""); // picked, not yet saved
    const [storeLogoSaving, setStoreLogoSaving]   = useState(false);
    const [storeLogoMsg, setStoreLogoMsg]         = useState("");

    const getToken = () =>
        user?.agent_token
        || sessionStorage.getItem("agentToken")
        || localStorage.getItem("agentToken")
        || "";

    const agentHeaders = () => ({
        "Content-Type": "application/json",
        "X-Agent-Token": getToken(),
    });

    useEffect(() => {
        if (!user) { setPage("login"); return; }
        if (user.role !== "agent" || user.agent_status !== "approved") setPage("dashboard");
    }, [user, setPage]);

    useEffect(() => {
        if (!user?.id) return;

        const load = async () => {
            try {
                setLoading(true);
                setError("");
                const headers = agentHeaders();
                const [nameRes, logoRes] = await Promise.all([
                    smartFetch(`/agent/store-name/${user.id}`, { headers }),
                    smartFetch(`/agent/store-logo/${user.id}`, { headers }),
                ]);

                if (nameRes.status === 403 || logoRes.status === 403) {
                    sessionStorage.removeItem("agentToken");
                    localStorage.removeItem("agentToken");
                    setPage("login");
                    return;
                }

                const nameData = await nameRes.json();
                const logoData = await logoRes.json();
                const currentName = nameData.store_name || "";

                setStoreName(currentName);
                setStoreNameInput(currentName);
                setStoreLogo(logoData.logo || "");
                setStoreLogoPreview(logoData.logo || "");
                setStoreLink(buildStoreLink(user.id, currentName));
            } catch (err) {
                console.log(err);
                setError("Failed to load store settings");
            } finally {
                setLoading(false);
            }
        };

        load();
    }, [user]);

    const copyLink = async () => {
        try {
            await navigator.clipboard.writeText(storeLink);
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
        } catch { alert("Copy failed"); }
    };

    const saveStoreName = async () => {
        setStoreNameMsg("");
        setStoreNameSaving(true);
        try {
            const res = await smartFetch(`/agent/store-name`, {
                method: "POST",
                headers: agentHeaders(),
                body: JSON.stringify({ agent_id: user.id, store_name: storeNameInput.trim() }),
            });
            const data = await res.json();
            if (data.status === "success") {
                const newName = storeNameInput.trim();
                setStoreName(newName);
                setStoreLink(buildStoreLink(user.id, newName));
                setStoreNameMsg("✅ Store name saved!");
            } else {
                setStoreNameMsg(data.error || "Failed to save");
            }
        } catch { setStoreNameMsg("Network error"); }
        finally {
            setStoreNameSaving(false);
            setTimeout(() => setStoreNameMsg(""), 3000);
        }
    };

    // Resizes/compresses whatever the agent picks down to a small square JPEG
    // before it ever touches the network — keeps uploads fast and the saved
    // payload well under the server's size cap regardless of the source file.
    const handleLogoFile = (e) => {
        const file = e.target.files?.[0];
        e.target.value = ""; // allow re-selecting the same file later
        if (!file) return;

        if (!file.type.startsWith("image/")) {
            setStoreLogoMsg("Please choose an image file");
            setTimeout(() => setStoreLogoMsg(""), 3000);
            return;
        }

        const reader = new FileReader();
        reader.onload = () => {
            const img = new Image();
            img.onload = () => {
                const size = Math.min(img.width, img.height); // center-crop to square
                const canvas = document.createElement("canvas");
                canvas.width = MAX_LOGO_DIM;
                canvas.height = MAX_LOGO_DIM;
                const ctx = canvas.getContext("2d");
                const sx = (img.width - size) / 2;
                const sy = (img.height - size) / 2;
                ctx.drawImage(img, sx, sy, size, size, 0, 0, MAX_LOGO_DIM, MAX_LOGO_DIM);
                const dataUrl = canvas.toDataURL("image/jpeg", 0.85);
                setStoreLogoPreview(dataUrl);
                setStoreLogoMsg("");
            };
            img.onerror = () => setStoreLogoMsg("Couldn't read that image — try another file");
            img.src = reader.result;
        };
        reader.readAsDataURL(file);
    };

    const saveStoreLogo = async () => {
        setStoreLogoMsg("");
        setStoreLogoSaving(true);
        try {
            const res = await smartFetch(`/agent/store-logo`, {
                method: "POST",
                headers: agentHeaders(),
                body: JSON.stringify({ agent_id: user.id, logo_base64: storeLogoPreview }),
            });
            const data = await res.json();
            if (data.status === "success") {
                setStoreLogo(data.logo || "");
                setStoreLogoMsg("✅ Logo saved!");
            } else {
                setStoreLogoMsg(data.error || "Failed to save logo");
            }
        } catch { setStoreLogoMsg("Network error"); }
        finally {
            setStoreLogoSaving(false);
            setTimeout(() => setStoreLogoMsg(""), 3000);
        }
    };

    const removeStoreLogo = async () => {
        setStoreLogoMsg("");
        setStoreLogoSaving(true);
        try {
            const res = await smartFetch(`/agent/store-logo`, {
                method: "POST",
                headers: agentHeaders(),
                body: JSON.stringify({ agent_id: user.id, logo_base64: "" }),
            });
            const data = await res.json();
            if (data.status === "success") {
                setStoreLogo("");
                setStoreLogoPreview("");
                setStoreLogoMsg("Removed — back to the default EVOS logo");
            } else {
                setStoreLogoMsg(data.error || "Failed to remove logo");
            }
        } catch { setStoreLogoMsg("Network error"); }
        finally {
            setStoreLogoSaving(false);
            setTimeout(() => setStoreLogoMsg(""), 3000);
        }
    };

    return (
        <div style={styles.container}>
            <div style={styles.header}>
                <div style={styles.headerBadge}>🎨 Store Settings</div>
                <h2 style={styles.title}>Customize Your Store</h2>
                <p style={styles.subtitle}>Your link, display name, and logo</p>
            </div>

            <div style={styles.wrapper}>
                <div style={styles.box}>
                    {error && <div style={styles.errorBox}>⚠️ {error}</div>}

                    {loading ? (
                        <div style={styles.emptyBox}>
                            <div style={{ fontSize: 32, marginBottom: 8 }}>⏳</div>
                            <p style={styles.emptyText}>Loading your store settings...</p>
                        </div>
                    ) : (
                        <>
                            <div style={styles.card}>
                                <div style={styles.cardHeader}>
                                    <span style={styles.cardTitle}>🏪 Your Store Link</span>
                                    <span style={styles.storeLinkBadge}>Live</span>
                                </div>
                                <div style={styles.storeLinkText}>{storeLink}</div>
                                <div style={styles.storeLinkBtns}>
                                    <button style={styles.copyBtn} onClick={copyLink}>{copied ? "✅ Copied!" : "📋 Copy Link"}</button>
                                    <button style={styles.visitBtn} onClick={() => window.open(storeLink, "_blank")}>🔗 Visit Store</button>
                                </div>
                            </div>

                            <div style={styles.card}>
                                <div style={styles.cardHeader}>
                                    <span style={styles.cardTitle}>✏️ Store Display Name</span>
                                    {storeName && (
                                        <span style={styles.cardCurrent}>
                                            Current: <strong style={{ color: "#c8ff3e" }}>{storeName}</strong>
                                        </span>
                                    )}
                                </div>
                                <p style={styles.cardHint}>
                                    This name appears on your store page and in your store link. e.g.{" "}
                                    <span style={{ color: "#c8ff3e", fontFamily: "monospace", fontSize: 11 }}>
                                        /store/{user?.id}/{storeName ? slugify(storeName) : "your-store-name"}
                                    </span>
                                </p>
                                <input
                                    type="text"
                                    placeholder={`e.g. ${user?.username || "My Data Store"}`}
                                    value={storeNameInput}
                                    maxLength={40}
                                    onChange={(e) => setStoreNameInput(e.target.value)}
                                    style={styles.cardInput}
                                />
                                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                                    <span style={{ fontSize: 11, color: "#7a6fa3" }}>{storeNameInput.length}/40 characters</span>
                                    {storeNameMsg && (
                                        <span style={{ fontSize: 12, fontWeight: 700, color: storeNameMsg.startsWith("✅") ? "#22c55e" : "#f87171" }}>
                                            {storeNameMsg}
                                        </span>
                                    )}
                                </div>
                                <button
                                    onClick={saveStoreName}
                                    disabled={storeNameSaving || storeNameInput.trim() === storeName}
                                    style={{
                                        ...styles.cardBtn,
                                        opacity: storeNameSaving || storeNameInput.trim() === storeName ? 0.5 : 1,
                                        cursor:  storeNameSaving || storeNameInput.trim() === storeName ? "not-allowed" : "pointer",
                                    }}
                                >
                                    {storeNameSaving ? "Saving..." : "Save Store Name"}
                                </button>
                            </div>

                            <div style={styles.card}>
                                <div style={styles.cardHeader}>
                                    <span style={styles.cardTitle}>🖼️ Store Logo</span>
                                </div>
                                <p style={styles.cardHint}>
                                    Shown at the top of your store page. If you don't set one,
                                    customers see the default EVOS logo instead.
                                </p>

                                <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 12 }}>
                                    <img
                                        src={storeLogoPreview || asset("evosdata.png")}
                                        alt="Store logo preview"
                                        style={{
                                            width: 64, height: 64, objectFit: "cover", borderRadius: 14,
                                            border: "1px solid rgba(255,255,255,0.08)", background: "rgba(10,8,20,0.75)",
                                        }}
                                    />
                                    <label style={styles.logoChooseBtn}>
                                        Choose Image
                                        <input type="file" accept="image/*" onChange={handleLogoFile} style={{ display: "none" }} />
                                    </label>
                                </div>

                                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                                    <span style={{ fontSize: 11, color: "#7a6fa3" }}>Square images work best</span>
                                    {storeLogoMsg && (
                                        <span style={{ fontSize: 12, fontWeight: 700, color: storeLogoMsg.startsWith("✅") ? "#22c55e" : storeLogoMsg.startsWith("Removed") ? "#b4acd0" : "#f87171" }}>
                                            {storeLogoMsg}
                                        </span>
                                    )}
                                </div>

                                <div style={{ display: "flex", gap: 8 }}>
                                    <button
                                        onClick={saveStoreLogo}
                                        disabled={storeLogoSaving || !storeLogoPreview || storeLogoPreview === storeLogo}
                                        style={{
                                            ...styles.cardBtn,
                                            marginTop: 0,
                                            opacity: storeLogoSaving || !storeLogoPreview || storeLogoPreview === storeLogo ? 0.5 : 1,
                                            cursor:  storeLogoSaving || !storeLogoPreview || storeLogoPreview === storeLogo ? "not-allowed" : "pointer",
                                        }}
                                    >
                                        {storeLogoSaving ? "Saving..." : "Save Logo"}
                                    </button>
                                    {storeLogo && (
                                        <button
                                            onClick={removeStoreLogo}
                                            disabled={storeLogoSaving}
                                            style={{
                                                marginTop: 0, padding: "12px", borderRadius: 12, border: "1px solid rgba(239,68,68,0.3)",
                                                background: "rgba(239,68,68,0.1)", color: "#f87171", fontWeight: 800, fontSize: 13,
                                                opacity: storeLogoSaving ? 0.5 : 1, cursor: storeLogoSaving ? "not-allowed" : "pointer",
                                            }}
                                        >
                                            Remove
                                        </button>
                                    )}
                                </div>
                            </div>
                        </>
                    )}

                    <button style={styles.backDashBtn} onClick={() => setPage("agent-dashboard")}>← Back to Dashboard</button>
                </div>
            </div>
        </div>
    );
}

const styles = {
    container: { padding: "28px 18px 80px", minHeight: "auto", fontFamily: "'Nunito', 'Poppins', ui-rounded, system-ui, Arial", color: "#241c3d" },
    header: { textAlign: "center", marginBottom: 20 },
    headerBadge: { display: "inline-block", padding: "5px 18px", borderRadius: 50, background: "linear-gradient(135deg, #e0e7ff, #ddd6fe)", border: "1px solid #c4b5fd", color: "#6d28d9", fontSize: 12, fontWeight: 800, marginBottom: 10, letterSpacing: "0.5px" },
    title: { fontSize: 26, fontWeight: 900, color: "#f3f0fb", margin: "0 0 6px", letterSpacing: "-0.5px" },
    subtitle: { fontSize: 13, color: "#9189b5", margin: 0, fontWeight: 600 },
    wrapper: { maxWidth: 520, margin: "0 auto" },
    box: { background: "rgba(22,17,38,0.85)", backdropFilter: "blur(20px)", WebkitBackdropFilter: "blur(20px)", padding: "24px 20px", borderRadius: 24, border: "1px solid rgba(255,255,255,0.07)", boxShadow: "0 8px 40px rgba(0,0,0,0.3)" },
    errorBox: { background: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.3)", color: "#f87171", padding: "12px 16px", borderRadius: 12, fontSize: 14, marginBottom: 16 },
    emptyBox: { textAlign: "center", padding: "30px 0" },
    emptyText: { color: "#9189b5", fontSize: 14, margin: 0, fontWeight: 600 },
    card: { background: "rgba(10,8,20,0.4)", border: "1px solid rgba(255,255,255,0.07)", borderRadius: 18, padding: "18px 16px", marginBottom: 16 },
    cardHeader: { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 },
    cardTitle: { fontWeight: 800, fontSize: 14, color: "#f3f0fb" },
    cardCurrent: { fontSize: 12, color: "#9189b5" },
    cardHint: { fontSize: 12, color: "#7a6fa3", margin: "0 0 12px", lineHeight: 1.6 },
    cardInput: { width: "100%", padding: "12px 14px", borderRadius: 12, border: "1px solid rgba(255,255,255,0.08)", background: "rgba(10,8,20,0.75)", color: "#e5e7eb", fontSize: 14, marginBottom: 8, boxSizing: "border-box", outline: "none" },
    cardBtn: { marginTop: 10, width: "100%", padding: "12px", borderRadius: 12, border: "none", background: "linear-gradient(135deg, #c8ff3e, #8fe600)", color: "#000", fontWeight: 900, fontSize: 14, cursor: "pointer" },
    logoChooseBtn: { padding: "10px 16px", borderRadius: 12, border: "1px solid rgba(200,255,62,0.3)", background: "rgba(200,255,62,0.1)", color: "#c8ff3e", fontWeight: 800, fontSize: 13, cursor: "pointer" },
    storeLinkBadge: { fontSize: 10, fontWeight: 800, padding: "2px 8px", borderRadius: 50, background: "rgba(34,197,94,0.15)", border: "1px solid rgba(34,197,94,0.3)", color: "#22c55e", textTransform: "uppercase" },
    storeLinkText: { fontSize: 13, color: "#9189b5", wordBreak: "break-all", lineHeight: 1.5, marginBottom: 14, background: "rgba(10,8,20,0.5)", padding: "10px 12px", borderRadius: 10, border: "1px solid rgba(255,255,255,0.05)" },
    storeLinkBtns: { display: "flex", gap: 10 },
    copyBtn: { flex: 1, padding: "11px", borderRadius: 12, border: "none", background: "linear-gradient(135deg, #c8ff3e, #8fe600)", color: "#000", fontWeight: 900, fontSize: 13, cursor: "pointer" },
    visitBtn: { flex: 1, padding: "11px", borderRadius: 12, border: "1px solid rgba(200,255,62,0.3)", background: "rgba(200,255,62,0.08)", color: "#c8ff3e", fontWeight: 800, fontSize: 13, cursor: "pointer" },
    backDashBtn: { width: "100%", padding: "12px", borderRadius: 14, background: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.1)", color: "#b4acd0", fontWeight: 700, fontSize: 13, cursor: "pointer", marginTop: 4 },
};
