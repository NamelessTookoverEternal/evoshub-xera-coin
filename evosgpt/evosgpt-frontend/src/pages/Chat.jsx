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
    <div style={{ position: "relative", maxWidth: "82%" }}>
      <div style={{ ...S.bubble, ...S.botBubble }}>
        <Markdown text={content} />
      </div>
      <button onClick={copy} style={S.copyFloating}>
        {copied ? "✓ Copied" : "📋 Copy"}
      </button>
    </div>
  );
}

export default function Chat({ setPage, user, setUser }) {
  const [messages, setMessages]       = useState([]);
  const [input, setInput]             = useState("");
  const [sending, setSending]         = useState(false);
  const [loadingHist, setLoadHist]    = useState(true);
  const [tier, setTier]               = useState(user?.evosgpt_tier || "Basic");
  const [todayCount, setToday]        = useState(0);
  const [dayLimit, setDayLimit]       = useState(null);
  const [nudge, setNudge]             = useState(false);
  const [limitHit, setLimitHit]       = useState(false);
  const [menuOpen, setMenuOpen]       = useState(false);
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

  const canGenerateImages = tier !== "Basic";

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
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 22 }}>⚡</span>
          <span style={S.brand}>EVOSGPT</span>
          <span style={{ ...S.tierBadge, color: badge.color, borderColor: badge.color + "55", background: badge.color + "18" }}>
            {badge.icon} {tier}
          </span>
        </div>
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          {dayLimit && <span style={S.counter}>{todayCount}/{dayLimit} today</span>}
          <button style={S.iconBtn} onClick={() => setMenuOpen(!menuOpen)}>☰</button>
        </div>
      </header>

      {/* MENU DROPDOWN */}
      {menuOpen && (
        <div style={S.menu} className="slide-up">
          <div style={S.menuItem} onClick={() => { setPage("dashboard"); setMenuOpen(false); }}>🏠 Dashboard</div>
          {tier === "Basic" && <div style={S.menuItem} onClick={() => { setPage("upgrade"); setMenuOpen(false); }}>⚡ Upgrade</div>}
          <div style={S.menuItem} onClick={() => { handleClear(); setMenuOpen(false); }}>🗑️ Clear Memory</div>
          <div style={S.menuItem} onClick={() => openProduct(EVOSDATA_URL)}>📶 Buy Data (EvosData)</div>
        </div>
      )}

      {/* MESSAGES */}
      <div style={S.body} ref={bodyRef} onScroll={handleScroll}>
        {loadingHist ? (
          <div style={S.emptyState}>⏳ Loading your conversation...</div>
        ) : messages.length === 0 ? (
          <div style={S.emptyState}>
            <div style={{ fontSize: 40, marginBottom: 10 }}>👋</div>
            <div style={{ fontWeight: 800, fontSize: 16, color: "#f1f5f9", marginBottom: 6 }}>
              Hey {user?.full_name?.split(" ")[0] || user?.username}!
            </div>
            <div style={{ color: "#64748b", fontSize: 14 }}>
              Ask me anything — code, letters, ideas, business plans. I'll remember as we chat.
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
          <div style={{ ...S.msgRow, justifyContent: "flex-start" }}>
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
      <div style={S.inputBar}>
        <input
          type="file"
          accept="image/*"
          ref={fileRef}
          style={{ display: "none" }}
          onChange={handleFileSelect}
        />
        <button
          style={{ ...S.attachBtn, opacity: limitHit || imageMode ? 0.4 : 1 }}
          title="Attach an image to ask about"
          disabled={limitHit || imageMode}
          onClick={() => fileRef.current?.click()}
        >
          📎
        </button>
        <button
          style={{ ...S.attachBtn, opacity: limitHit ? 0.4 : 1, color: imageMode ? "#a78bfa" : "#94a3b8", borderColor: imageMode ? "rgba(167,139,250,0.5)" : "rgba(255,255,255,0.1)" }}
          title={canGenerateImages ? "Generate an image" : "Upgrade to Pro to generate images"}
          disabled={limitHit}
          onClick={toggleImageMode}
        >
          🎨
        </button>
        <button
          style={{ ...S.attachBtn, opacity: limitHit ? 0.4 : 1, color: docMode ? "#4ade80" : "#94a3b8", borderColor: docMode ? "rgba(74,222,128,0.5)" : "rgba(255,255,255,0.1)" }}
          title={canGenerateImages ? "Generate a PDF/Word document" : "Upgrade to Pro to generate documents"}
          disabled={limitHit}
          onClick={toggleDocMode}
        >
          📄
        </button>
        <textarea
          ref={taRef}
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
      </div>
    </div>
  );
}

