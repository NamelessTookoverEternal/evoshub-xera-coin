import { initTheme } from './theme.js';
import { requireSession, getUser, api } from './evos-session.js';
import { mountHubShell } from './hub-shell.js';

initTheme();

if (requireSession()) {
    const user = getUser();
    const nameEl = document.getElementById('welcomeName');
    if (nameEl) nameEl.textContent = user?.full_name || user?.username || 'there';

    mountHubShell('overview');
    loadXeraCard();
    loadActivity();
    loadEcosystemLinks();
}

// ---------------------------------------------------------------
// XERA card — the one product with a real, live wallet today, so
// its card shows an actual balance instead of a generic blurb.
// ---------------------------------------------------------------
async function loadXeraCard() {
    const balanceEl = document.getElementById('xeraCardBalance');
    if (!balanceEl) return;
    const settle = (text) => {
        balanceEl.textContent = text;
        balanceEl.classList.remove('hub-skel');
        balanceEl.style.width = 'auto';
        balanceEl.style.height = 'auto';
    };
    try {
        const res = await api('/api/xera/wallet');
        settle(res.status === 'ok' ? `${formatXera(res.balance)} XERA` : 'View wallet');
    } catch (e) {
        settle('View wallet');
    }
}

function formatXera(n) {
    const num = Number(n) || 0;
    return num.toLocaleString(undefined, { maximumFractionDigits: 3, minimumFractionDigits: 0 });
}

// ---------------------------------------------------------------
// Quick activity — real XERA transactions only (mining/claims/etc).
// Section 7 of the brief: never fabricate activity.
// ---------------------------------------------------------------
const ACTIVITY_META = {
    mining_reward: { label: 'Mining reward', icon: 'bolt' },
    daily_claim:   { label: 'Daily claim', icon: 'gift' },
    claim:         { label: 'XERA claimed', icon: 'bolt' },
    adjustment:    { label: 'Balance adjustment', icon: 'gear' },
};

async function loadActivity() {
    const list = document.getElementById('activityList');
    if (!list) return;
    try {
        const res = await api('/api/xera/transactions?limit=6');
        const txs = res.status === 'ok' ? (res.transactions || []) : [];
        if (!txs.length) {
            list.innerHTML = `<p class="hub-empty">No activity yet — start a XERA mining session to see it here.</p>`;
            return;
        }
        list.innerHTML = txs.map(renderActivityRow).join('');
    } catch (e) {
        list.innerHTML = `<p class="hub-empty">Couldn't load activity right now.</p>`;
    }
}

function renderActivityRow(tx) {
    const meta = ACTIVITY_META[tx.type] || { label: tx.type || 'Transaction', icon: 'clock' };
    const amount = Number(tx.amount) || 0;
    const sign = amount > 0 ? '+' : '';
    const when = tx.created_at ? timeAgo(tx.created_at) : '';
    return `
        <div class="hub-activity-row">
            <div class="hub-activity-left">
                <span class="hub-activity-icon">${iconSvg(meta.icon)}</span>
                <div>
                    <p class="hub-activity-title">${meta.label}</p>
                    <p class="hub-activity-time">${when}</p>
                </div>
            </div>
            <span class="hub-activity-amount${amount > 0 ? ' positive' : ''}">${sign}${formatXera(amount)} XERA</span>
        </div>
    `;
}

function timeAgo(iso) {
    const diffMs = Date.now() - new Date(iso).getTime();
    const mins = Math.floor(diffMs / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    const days = Math.floor(hrs / 24);
    return `${days}d ago`;
}

function iconSvg(name) {
    const paths = {
        bolt:  '<path d="M13 2 4 14h6l-1 8 9-12h-6l1-8Z" stroke-linejoin="round"/>',
        gift:  '<rect x="3" y="9" width="18" height="12" rx="1.5"/><path d="M3 9h18v0M12 9v12M12 9c-2-4-7-3-6-.5S9 9 12 9Zm0 0c2-4 7-3 6-.5S15 9 12 9Z"/>',
        gear:  '<circle cx="12" cy="12" r="3"/>',
        clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.5 2" stroke-linecap="round"/>',
    };
    return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">${paths[name] || paths.clock}</svg>`;
}

// ---------------------------------------------------------------
// Other ecosystem products — pulled from the admin-curated
// xera_ecosystem_links table (already live, used by ecosystem.html)
// rather than hardcoding a second copy of the same list.
// ---------------------------------------------------------------
async function loadEcosystemLinks() {
    const grid = document.getElementById('ecoLinksSlot');
    if (!grid) return;
    try {
        const res = await fetch('/api/xera/ecosystem').then(r => r.json());
        const links = res.status === 'ok' ? (res.links || []) : [];
        if (!links.length) {
            grid.innerHTML = '';
            return;
        }
        grid.innerHTML = links.map(link => `
            <a class="hub-product-card" href="${escapeAttr(link.url)}" target="_blank" rel="noopener">
                <span class="hub-product-icon">
                    ${link.image_url
                        ? `<img src="${escapeAttr(link.image_url)}" alt="" style="width:100%;height:100%;object-fit:cover;border-radius:12px"/>`
                        : iconSvg('bolt')}
                </span>
                <div>
                    <p class="hub-product-name">${escapeHtml(link.name)}</p>
                    <p class="hub-product-desc">Part of the EVOXERA ecosystem</p>
                </div>
                <div class="hub-product-foot">
                    <span class="hub-status-pill is-live"><span class="dot"></span>Live</span>
                    <span class="hub-product-open">Open ↗</span>
                </div>
            </a>
        `).join('');
    } catch (e) {
        grid.innerHTML = '';
    }
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = String(str ?? '');
    return div.innerHTML;
}
function escapeAttr(str) {
    return escapeHtml(str).replace(/"/g, '&quot;');
}
