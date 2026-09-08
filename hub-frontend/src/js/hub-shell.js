/* EVOS HUB — shared app shell: sidebar (desktop), topbar, and bottom
 * nav (mobile). One small module so every Hub page (dashboard, settings,
 * and future product pages) gets the same chrome without copy-pasting
 * markup. Product pages that already have their own shell (XERA) don't
 * use this — it's for the Hub's own pages only. */

import { getUser, logout } from './evos-session.js';

const NAV_ITEMS = [
    { key: 'overview', label: 'Overview', href: '/hub/', icon: 'grid' },
    { key: 'data',     label: 'Data Services', href: '/hub/#data', icon: 'signal' },
    { key: 'xera',     label: 'XERA Mining', href: '/xera', icon: 'bolt' },
    { key: 'activity', label: 'Activity', href: '/hub/#activity', icon: 'clock' },
    { key: 'settings', label: 'Settings', href: '/hub/settings.html', icon: 'gear' },
];

// Mobile bottom nav is intentionally a shorter set — section 4 of the
// brief is explicit about not overcrowding it.
const MOBILE_ITEMS = [
    { key: 'overview', label: 'Home', href: '/hub/', icon: 'grid' },
    { key: 'data',     label: 'Products', href: '/hub/#data', icon: 'signal' },
    { key: 'activity', label: 'Activity', href: '/hub/#activity', icon: 'clock' },
    { key: 'settings', label: 'Profile', href: '/hub/settings.html', icon: 'user' },
];

const ICONS = {
    grid:   '<path d="M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z"/>',
    signal: '<path d="M4 20V14M10 20V10M16 20V6M22 20H2" stroke-linecap="round"/>',
    bolt:   '<path d="M13 2 4 14h6l-1 8 9-12h-6l1-8Z" stroke-linejoin="round"/>',
    clock:  '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.5 2" stroke-linecap="round"/>',
    gear:   '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1 1.55V21a2 2 0 1 1-4 0v-.09A1.7 1.7 0 0 0 9 19.36a1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.7 1.7 0 0 0 4.64 15a1.7 1.7 0 0 0-1.55-1H3a2 2 0 1 1 0-4h.09A1.7 1.7 0 0 0 4.64 9a1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.7 1.7 0 0 0 9 4.64 1.7 1.7 0 0 0 10 3.09V3a2 2 0 1 1 4 0v.09A1.7 1.7 0 0 0 15 4.64a1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.7 1.7 0 0 0 19.36 9c.1.63.5 1.17 1 1.45.32.16.68.25 1.06.25H21a2 2 0 1 1 0 4h-.09a1.7 1.7 0 0 0-1.51 1Z"/>',
    user:   '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 3.6-7 8-7s8 3 8 7" stroke-linecap="round"/>',
    logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9" stroke-linecap="round" stroke-linejoin="round"/>',
};

function icon(name, cls = '') {
    return `<svg class="${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">${ICONS[name] || ''}</svg>`;
}

/**
 * Mounts the shell into #hubSidebar (desktop), #hubTopbar (mobile top
 * bar) and #hubBottomNav (mobile bottom nav) if those elements exist on
 * the page. Pass the active NAV_ITEMS key so the current section is
 * highlighted.
 */
export function mountHubShell(activeKey) {
    const user = getUser();
    const displayName = user?.full_name || user?.username || 'there';
    const initial = (user?.full_name || user?.username || 'E').trim().charAt(0).toUpperCase();

    const sidebar = document.getElementById('hubSidebar');
    if (sidebar) {
        sidebar.innerHTML = `
            <div class="hub-side-brand">
                <span class="hub-side-brand-mark">EH</span>
                <span class="hub-side-brand-text">EVOS HUB</span>
            </div>
            <nav class="hub-side-nav" aria-label="EVOS Hub">
                ${NAV_ITEMS.map(item => `
                    <a class="hub-side-link${item.key === activeKey ? ' active' : ''}" href="${item.href}">
                        ${icon(item.icon, 'hub-side-icon')}
                        <span>${item.label}</span>
                    </a>
                `).join('')}
            </nav>
            <div class="hub-side-foot">
                <div class="hub-side-user">
                    <span class="hub-avatar">${initial}</span>
                    <span class="hub-side-username">${escapeHtml(displayName)}</span>
                </div>
                <button type="button" class="hub-side-link hub-logout-btn" id="hubLogoutBtn">
                    ${icon('logout', 'hub-side-icon')}
                    <span>Log out</span>
                </button>
            </div>
        `;
    }

    const topbar = document.getElementById('hubTopbar');
    if (topbar) {
        topbar.innerHTML = `
            <span class="hub-topbar-brand">EVOS HUB</span>
            <span class="hub-avatar hub-avatar-sm">${initial}</span>
        `;
    }

    const bottomNav = document.getElementById('hubBottomNav');
    if (bottomNav) {
        bottomNav.innerHTML = MOBILE_ITEMS.map(item => `
            <a class="hub-bottom-link${item.key === activeKey ? ' active' : ''}" href="${item.href}">
                ${icon(item.icon, 'hub-bottom-icon')}
                <span>${item.label}</span>
            </a>
        `).join('');
    }

    const logoutBtn = document.getElementById('hubLogoutBtn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', () => {
            logout();
            location.href = '/xera';
        });
    }
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = String(str ?? '');
    return div.innerHTML;
}
