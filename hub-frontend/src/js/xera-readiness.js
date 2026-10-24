// XERA dashboard cards: Notifications, KYC verification status, first-transfer processing fee,
// plus the "complete these steps" dialog shown when the server refuses a first transfer.
//
// Everything shown here is what GET /api/xera/readiness returned. The browser never decides
// that someone is verified or has paid: it only displays the server's answer, and submits
// KYC *details* for review (it cannot send a status). The Mining timer card is the existing
// one in xera.js; this module only reads its session to describe it in Notifications.

const $ = (id) => document.getElementById(id);

const KYC_VIEW = {
    UNVERIFIED:    { tone: 'warn',    label: 'Unverified',            hint: 'Please verify your identity' },
    PENDING:       { tone: 'neutral', label: 'Verification pending',  hint: 'Your details are being reviewed' },
    VERIFIED:      { tone: 'ok',      label: 'Verified',              hint: 'Your identity is verified' },
    FAILED:        { tone: 'bad',     label: 'Verification failed',   hint: 'Tap to see why and try again' },
    INFO_REQUIRED: { tone: 'warn',    label: 'More information needed', hint: 'Tap to update your details' },
};
const FEE_VIEW = {
    UNPAID:  { tone: 'neutral', label: 'Unpaid' },
    PENDING: { tone: 'neutral', label: 'Payment pending' },
    PAID:    { tone: 'ok',      label: 'Paid' },
    FAILED:  { tone: 'bad',     label: 'Payment failed' },
};
const REQ_LABEL = {
    kyc_not_verified: 'Verify your identity',
    fee_not_paid: 'Pay the one-time processing fee',
};

let ctx = null;          // { req, getMining, fmtDateTime }
let state = null;        // last server response
let localTimer = null;
let wired = false;

function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
}
function open(id) { const m = $(id); if (m) m.hidden = false; }
function close(id) { const m = $(id); if (m) m.hidden = true; }

function fmtMoney(minor, currency) {
    try {
        return new Intl.NumberFormat('en-US', { style: 'currency', currency }).format((minor || 0) / 100);
    } catch (_e) { return `${((minor || 0) / 100).toFixed(2)} ${currency}`; }
}

// ---------------------------------------------------------------- cards

function renderKyc() {
    const k = state.kyc;
    const v = KYC_VIEW[k.status] || KYC_VIEW.UNVERIFIED;
    const card = $('kycCard');
    card.dataset.tone = v.tone;
    $('kycIcon').textContent = v.tone === 'ok' ? '✓' : v.tone === 'bad' ? '✕' : v.tone === 'warn' ? '!' : '…';
    $('kycLabel').textContent = v.label;
    $('kycHint').textContent = k.unavailable ? 'Verification status is temporarily unavailable.' : v.hint;
}

function renderFee() {
    const f = state.fee;
    const v = FEE_VIEW[f.status] || FEE_VIEW.UNPAID;
    const card = $('feeCard');
    card.dataset.tone = v.tone;
    $('feeAmount').textContent = fmtMoney(f.amount_minor, f.currency);
    $('feeLabel').textContent = v.label;
    $('feeHint').textContent = f.status === 'PAID'
        ? 'Your one-time processing fee is confirmed.'
        : f.collection_enabled
            ? 'Required once, before your first eligible transfer.'
            : 'Required once, before your first transfer. Payment is not open yet.';
}

function notificationItems() {
    // Persisted server notifications first, then live status lines derived from server-confirmed state.
    const items = [];
    (state.notifications || []).forEach((n) => items.push({ title: n.title, body: n.body, when: n.created_at, tone: n.kind === 'kyc_verified' ? 'ok' : n.kind === 'kyc_failed' ? 'bad' : 'neutral' }));

    const mining = ctx && ctx.getMining ? ctx.getMining() : null;
    if (mining && mining.expires_at) {
        const ended = new Date(mining.expires_at).getTime() <= Date.now();
        items.push(ended
            ? { title: 'Mining session complete', body: 'Your reward is ready to claim.', tone: 'ok' }
            : { title: 'Mining session in progress', body: `Ends ${ctx.fmtDateTime(new Date(mining.expires_at))}.`, tone: 'neutral' });
    }
    const k = state.kyc.status;
    if (k === 'PENDING') items.push({ title: 'Verification pending', body: 'We are reviewing your details. You can keep mining.', tone: 'neutral' });
    if (k === 'INFO_REQUIRED') items.push({ title: 'More information needed', body: state.kyc.note || 'Update your details to continue verification.', tone: 'warn' });
    if (k === 'FAILED') items.push({ title: 'Verification unsuccessful', body: state.kyc.note || 'You can submit your details again.', tone: 'bad' });
    if (state.fee.status === 'FAILED') items.push({ title: 'Processing fee payment failed', body: 'No fee was recorded.', tone: 'bad' });
    if ((state.missing || []).length) {
        items.push({ title: 'Needed before your first transfer', body: state.missing.map((m) => REQ_LABEL[m] || m).join(' · ') + '. You can keep mining.', tone: 'warn' });
    }
    return items;
}

