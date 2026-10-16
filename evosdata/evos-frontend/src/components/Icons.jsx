// Small inline icon set (stroke icons, inherit currentColor) — crisp at any size.
const base = (size) => ({ width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round", strokeLinejoin: "round", "aria-hidden": true });

export const Icon = ({ name, size = 20 }) => {
  const p = base(size);
  switch (name) {
    case "home": return <svg {...p}><path d="M3 11.5 12 4l9 7.5" /><path d="M5 10v10h5v-6h4v6h5V10" /></svg>;
    case "bolt": return <svg {...p}><path d="M13 2 4 14h7l-1 8 9-12h-7z" /></svg>;
    case "box": return <svg {...p}><path d="M21 8 12 3 3 8v8l9 5 9-5z" /><path d="m3 8 9 5 9-5M12 13v8" /></svg>;
    case "chart": return <svg {...p}><path d="M4 20V10M10 20V4M16 20v-7M22 20H2" /></svg>;
    case "pin": return <svg {...p}><path d="M12 21s7-6.2 7-11.5A7 7 0 0 0 5 9.5C5 14.8 12 21 12 21z" /><circle cx="12" cy="9.5" r="2.5" /></svg>;
    case "cap": return <svg {...p}><path d="m2 9 10-5 10 5-10 5z" /><path d="M6 11.5V16c0 1.5 3 3 6 3s6-1.5 6-3v-4.5" /></svg>;
    case "rocket": return <svg {...p}><path d="M5 15c-1.5 1.2-2 4-2 6 2 0 4.8-.5 6-2" /><path d="M12 15 9 12c1-4 4-8 11-9 0 7-4 10-8 12z" /><circle cx="15.5" cy="8.5" r="1.4" /></svg>;
    case "store": return <svg {...p}><path d="M3 9 5 4h14l2 5" /><path d="M4 9v11h16V9" /><path d="M3 9a3 3 0 0 0 6 0 3 3 0 0 0 6 0 3 3 0 0 0 6 0" /></svg>;
    case "tag": return <svg {...p}><path d="M3 12V4h8l10 10-8 8z" /><circle cx="7.5" cy="8.5" r="1.3" /></svg>;
    case "wallet": return <svg {...p}><path d="M3 7a2 2 0 0 1 2-2h13v4" /><path d="M3 7v11a2 2 0 0 0 2 2h15V9H5a2 2 0 0 1-2-2z" /><circle cx="16.5" cy="14.5" r="1.2" /></svg>;
    case "signal": return <svg {...p}><path d="M4 20v-3M9 20v-7M14 20V9M19 20V4" /></svg>;
    case "user": return <svg {...p}><circle cx="12" cy="8" r="4" /><path d="M4 21c0-4 3.6-7 8-7s8 3 8 7" /></svg>;
    case "menu": return <svg {...p}><path d="M4 7h16M4 12h16M4 17h10" /></svg>;
    case "close": return <svg {...p}><path d="M6 6l12 12M18 6 6 18" /></svg>;
    case "login": return <svg {...p}><path d="M15 4h4a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1h-4" /><path d="M10 17l5-5-5-5M15 12H4" /></svg>;
    case "logout": return <svg {...p}><path d="M9 4H5a1 1 0 0 0-1 1v14a1 1 0 0 0 1 1h4" /><path d="m16 17 5-5-5-5M21 12H9" /></svg>;
    case "download": return <svg {...p}><path d="M12 3v12M7 10l5 5 5-5M4 21h16" /></svg>;
    case "share": return <svg {...p}><path d="M12 15V3M8 7l4-4 4 4" /><path d="M5 12v7a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-7" /></svg>;
    case "plus-box": return <svg {...p}><rect x="4" y="4" width="16" height="16" rx="4" /><path d="M12 8v8M8 12h8" /></svg>;
    case "gift": return <svg {...p}><rect x="3" y="8" width="18" height="4" rx="1" /><path d="M5 12v8h14v-8M12 8v12" /><path d="M12 8C10 8 7.5 7.3 7.5 5.5 7.5 4 9 3.5 10 4c1.2.6 2 2.5 2 4zM12 8c2 0 4.5-.7 4.5-2.5C16.5 4 15 3.5 14 4c-1.2.6-2 2.5-2 4z" /></svg>;
    case "shield": return <svg {...p}><path d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6z" /><path d="m9 12 2 2 4-4" /></svg>;
    default: return null;
  }
};

export const WhatsAppIcon = ({ size = 28 }) => (
  <svg width={size} height={size} viewBox="0 0 32 32" fill="currentColor" aria-hidden="true">
    <path d="M16.04 3C9.4 3 4 8.38 4 15.01c0 2.12.55 4.18 1.6 6L4 29l8.2-1.56a12.02 12.02 0 0 0 3.84.62h.01C22.68 28.06 28 22.67 28 16.05 28 9.4 22.68 3 16.04 3zm0 22.04h-.01c-1.2 0-2.37-.32-3.4-.93l-.24-.15-4.86.92.95-4.74-.16-.25a9.9 9.9 0 0 1-1.52-5.28c0-5.46 4.45-9.9 9.92-9.9 5.46 0 9.9 4.44 9.9 9.9 0 5.47-4.44 9.43-9.58 10.43zM21.5 18.2c-.3-.15-1.77-.87-2.04-.97-.27-.1-.47-.15-.67.15-.2.3-.77.97-.94 1.17-.17.2-.35.22-.65.07-.3-.15-1.27-.47-2.4-1.5-.9-.8-1.5-1.78-1.67-2.08-.17-.3-.02-.46.13-.6.13-.14.3-.35.45-.52.15-.17.2-.3.3-.5.1-.2.05-.37-.03-.52-.07-.15-.67-1.62-.92-2.22-.24-.58-.49-.5-.67-.51h-.57c-.2 0-.52.07-.8.37-.27.3-1.04 1.02-1.04 2.48 0 1.46 1.07 2.88 1.22 3.08.15.2 2.1 3.2 5.08 4.49.71.3 1.27.49 1.7.63.72.23 1.37.2 1.88.12.57-.08 1.77-.72 2.02-1.42.25-.7.25-1.3.17-1.42-.07-.12-.27-.2-.57-.35z" />
  </svg>
);