const S = {
  wrap:      { display: "flex", flexDirection: "column", height: "100vh", background: "#070d1a" },
  header:    { display: "flex", justifyContent: "space-between", alignItems: "center", padding: "14px 18px", borderBottom: "1px solid rgba(255,255,255,0.06)", position: "relative", zIndex: 10 },
  brand:     { fontWeight: 900, fontSize: 17, background: "linear-gradient(135deg,#38bdf8,#a78bfa)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" },
  tierBadge: { fontSize: 11, fontWeight: 800, padding: "3px 10px", borderRadius: 50, border: "1px solid" },
  counter:   { fontSize: 12, color: "#64748b", fontWeight: 700 },
  iconBtn:   { width: 36, height: 36, borderRadius: 10, border: "none", background: "rgba(255,255,255,0.06)", color: "#e2e8f0", fontSize: 16, cursor: "pointer" },
  menu:      { position: "absolute", top: 58, right: 18, background: "#0f172a", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 14, padding: 8, zIndex: 50, minWidth: 200, boxShadow: "0 12px 30px rgba(0,0,0,0.5)" },
  menuItem:  { padding: "10px 14px", borderRadius: 10, fontSize: 14, color: "#e2e8f0", cursor: "pointer", fontWeight: 600 },
  body:      { flex: 1, overflowY: "auto", padding: "20px 16px 10px", display: "flex", flexDirection: "column", gap: 16, maxWidth: 760, margin: "0 auto", width: "100%", position: "relative" },
  emptyState:{ textAlign: "center", margin: "auto", maxWidth: 320 },
  msgRow:    { display: "flex" },
  bubble:    { padding: "12px 16px", borderRadius: 16, fontSize: 14.5, lineHeight: 1.6, wordBreak: "break-word" },
  userBubble:{ maxWidth: "82%", background: "linear-gradient(135deg,#38bdf8,#0ea5e9)", color: "#000", fontWeight: 600, borderBottomRightRadius: 4 },
  botBubble: { background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.06)", color: "#e2e8f0", borderBottomLeftRadius: 4 },
  copyFloating: { marginTop: 6, display: "inline-flex", alignItems: "center", gap: 4, background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.1)", color: "#64748b", fontSize: 11, fontWeight: 700, padding: "3px 10px", borderRadius: 6, cursor: "pointer", transition: "color 0.2s" },

  // Scroll button group — sits between messages and nudge/input
  scrollBtnGroup:  { display: "flex", gap: 6, justifyContent: "center", padding: "6px 0 2px", maxWidth: 760, margin: "0 auto", width: "100%" },
  scrollBtnSmooth: { display: "flex", alignItems: "center", justifyContent: "center", gap: 0, background: "#0f172a", border: "1px solid rgba(255,255,255,0.15)", color: "#94a3b8", fontSize: 13, fontWeight: 800, padding: "5px 14px", borderRadius: 50, cursor: "pointer", letterSpacing: 1 },
  scrollBtnInstant:{ display: "flex", alignItems: "center", justifyContent: "center", gap: 0, background: "#0f172a", border: "1px solid rgba(56,189,248,0.3)", color: "#38bdf8", fontSize: 13, fontWeight: 800, padding: "5px 14px", borderRadius: 50, cursor: "pointer", letterSpacing: 1 },
  // The arrows are rotated 90deg to point downward
  scrollArrow: { display: "inline-block", transform: "rotate(90deg)", lineHeight: 1, fontSize: 16 },

  nudgeBox:  { maxWidth: 760, margin: "0 auto 10px", width: "calc(100% - 32px)", background: "rgba(56,189,248,0.08)", border: "1px solid rgba(56,189,248,0.25)", borderRadius: 16, padding: "14px 18px", display: "flex", justifyContent: "space-between", alignItems: "center", gap: 14, flexWrap: "wrap" },
  limitBox:  { maxWidth: 760, margin: "0 auto 10px", width: "calc(100% - 32px)", background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.25)", borderRadius: 16, padding: "16px 18px" },
  nudgeBtn:  { padding: "8px 16px", borderRadius: 10, border: "none", background: "#38bdf8", color: "#000", fontWeight: 800, fontSize: 13, cursor: "pointer" },
  nudgeGhost:{ padding: "8px 14px", borderRadius: 10, border: "1px solid rgba(255,255,255,0.15)", background: "transparent", color: "#94a3b8", fontWeight: 700, fontSize: 13, cursor: "pointer" },
  inputBar:  { display: "flex", gap: 8, padding: "14px 16px 20px", borderTop: "1px solid rgba(255,255,255,0.06)", maxWidth: 760, margin: "0 auto", width: "100%", boxSizing: "border-box", alignItems: "flex-end" },
  textarea:  { flex: 1, resize: "none", padding: "13px 16px", borderRadius: 16, border: "1px solid rgba(255,255,255,0.1)", background: "rgba(255,255,255,0.04)", color: "#f1f5f9", fontSize: 14.5, outline: "none", minHeight: 50, maxHeight: 160, fontFamily: "inherit", lineHeight: 1.55, transition: "height 0.1s ease" },
  sendBtn:   { width: 46, height: 46, borderRadius: "50%", border: "none", background: "linear-gradient(135deg,#38bdf8,#0ea5e9)", color: "#000", fontSize: 18, cursor: "pointer", flexShrink: 0 },
  attachBtn: { width: 46, height: 46, borderRadius: 14, border: "1px solid rgba(255,255,255,0.1)", background: "rgba(255,255,255,0.04)", fontSize: 18, cursor: "pointer", flexShrink: 0 },

  pendingImageBar: { display: "flex", alignItems: "center", gap: 10, maxWidth: 760, margin: "0 auto", width: "calc(100% - 32px)", background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 14, padding: "8px 10px", marginBottom: 8 },
  pendingImageThumb: { width: 40, height: 40, borderRadius: 8, objectFit: "cover" },
  pendingImageRemove:{ background: "none", border: "none", color: "#94a3b8", fontSize: 14, fontWeight: 800, cursor: "pointer", padding: "2px 6px" },
  modeToggleBtn:      { fontSize: 11, fontWeight: 700, padding: "5px 10px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.12)", background: "transparent", color: "#94a3b8", cursor: "pointer", whiteSpace: "nowrap" },
  modeToggleBtnActive:{ background: "rgba(167,139,250,0.18)", borderColor: "rgba(167,139,250,0.5)", color: "#a78bfa" },
  imageModeBar: { display: "flex", alignItems: "center", justifyContent: "space-between", maxWidth: 760, margin: "0 auto", width: "calc(100% - 32px)", background: "rgba(167,139,250,0.08)", border: "1px solid rgba(167,139,250,0.25)", borderRadius: 14, padding: "8px 12px", marginBottom: 8 },
  docSelect: { fontSize: 11, fontWeight: 700, padding: "5px 6px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.15)", background: "#0f172a", color: "#e2e8f0", cursor: "pointer" },
};
