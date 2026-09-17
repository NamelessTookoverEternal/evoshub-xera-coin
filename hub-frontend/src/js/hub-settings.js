import { THEMES, getTheme, applyTheme, initTheme } from './theme.js';
import { requireSession, getUser } from './evos-session.js';
import { mountHubShell } from './hub-shell.js';

initTheme();

if (requireSession()) {
    mountHubShell('settings');
    renderAccentGrid();
    renderProfile();
}

function renderAccentGrid() {
    const grid = document.getElementById('accentGrid');
    if (!grid) return;
    const current = getTheme();

    const paint = () => {
        const active = getTheme();
        grid.innerHTML = THEMES.map(t => `
            <button type="button" class="hub-accent-swatch${t.id === active ? ' active' : ''}"
                    data-theme="${t.id}" role="radio" aria-checked="${t.id === active}">
                <span class="hub-accent-dot" style="background:${t.swatch}"></span>
                <span>${t.label}</span>
            </button>
        `).join('');
    };
    paint();

    grid.addEventListener('click', (e) => {
        const btn = e.target.closest('.hub-accent-swatch');
        if (!btn) return;
        applyTheme(btn.dataset.theme);
        paint();
    });
}

function renderProfile() {
    const panel = document.getElementById('profilePanel');
    if (!panel) return;
    const user = getUser();
    panel.innerHTML = `
        <div class="hub-profile-row"><span>Name</span><span>${escapeHtml(user?.full_name || '—')}</span></div>
        <div class="hub-profile-row"><span>Username</span><span>${escapeHtml(user?.username || '—')}</span></div>
        <div class="hub-profile-row"><span>Email</span><span>${escapeHtml(user?.email || '—')}</span></div>
    `;
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = String(str ?? '');
    return div.innerHTML;
}
