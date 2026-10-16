import { useEffect, useState, useCallback } from "react";
import { asset } from "../lib/basePath";
import { hasNativePrompt, isIOS, isStandalone, promptInstall, subscribeInstall } from "../lib/install";
import { Icon } from "./Icons";

export function useInstall() {
  const [, force] = useState(0);
  useEffect(() => subscribeInstall(() => force((n) => n + 1)), []);
  const [help, setHelp] = useState(false);
  const standalone = isStandalone();
  const ios = isIOS();

  const install = useCallback(async () => {
    const res = await promptInstall();
    if (res === null) setHelp(true); // no native prompt: show manual steps
  }, []);

  return { standalone, ios, native: hasNativePrompt(), install, help, setHelp };
}

// Manual "how to install" sheet (iPhone Safari, or browsers without a native prompt)
export function InstallHelp({ ios, onClose }) {
  return (
    <>
      <div className="vy-scrim" style={{ zIndex: 10040 }} onClick={onClose} />
      <div className="vy-sheet" style={{ zIndex: 10050 }} role="dialog" aria-label="Install EVOS Data">
        <div className="vy-grab" />
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <img src={asset("icons/icon-192.png")} alt="" width="52" height="52" style={{ borderRadius: 15 }} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <h3 style={{ fontSize: 19 }}>Install EVOS Data</h3>
            <p style={{ fontSize: 12.5 }}>Opens like a real app — no store needed.</p>
          </div>
          <button className="cm-x" style={{ position: "static" }} onClick={onClose} aria-label="Close">✕</button>
        </div>
        <div className="vy-steps">
          {ios ? (
            <>
              <div className="vy-step"><b>1</b><span>Tap the <strong>Share</strong> button <span style={{ verticalAlign: "-4px" }}><Icon name="share" size={18} /></span> in Safari's toolbar.</span></div>
              <div className="vy-step"><b>2</b><span>Scroll and tap <strong>Add to Home Screen</strong>.</span></div>
              <div className="vy-step"><b>3</b><span>Tap <strong>Add</strong> — EVOS Data is now on your home screen.</span></div>
            </>
          ) : (
            <>
              <div className="vy-step"><b>1</b><span>Open your browser menu (<strong>⋮</strong> or <strong>⋯</strong>).</span></div>
              <div className="vy-step"><b>2</b><span>Tap <strong>Install app</strong> or <strong>Add to Home screen</strong>.</span></div>
              <div className="vy-step"><b>3</b><span>Confirm — EVOS Data now lives on your device.</span></div>
            </>
          )}
        </div>
      </div>
    </>
  );
}

// Slim banner that slides up once per few days if the app isn't installed yet.
export function InstallBanner({ install, ios, standalone, native, hidden }) {
  const [show, setShow] = useState(false);
  const recentlyDismissed = () => {
    try { return Date.now() - Number(localStorage.getItem("evosInstallDismissed") || 0) < 3 * 24 * 3600 * 1000; } catch { return false; }
  };
  const installed = () => { try { return localStorage.getItem("evosInstalled") === "1"; } catch { return false; } };

  useEffect(() => {
    if (standalone || installed() || recentlyDismissed() || hidden) return;
    if (!native && !ios) return; // only nag when we can actually help
    const t = setTimeout(() => setShow(true), 6000);
    return () => clearTimeout(t);
  }, [standalone, native, ios, hidden]);

  if (!show || standalone) return null;
  const close = () => { try { localStorage.setItem("evosInstallDismissed", String(Date.now())); } catch { /* ignore */ } setShow(false); };

  return (
    <div className="vy-install" role="dialog" aria-label="Install the app">
      <img src={asset("icons/icon-192.png")} alt="" />
      <div className="t">
        <b>Get the EVOS Data app</b>
        <span>Faster ordering, one tap from your home screen.</span>
      </div>
      <button className="vy-pill vy-pill-solid" onClick={() => { setShow(false); install(); }}>Install</button>
      <button className="x" onClick={close} aria-label="Close">✕</button>
    </div>
  );
}
