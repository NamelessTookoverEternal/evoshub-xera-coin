// Bottom tab bar: Home / Chat / Plans / Me. Shown on the browse screens (not inside the chat or the sign-in forms).
const Icon = ({ d, extra }) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d={d} />{extra}
  </svg>
);

const ICONS = {
  home: <Icon d="M3 11.5 12 4l9 7.5M5.5 10v9.5h13V10" />,
  chat: <Icon d="M20 12a8 8 0 0 1-11.6 7.1L4 20l1-4A8 8 0 1 1 20 12Z" />,
  plans: <Icon d="M13 2 4 14h7l-1 8 9-12h-7l1-8Z" />,
  me: <Icon d="M20 21a8 8 0 0 0-16 0M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z" />,
};

export default function TabBar({ page, setPage, user }) {
  const tabs = [
    { id: "home", label: "Home", go: "home" },
    { id: "chat", label: "Chat", go: "chat", cls: "chat-tab" },
    { id: "upgrade", label: "Plans", go: "upgrade", icon: "plans" },
    { id: "dashboard", label: user ? "Me" : "Sign in", go: user ? "dashboard" : "login", icon: "me" },
  ];
  return (
    <nav className="tabbar" aria-label="Main">
      {tabs.map((t) => (
        <button key={t.id} className={`tab ${t.cls || ""} ${page === t.id ? "active" : ""}`} onClick={() => setPage(t.go)}
                aria-current={page === t.id ? "page" : undefined}>
          {ICONS[t.icon || t.id]}
          {t.label}
        </button>
      ))}
    </nav>
  );
}
