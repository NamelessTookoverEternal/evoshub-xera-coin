import { useState, useEffect, useRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { sendMessage, generateImage, editImage, generateDocument, getMemory, clearMemory, getUser } from "../api";
import { EVOSDATA_URL, openProduct } from "../config";

const TIER_BADGE = {
  Basic:   { icon: "🧊", color: "#64748b" },
  Pro:     { icon: "⚡", color: "#38bdf8" },
  Core:    { icon: "🔥", color: "#a78bfa" },
  Founder: { icon: "👑", color: "#f59e0b" },
};

function CodeBlock({ value, language }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard.writeText(value);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <div style={{ margin: "10px 0", borderRadius: 8, overflow: "hidden", border: "1px solid rgba(255,255,255,0.08)" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", background: "rgba(56,189,248,0.08)", padding: "5px 12px", borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
        <span style={{ fontSize: 11, color: "#38bdf8", fontWeight: 700 }}>{language || "code"}</span>
        <button
          onClick={copy}
          style={{ background: "none", border: "1px solid rgba(255,255,255,0.15)", color: copied ? "#4ade80" : "#94a3b8", fontSize: 11, fontWeight: 700, padding: "2px 10px", borderRadius: 5, cursor: "pointer" }}
        >
          {copied ? "✓ Copied" : "Copy"}
        </button>
      </div>
      <pre style={{ margin: 0, padding: "14px 16px", background: "#020817", overflowX: "auto" }}>
        <code style={{ fontSize: 13, fontFamily: "monospace", color: "#e2e8f0" }}>{value}</code>
      </pre>
    </div>
  );
}

function Markdown({ text }) {
  return (
    <div className="md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          code({ node, className, children, ...props }) {
            const value = String(children).replace(/\n$/, "");
            const language = className?.replace("language-", "") || "";
            const isBlock = Boolean(className);
            if (!isBlock) return (
              <code style={{ background: "rgba(255,255,255,0.08)", padding: "1px 6px", borderRadius: 4, fontSize: 13, fontFamily: "monospace", color: "#38bdf8" }}>
                {value}
              </code>
            );
            return <CodeBlock value={value} language={language} />;
          },
          img({ src, alt }) {
            return (
              <img
                src={src}
                alt={alt || "Generated image"}
                style={{ maxWidth: "100%", borderRadius: 12, margin: "6px 0", display: "block" }}
                loading="lazy"
              />
            );
          },
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}

function BotBubble({ content }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard.writeText(content);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <div style={{ display: "flex", gap: 10, alignItems: "flex-start", maxWidth: "92%" }}>
      <span className="orb sm" style={{ marginTop: 2 }} aria-hidden="true" />
      <div style={{ position: "relative", minWidth: 0 }}>
        <div style={{ ...S.bubble, ...S.botBubble }}>
          <Markdown text={content} />
        </div>
        <button onClick={copy} style={S.copyFloating}>
          {copied ? "✓ Copied" : "Copy"}
        </button>
      </div>
    </div>
  );
}

export default function Chat({ setPage, user, setUser }) {
  const [messages, setMessages]       = useState([]);
  const [input, setInput]             = useState(() => {
    try { const v = sessionStorage.getItem("evosgpt_prefill") || ""; if (v) sessionStorage.removeItem("evosgpt_prefill"); return v; } catch { return ""; }
  });
  const [sending, setSending]         = useState(false);
  const [loadingHist, setLoadHist]    = useState(true);
  const [tier, setTier]               = useState(user?.evosgpt_tier || "Basic");
  const [todayCount, setToday]        = useState(0);
  const [dayLimit, setDayLimit]       = useState(null);
  const [nudge, setNudge]             = useState(false);
  const [limitHit, setLimitHit]       = useState(false);
  const [menuOpen, setMenuOpen]       = useState(false);
  const [plusOpen, setPlusOpen]       = useState(false); // "+" attach/create menu next to the message box
  const [showScrollBtn, setShowScrollBtn] = useState(false);

  // Image generation + vision upload
  const [imageMode, setImageMode]     = useState(false); // 🎨 generate-image mode
  const [pendingImage, setPendingImage] = useState(null); // { base64, mime, previewUrl }
  const [editMode, setEditMode]       = useState(false); // true = "Edit this image" instead of "Ask about it"

  // Document generation (PDF / Word)
  const [docMode, setDocMode]         = useState(false); // 📄 generate-document mode
  const [docFormat, setDocFormat]     = useState("pdf");  // "pdf" | "docx"
  const [docPaperSize, setDocPaperSize] = useState("A4"); // "A4" | "A5" | "LETTER" | "LEGAL"

  const bottomRef = useRef(null);
  const bodyRef   = useRef(null);
  const taRef     = useRef(null);
  const fileRef   = useRef(null);
  const plusRef   = useRef(null);

  const canGenerateImages = tier !== "Basic";

  // Close the "+" menu on outside click or Escape.
  useEffect(() => {
    if (!plusOpen) return;
    const onDown = (e) => { if (plusRef.current && !plusRef.current.contains(e.target)) setPlusOpen(false); };
    const onKey  = (e) => { if (e.key === "Escape") setPlusOpen(false); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("touchstart", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("touchstart", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [plusOpen]);

  useEffect(() => {
    if (!user) { setPage("login"); return; }
    loadHistory();
  }, [user]);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, sending]);

  const handleScroll = () => {
    const el = bodyRef.current;
    if (!el) return;
    const distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    setShowScrollBtn(distFromBottom > 60);
  };

  const scrollSmooth = () => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  const scrollInstant = () => {
    bottomRef.current?.scrollIntoView({ behavior: "auto" });
  };

  const loadHistory = async () => {
    try {
      setLoadHist(true);
      const { data } = await getMemory(user.id);
      setMessages((data.short_memory || []).map(m => ({ role: m.role, content: m.content })));
      const { data: u } = await getUser(user.id);
      setTier(u.user.evosgpt_tier);
      setToday(u.user.today_count);
      setDayLimit(u.user.day_limit);
    } catch (e) {
      console.error(e);
    } finally { setLoadHist(false); }
  };

  const handleFileSelect = (e) => {
    const file = e.target.files?.[0];
    e.target.value = ""; // allow re-selecting the same file later
    if (!file) return;
    if (!file.type.startsWith("image/")) return;
    const reader = new FileReader();
    reader.onload = () => {
      const dataUrl = reader.result; // "data:image/jpeg;base64,...."
      const [meta, base64] = dataUrl.split(",");
      const mime = meta.match(/data:(.*);base64/)?.[1] || "image/jpeg";
      setImageMode(false);
      setDocMode(false);
      setEditMode(false);
      setPendingImage({ base64, mime, previewUrl: dataUrl });
    };
    reader.readAsDataURL(file);
  };

  const toggleImageMode = () => {
    if (!canGenerateImages) {
      setNudge(true);
      return;
    }
    setPendingImage(null);
    setDocMode(false);
    setImageMode(v => !v);
  };

  const toggleDocMode = () => {
    if (!canGenerateImages) {
      setNudge(true);
      return;
    }
    setPendingImage(null);
    setImageMode(false);
    setDocMode(v => !v);
  };

  const send = async () => {
    const text = input.trim();
    if (!text || sending) return;
    setInput("");
    // Reset textarea height
    if (taRef.current) {
      taRef.current.style.height = "auto";
    }
    setSending(true);
    setNudge(false);

    // ---- Mode 0: generate a PDF/Word document from the prompt ----
    if (docMode) {
      setMessages(m => [...m, { role: "user", content: `📄 ${text}` }]);
      setDocMode(false);
      try {
        const { data } = await generateDocument({
          user_id: user.id,
          prompt: text,
          doc_format: docFormat,
          paper_size: docPaperSize,
        });

        if (data.status === "tier_restricted") {
          setMessages(m => [...m, { role: "assistant", content: data.reply }]);
          setNudge(true);
          return;
        }
        if (data.status === "letterhead_restricted") {
          setMessages(m => [...m, { role: "assistant", content: data.reply }]);
          return;
        }
        if (data.status === "limit_reached") {
          setLimitHit(true);
          setMessages(m => [...m, { role: "assistant", content: data.reply }]);
          return;
        }

        setMessages(m => [...m, { role: "assistant", content: data.reply }]);
        setTier(data.tier);
        setToday(data.today_count);
        setDayLimit(data.day_limit);
      } catch (e) {
        setMessages(m => [...m, { role: "assistant", content: "⚠️ Couldn't generate that document. Please try again." }]);
      } finally { setSending(false); }
      return;
    }

    // ---- Mode 1: generate an image from the prompt ----
    if (imageMode) {
      setMessages(m => [...m, { role: "user", content: `🎨 ${text}` }]);
      setImageMode(false);
      try {
        const { data } = await generateImage({ user_id: user.id, prompt: text });

        if (data.status === "tier_restricted") {
          setMessages(m => [...m, { role: "assistant", content: data.reply }]);
          setNudge(true);
          return;
        }
        if (data.status === "limit_reached") {
          setLimitHit(true);
          setMessages(m => [...m, { role: "assistant", content: data.reply }]);
          return;
        }

        setMessages(m => [...m, { role: "assistant", content: data.reply }]);
        setTier(data.tier);
        setToday(data.today_count);
        setDayLimit(data.day_limit);
      } catch (e) {
        setMessages(m => [...m, { role: "assistant", content: "⚠️ Couldn't generate that image. Please try again." }]);
      } finally { setSending(false); }
      return;
    }

    // ---- Mode 2a: edit the attached image ----
    if (pendingImage && editMode) {
      const attached = pendingImage;
      setPendingImage(null);
      setEditMode(false);
      setMessages(m => [...m, { role: "user", content: `✏️ ${text}`, image: attached.previewUrl }]);

      try {
        const { data } = await editImage({
          user_id: user.id,
          prompt: text,
          image_base64: attached.base64,
          image_mime: attached.mime,
        });

        if (data.status === "tier_restricted") {
          setMessages(m => [...m, { role: "assistant", content: data.reply }]);
          setNudge(true);
          return;
        }
        if (data.status === "letterhead_restricted") {
          setMessages(m => [...m, { role: "assistant", content: data.reply }]);
          return;
        }
        if (data.status === "limit_reached") {
          setLimitHit(true);
          setMessages(m => [...m, { role: "assistant", content: data.reply }]);
          return;
        }

        setMessages(m => [...m, { role: "assistant", content: data.reply }]);
        setTier(data.tier);
        setToday(data.today_count);
        setDayLimit(data.day_limit);
      } catch (e) {
        setMessages(m => [...m, { role: "assistant", content: "⚠️ Couldn't edit that image. Please try again." }]);
      } finally { setSending(false); }
      return;
    }

    // ---- Mode 2b: plain text, optionally with an attached image (vision) ----
    const attached = pendingImage;
    setPendingImage(null);
    setEditMode(false);
    setMessages(m => [...m, { role: "user", content: text, image: attached?.previewUrl }]);

    try {
      const { data } = await sendMessage({
        user_id: user.id,
        message: text,
        ...(attached ? { image_base64: attached.base64, image_mime: attached.mime } : {}),
      });

      if (data.limit_reached) {
        setLimitHit(true);
        setMessages(m => [...m, { role: "assistant", content: data.reply }]);
        return;
      }

      setMessages(m => [...m, { role: "assistant", content: data.reply }]);
      setTier(data.tier);
      setToday(data.today_count);
      setDayLimit(data.day_limit);
      if (data.show_upgrade_nudge) setNudge(true);
    } catch (e) {
      setMessages(m => [...m, { role: "assistant", content: "⚠️ Something went wrong. Please try again." }]);
    } finally { setSending(false); }
  };

  const handleClear = async () => {
    if (!confirm("Clear all memory? This cannot be undone.")) return;
    await clearMemory(user.id);
    setMessages([]);
  };

  const handleTextareaChange = (e) => {
    setInput(e.target.value);
    // Auto-expand
    e.target.style.height = "auto";
    e.target.style.height = Math.min(e.target.scrollHeight, 160) + "px";
  };

  const badge = TIER_BADGE[tier] || TIER_BADGE.Basic;

  return (
    <div style={S.wrap}>
      {/* HEADER */}
      <header style={S.header}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
          <button style={S.iconBtn} onClick={() => setPage("home")} aria-label="Back to home">‹</button>
          <span className="orb sm" aria-hidden="true" />
          <span style={S.brand}>EVOSGPT</span>
          <span style={{ ...S.tierBadge, color: badge.color, borderColor: badge.color + "55", background: badge.color + "18" }}>
            {badge.icon} {tier}
          </span>
        </div>
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          {dayLimit && <span style={S.counter}>{todayCount}/{dayLimit}</span>}
          <button style={S.iconBtn} onClick={() => setMenuOpen(!menuOpen)} aria-label="Menu">⋯</button>
        </div>
      </header>

      {/* MENU DROPDOWN */}
      {menuOpen && (
        <div style={S.menu} className="slide-up">
          <div style={S.menuItem} onClick={() => { setPage("home"); setMenuOpen(false); }}>🏠 Home</div>
          <div style={S.menuItem} onClick={() => { setPage("dashboard"); setMenuOpen(false); }}>👤 My dashboard</div>
          <div style={S.menuItem} onClick={() => { setPage("upgrade"); setMenuOpen(false); }}>⚡ {tier === "Basic" ? "Upgrade" : "Plans"}</div>
          <div style={S.menuItem} onClick={() => { handleClear(); setMenuOpen(false); }}>🗑️ Clear Memory</div>
          <div style={S.menuItem} onClick={() => openProduct(EVOSDATA_URL)}>📶 Buy Data (EvosData)</div>
        </div>
      )}

      {/* MESSAGES */}
      <div style={S.body} ref={bodyRef} onScroll={handleScroll}>
        {loadingHist ? (
          <div style={S.emptyState}>⏳ Loading your conversation...</div>
        ) : messages.length === 0 ? (
          <div style={S.emptyState} className="fade-in">
            <div className="orb md" style={{ marginBottom: 18 }} aria-hidden="true" />
            <div className="display" style={{ fontWeight: 700, fontSize: 24, marginBottom: 6, letterSpacing: "-0.02em" }}>
              Hey <span className="grad-text">{user?.full_name?.split(" ")[0] || user?.username}</span>
            </div>
            <div style={{ color: "var(--muted)", fontSize: 14.5, marginBottom: 20 }}>
              What would you like to do today? I remember as we chat.
            </div>
            <div style={S.suggestGrid}>
              {[
                ["✍️", "Write a letter", "Write a professional letter for me about "],
                ["💻", "Help with code", "Help me with this code: "],
                ["📊", "Business ideas", "Give me 5 practical small business ideas I can start in Ghana with little money."],
                ["🎓", "Explain simply", "Explain this in simple terms: "],
              ].map(([ic, label, text]) => (
                <button key={label} className="glass" style={S.suggest}
                        onClick={() => { setInput(text); taRef.current?.focus(); }}>
                  <span style={{ fontSize: 20 }}>{ic}</span>
                  <span style={{ fontWeight: 700, fontSize: 13.5 }}>{label}</span>
                </button>
              ))}
            </div>
          </div>
        ) : (
          messages.map((m, i) => (
            <div key={i} style={{ ...S.msgRow, justifyContent: m.role === "user" ? "flex-end" : "flex-start" }}>
              {m.role === "user" ? (
                <div style={{ ...S.bubble, ...S.userBubble }}>
                  {m.image && (
                    <img src={m.image} alt="Uploaded" style={{ maxWidth: "100%", borderRadius: 10, marginBottom: 8, display: "block" }} />
                  )}
                  {m.content}
                </div>
              ) : (
                <BotBubble content={m.content} />
              )}
            </div>
          ))
        )}

        {sending && (
          <div style={{ ...S.msgRow, justifyContent: "flex-start", gap: 10, alignItems: "center" }}>
            <span className="orb sm" aria-hidden="true" />
            <div style={{ ...S.bubble, ...S.botBubble }}>
              <span className="dot"></span><span className="dot"></span><span className="dot"></span>
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* SCROLL BUTTONS — shown only when not at bottom */}
      {showScrollBtn && (
        <div style={S.scrollBtnGroup}>
          {/* Smooth scroll — animated */}
          <button
            style={S.scrollBtnSmooth}
            title="Scroll to bottom (smooth)"
            onClick={scrollSmooth}
          >
            <span style={S.scrollArrow}>›</span>
          </button>
          {/* Instant jump — no animation */}
          <button
            style={S.scrollBtnInstant}
            title="Jump to bottom instantly"
            onClick={scrollInstant}
          >
            <span style={S.scrollArrow}>›</span>
            <span style={S.scrollArrow}>›</span>
          </button>
        </div>
      )}

      {/* UPGRADE NUDGE */}
      {nudge && (
        <div style={S.nudgeBox} className="slide-up">
          <div>
            <strong style={{ color: "#f1f5f9" }}>Enjoying the conversation? 🚀</strong>
            <p style={{ fontSize: 13, color: "#94a3b8", margin: "4px 0 0" }}>
              Upgrade to Pro for unlimited chats, or buy data on EvosData to stay connected.
            </p>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button style={S.nudgeBtn} onClick={() => setPage("upgrade")}>Upgrade</button>
            <button style={S.nudgeGhost} onClick={() => setNudge(false)}>✕</button>
          </div>
        </div>
      )}

      {/* LIMIT REACHED */}
      {limitHit && (
        <div style={S.limitBox} className="slide-up">
          <strong style={{ color: "#fca5a5" }}>Daily limit reached</strong>
          <p style={{ fontSize: 13, color: "#94a3b8", margin: "4px 0 10px" }}>
            Upgrade to Pro for unlimited chats — or come back tomorrow.
          </p>
          <div style={{ display: "flex", gap: 8 }}>
            <button style={S.nudgeBtn} onClick={() => setPage("upgrade")}>Upgrade to Pro</button>
            <button style={S.nudgeGhost} onClick={() => setLimitHit(false)}>Dismiss</button>
          </div>
        </div>
      )}

      {/* PENDING IMAGE PREVIEW (vision upload / edit) */}
      {pendingImage && (
        <div style={S.pendingImageBar}>
          <img src={pendingImage.previewUrl} alt="To send" style={S.pendingImageThumb} />
          <span style={{ fontSize: 12, color: "#94a3b8", flex: 1 }}>
            {editMode ? "Describe how to edit this image" : "Ask a question, or switch to Edit"}
          </span>
          <button
            style={{ ...S.modeToggleBtn, ...(editMode ? {} : S.modeToggleBtnActive) }}
            onClick={() => setEditMode(false)}
          >
            💬 Ask
          </button>
          <button
            style={{ ...S.modeToggleBtn, ...(editMode ? S.modeToggleBtnActive : {}) }}
            title={canGenerateImages ? "Edit this image" : "Upgrade to Pro to edit images"}
            onClick={() => { if (!canGenerateImages) { setNudge(true); return; } setEditMode(true); }}
          >
            ✏️ Edit
          </button>
          <button style={S.pendingImageRemove} onClick={() => { setPendingImage(null); setEditMode(false); }}>✕</button>
        </div>
      )}

      {/* DOCUMENT-GENERATION MODE BANNER */}
      {docMode && (
        <div style={S.imageModeBar}>
          <span style={{ fontSize: 12, color: "#4ade80", fontWeight: 700, flex: 1 }}>📄 Describe the PDF/Word document to generate</span>
          <select style={S.docSelect} value={docFormat} onChange={e => setDocFormat(e.target.value)}>
            <option value="pdf">PDF</option>
            <option value="docx">Word (.docx)</option>
          </select>
          <select style={S.docSelect} value={docPaperSize} onChange={e => setDocPaperSize(e.target.value)}>
            <option value="A4">A4</option>
            <option value="LETTER">Letter</option>
            <option value="LEGAL">Legal</option>
            <option value="A5">A5</option>
          </select>
          <button style={S.pendingImageRemove} onClick={() => setDocMode(false)}>✕</button>
        </div>
      )}

      {/* IMAGE-GENERATION MODE BANNER */}
      {imageMode && (
        <div style={S.imageModeBar}>
          <span style={{ fontSize: 12, color: "#a78bfa", fontWeight: 700 }}>🎨 Describe the image you want EVOSGPT to generate</span>
          <button style={S.pendingImageRemove} onClick={() => setImageMode(false)}>✕</button>
        </div>
      )}

      {/* INPUT */}
      <div style={S.inputOuter}><div style={S.inputBar} className="glass">
        <input
          type="file"
          accept="image/*"
          ref={fileRef}
          style={{ display: "none" }}
          onChange={handleFileSelect}
        />
        {/* "+" menu (like Claude / ChatGPT): attach an image, create an image, create a document */}
        <div ref={plusRef} style={{ position: "relative", flexShrink: 0 }}>
          {plusOpen && (
            <div style={S.plusMenu} role="menu">
              <button
                role="menuitem"
                style={{ ...S.plusItem, opacity: imageMode ? 0.4 : 1 }}
                disabled={imageMode}
                onClick={() => { setPlusOpen(false); fileRef.current?.click(); }}
              >
                <span style={S.plusIcon}>📎</span>
                <span style={{ flex: 1 }}>Add a photo</span>
              </button>
              <button
                role="menuitem"
                style={{ ...S.plusItem, color: imageMode ? "#a78bfa" : "#e2e8f0" }}
                onClick={() => { setPlusOpen(false); toggleImageMode(); }}
              >
                <span style={S.plusIcon}>🎨</span>
                <span style={{ flex: 1 }}>Create an image</span>
                {!canGenerateImages ? <span style={S.plusBadge}>Pro</span> : imageMode ? <span style={{ color: "#a78bfa" }}>✓</span> : null}
              </button>
              <button
                role="menuitem"
                style={{ ...S.plusItem, color: docMode ? "#4ade80" : "#e2e8f0" }}
                onClick={() => { setPlusOpen(false); toggleDocMode(); }}
              >
                <span style={S.plusIcon}>📄</span>
                <span style={{ flex: 1 }}>Create a document</span>
                {!canGenerateImages ? <span style={S.plusBadge}>Pro</span> : docMode ? <span style={{ color: "#4ade80" }}>✓</span> : null}
              </button>
            </div>
          )}
          <button
            style={{
              ...S.attachBtn, fontSize: 26, fontWeight: 300, lineHeight: 1, opacity: limitHit ? 0.4 : 1,
              color: (imageMode || docMode || plusOpen) ? "#f1f5f9" : "#94a3b8",
              background: plusOpen ? "rgba(255,255,255,0.14)" : "rgba(255,255,255,0.06)",
            }}
            title="Add photo, create image or document"
            aria-label="Add photo, create image or document"
            aria-haspopup="menu"
            aria-expanded={plusOpen}
            disabled={limitHit}
            onClick={() => setPlusOpen(o => !o)}
          >
            <span style={{ display: "inline-block", transform: plusOpen ? "rotate(45deg)" : "none", transition: "transform 0.15s ease" }}>+</span>
          </button>
        </div>
        <textarea
          ref={taRef}
          rows={1}
          style={{ ...S.textarea, overflowY: "hidden" }}
          placeholder={docMode ? "Describe the document to generate..." : imageMode ? "Describe the image to generate..." : (pendingImage && editMode) ? "Describe the edit you want..." : "Message EVOSGPT..."}
          value={input}
          disabled={limitHit}
          onChange={handleTextareaChange}
          onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
        />
        <button
          style={{ ...S.sendBtn, opacity: (!input.trim() || sending || limitHit) ? 0.4 : 1 }}
          onClick={send}
          disabled={!input.trim() || sending || limitHit}
        >
          ➤
        </button>
      </div></div>
    </div>
  );
}

const S = {
  wrap:      { display: "flex", flexDirection: "column", height: "100dvh", background: "transparent" },
  header:    { display: "flex", justifyContent: "space-between", alignItems: "center", padding: "calc(10px + var(--safe-t)) 14px 10px", borderBottom: "1px solid var(--line)", position: "relative", zIndex: 10, background: "rgba(6,9,18,0.55)", backdropFilter: "blur(18px)", WebkitBackdropFilter: "blur(18px)" },
  brand:     { fontFamily: "var(--display)", fontWeight: 700, fontSize: 17, background: "var(--grad)", WebkitBackgroundClip: "text", backgroundClip: "text", WebkitTextFillColor: "transparent" },
  tierBadge: { fontSize: 11, fontWeight: 800, padding: "3px 10px", borderRadius: 50, border: "1px solid", whiteSpace: "nowrap" },
  counter:   { fontSize: 12, color: "var(--muted)", fontWeight: 700 },
  iconBtn:   { width: 38, height: 38, borderRadius: 12, border: "1px solid var(--line)", background: "var(--panel)", color: "var(--text)", fontSize: 20, lineHeight: 1, cursor: "pointer" },
  menu:      { position: "absolute", top: "calc(58px + var(--safe-t))", right: 14, background: "rgba(14,18,34,0.96)", border: "1px solid var(--line)", borderRadius: 16, padding: 8, zIndex: 50, minWidth: 210, boxShadow: "0 16px 40px rgba(0,0,0,0.55)", backdropFilter: "blur(20px)" },
  menuItem:  { padding: "11px 14px", borderRadius: 11, fontSize: 14, color: "var(--text)", cursor: "pointer", fontWeight: 600 },
  body:      { flex: 1, overflowY: "auto", padding: "20px 16px 10px", display: "flex", flexDirection: "column", gap: 18, maxWidth: 780, margin: "0 auto", width: "100%", position: "relative" },
  emptyState:{ textAlign: "center", margin: "auto", maxWidth: 460, width: "100%" },
  suggestGrid: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 },
  suggest:   { display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 8, padding: "14px 14px", borderRadius: 18, color: "var(--text)", cursor: "pointer", textAlign: "left", fontFamily: "inherit" },
  msgRow:    { display: "flex" },
  bubble:    { padding: "12px 16px", borderRadius: 20, fontSize: 15, lineHeight: 1.65, wordBreak: "break-word" },
  userBubble:{ maxWidth: "84%", background: "linear-gradient(135deg,#38bdf8,#818cf8)", color: "#04101f", fontWeight: 600, borderBottomRightRadius: 6, boxShadow: "0 8px 26px rgba(99,102,241,0.28)" },
  botBubble: { background: "var(--panel)", border: "1px solid var(--line)", color: "var(--text)", borderTopLeftRadius: 6 },
  copyFloating: { marginTop: 6, display: "inline-flex", alignItems: "center", gap: 4, background: "transparent", border: "1px solid var(--line)", color: "var(--dim)", fontSize: 11, fontWeight: 700, padding: "3px 10px", borderRadius: 999, cursor: "pointer", transition: "color 0.2s" },

  // Scroll button group — sits between messages and nudge/input
  scrollBtnGroup:  { display: "flex", gap: 6, justifyContent: "center", padding: "6px 0 2px", maxWidth: 780, margin: "0 auto", width: "100%" },
  scrollBtnSmooth: { display: "flex", alignItems: "center", justifyContent: "center", gap: 0, background: "rgba(14,18,34,0.9)", border: "1px solid var(--line)", color: "var(--muted)", fontSize: 13, fontWeight: 800, padding: "5px 14px", borderRadius: 50, cursor: "pointer", letterSpacing: 1 },
  scrollBtnInstant:{ display: "flex", alignItems: "center", justifyContent: "center", gap: 0, background: "rgba(14,18,34,0.9)", border: "1px solid rgba(56,189,248,0.35)", color: "#38bdf8", fontSize: 13, fontWeight: 800, padding: "5px 14px", borderRadius: 50, cursor: "pointer", letterSpacing: 1 },
  // The arrows are rotated 90deg to point downward
  scrollArrow: { display: "inline-block", transform: "rotate(90deg)", lineHeight: 1, fontSize: 16 },

  nudgeBox:  { maxWidth: 780, margin: "0 auto 10px", width: "calc(100% - 32px)", background: "rgba(56,189,248,0.08)", border: "1px solid rgba(56,189,248,0.25)", borderRadius: 18, padding: "14px 18px", display: "flex", justifyContent: "space-between", alignItems: "center", gap: 14, flexWrap: "wrap" },
  limitBox:  { maxWidth: 780, margin: "0 auto 10px", width: "calc(100% - 32px)", background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.25)", borderRadius: 18, padding: "16px 18px" },
  nudgeBtn:  { padding: "8px 16px", borderRadius: 12, border: "none", background: "linear-gradient(135deg,#38bdf8,#818cf8)", color: "#04101f", fontWeight: 800, fontSize: 13, cursor: "pointer" },
  nudgeGhost:{ padding: "8px 14px", borderRadius: 12, border: "1px solid var(--line)", background: "transparent", color: "var(--muted)", fontWeight: 700, fontSize: 13, cursor: "pointer" },
  inputOuter:{ padding: "6px 12px calc(12px + var(--safe-b))", maxWidth: 780, margin: "0 auto", width: "100%", boxSizing: "border-box" },
  inputBar:  { display: "flex", gap: 6, padding: 6, borderRadius: 28, alignItems: "flex-end", boxShadow: "0 10px 40px rgba(0,0,0,0.35)" },
  textarea:  { flex: 1, minWidth: 0, resize: "none", padding: "11px 8px", borderRadius: 16, border: "none", background: "transparent", color: "var(--text)", fontSize: 15.5, outline: "none", minHeight: 44, maxHeight: 160, fontFamily: "inherit", lineHeight: 1.5, transition: "height 0.1s ease" },
  sendBtn:   { width: 44, height: 44, borderRadius: "50%", border: "none", background: "linear-gradient(135deg,#38bdf8,#818cf8)", color: "#04101f", fontSize: 17, fontWeight: 900, cursor: "pointer", flexShrink: 0 },
  plusMenu:  { position: "absolute", bottom: 54, left: 0, minWidth: 230, padding: 6, borderRadius: 18, background: "rgba(14,18,34,0.97)", border: "1px solid var(--line)", boxShadow: "0 16px 40px rgba(0,0,0,0.55)", display: "flex", flexDirection: "column", gap: 2, zIndex: 50 },
  plusItem:  { display: "flex", alignItems: "center", gap: 10, width: "100%", padding: "11px 12px", borderRadius: 12, border: "none", background: "transparent", color: "var(--text)", fontSize: 14, fontWeight: 600, cursor: "pointer", textAlign: "left", fontFamily: "inherit" },
  plusIcon:  { width: 22, textAlign: "center", fontSize: 16 },
  plusBadge: { fontSize: 10, fontWeight: 800, padding: "2px 7px", borderRadius: 999, background: "rgba(167,139,250,0.18)", color: "#a78bfa", letterSpacing: 0.4 },
  attachBtn: { width: 44, height: 44, borderRadius: "50%", border: "none", background: "var(--panel)", fontSize: 18, cursor: "pointer", flexShrink: 0 },

  pendingImageBar: { display: "flex", alignItems: "center", gap: 10, maxWidth: 780, margin: "0 auto", width: "calc(100% - 24px)", background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 16, padding: "8px 10px", marginBottom: 8 },
  pendingImageThumb: { width: 40, height: 40, borderRadius: 10, objectFit: "cover" },
  pendingImageRemove:{ background: "none", border: "none", color: "var(--muted)", fontSize: 14, fontWeight: 800, cursor: "pointer", padding: "2px 6px" },
  modeToggleBtn:      { fontSize: 11, fontWeight: 700, padding: "5px 10px", borderRadius: 9, border: "1px solid var(--line)", background: "transparent", color: "var(--muted)", cursor: "pointer", whiteSpace: "nowrap" },
  modeToggleBtnActive:{ background: "rgba(167,139,250,0.18)", borderColor: "rgba(167,139,250,0.5)", color: "#a78bfa" },
  imageModeBar: { display: "flex", alignItems: "center", justifyContent: "space-between", maxWidth: 780, margin: "0 auto", width: "calc(100% - 24px)", background: "rgba(167,139,250,0.08)", border: "1px solid rgba(167,139,250,0.25)", borderRadius: 16, padding: "8px 12px", marginBottom: 8 },
  docSelect: { fontSize: 11, fontWeight: 700, padding: "5px 6px", borderRadius: 8, border: "1px solid var(--line)", background: "#0f172a", color: "var(--text)", cursor: "pointer" },
};