function renderNotifications() {
    const list = $('notifList');
    list.replaceChildren();
    const items = notificationItems();
    if (!items.length) { list.appendChild(el('p', 'rd-empty', 'No new notifications.')); if ($('notifBadge')) $('notifBadge').hidden = true; if ($('notifLabel')) $('notifLabel').textContent = 'All clear'; return; }
    const n = items.length;
    const badge = $('notifBadge'), label = $('notifLabel');
    if (badge) { badge.textContent = n > 9 ? '9+' : String(n); badge.hidden = n === 0; }
    if (label) label.textContent = n === 0 ? 'All clear' : `${n} update${n === 1 ? '' : 's'}`;
    items.slice(0, 50).forEach((it) => {
        const row = el('div', 'rd-notif');
        row.dataset.tone = it.tone || 'neutral';
        row.appendChild(el('span', 'rd-notif-dot'));
        const text = el('div', 'rd-notif-text');
        text.appendChild(el('b', null, it.title));
        if (it.body) text.appendChild(el('span', null, it.body));
        row.appendChild(text);
        list.appendChild(row);
    });
}

function renderAll() {
    if (!state) return;
    $('readinessCards').hidden = false;
    renderKyc(); renderFee(); renderNotifications();
}

// ---------------------------------------------------------------- KYC modal

function openKyc() {
    const k = state.kyc;
    const form = $('kycForm'), info = $('kycInfo'), err = $('kycError');
    err.textContent = '';
    const canSubmit = ['UNVERIFIED', 'FAILED', 'INFO_REQUIRED'].includes(k.status) && !k.unavailable;
    form.hidden = !canSubmit;
    info.hidden = canSubmit;
    $('kycNote').hidden = !k.note;
    $('kycNote').textContent = k.note ? `Reviewer note: ${k.note}` : '';
    if (!canSubmit) {
        info.textContent = k.unavailable ? 'Verification is temporarily unavailable. Please try again later.'
            : k.status === 'VERIFIED' ? 'Your identity is verified. Nothing more to do here.'
            : 'Your details are with our team for review. You can keep mining while you wait.';
    }
    open('kycModal');
}

async function submitKyc(ev) {
    ev.preventDefault();
    const btn = $('kycSubmit'), err = $('kycError');
    err.textContent = '';
    btn.disabled = true;
    try {
        // Details only. There is deliberately no status field in this request.
        await ctx.req('/api/xera/kyc/submit', {
            method: 'POST',
            body: JSON.stringify({
                legal_name: $('kycName').value, country: $('kycCountry').value,
                id_type: $('kycIdType').value, id_number: $('kycIdNumber').value,
            }),
        });
        $('kycIdNumber').value = '';
        await refresh();
        close('kycModal');
    } catch (e) {
        err.textContent = e.message || 'Could not submit your details. Please try again.';
    } finally { btn.disabled = false; }
}

// ---------------------------------------------------------------- fee modal

function openFee() {
    const f = state.fee;
    $('feeModalTitle').textContent = `First-Time Transfer Processing Fee — ${fmtMoney(f.amount_minor, f.currency)}`;
    const status = $('feeModalStatus');
    status.textContent = `Status: ${(FEE_VIEW[f.status] || FEE_VIEW.UNPAID).label}`;
    const pay = $('feePay');
    // No payment route exists yet, so this button can never start a charge.
    pay.disabled = true;
    pay.textContent = f.status === 'PAID' ? 'Already paid' : 'Payment not open yet';
    $('feeRefund').textContent = f.collection_enabled
        ? 'Refund policy: shown here before any payment is taken.'
        : 'Refund policy: will be shown here, and must be accepted, before payment opens. Nothing is charged today.';
    open('feeModal');
}

// ---------------------------------------------------------------- requirements dialog

export function showRequirements(missing) {
    const list = $('reqList');
    list.replaceChildren();
    const m = Array.isArray(missing) && missing.length ? missing : ['kyc_not_verified', 'fee_not_paid'];
    m.forEach((code) => {
        const li = el('li');
        const b = el('button', 'btn btn-sm btn-ghost', REQ_LABEL[code] || code);
        b.type = 'button';
        b.onclick = () => { close('reqModal'); if (!state) return; (code === 'kyc_not_verified' ? openKyc : openFee)(); };
        li.appendChild(b);
        list.appendChild(li);
    });
    open('reqModal');
}

// ---------------------------------------------------------------- lifecycle

export async function refresh() {
    try {
        const d = await ctx.req('/api/xera/readiness');
        state = { kyc: d.kyc, fee: d.fee, missing: d.missing || [], notifications: d.notifications || [] };
        renderAll();
    } catch (_e) {
        // Keep whatever was last confirmed; never invent a status.
        if (!state) $('readinessCards').hidden = true;
    }
}

function wire() {
    if (wired) return;
    wired = true;
    $('kycCard').addEventListener('click', () => state && openKyc());
    $('feeCard').addEventListener('click', () => state && openFee());
    $('kycForm').addEventListener('submit', submitKyc);
    [['kycLater', 'kycModal'], ['kycClose', 'kycModal'], ['feeCancel', 'feeModal'], ['feeClose', 'feeModal'], ['reqClose', 'reqModal'], ['reqLater', 'reqModal']]
        .forEach(([btn, modal]) => { const b = $(btn); if (b) b.addEventListener('click', () => close(modal)); });
    ['kycModal', 'feeModal', 'reqModal'].forEach((id) => $(id).addEventListener('click', (e) => { if (e.target.id === id) close(id); }));
}

export function initReadiness(c) {
    if (!$('readinessCards')) return;
    ctx = c;
    wire();
    refresh();
    clearInterval(localTimer);
    localTimer = setInterval(() => { if (state) renderNotifications(); }, 30000);
}

export function resetReadiness() {
    state = null;
    clearInterval(localTimer);
    const c = $('readinessCards');
    if (c) c.hidden = true;
}

window.XeraReadiness = { showRequirements, refresh };
