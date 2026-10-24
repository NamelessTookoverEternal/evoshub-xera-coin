/* XERA dashboard: notifications, KYC status and first-transfer fee cards, plus the
 * "complete these steps first" modals.
 *
 * Nothing here is an authority. Every status shown comes from GET /api/xera/readiness and
 * /api/xera/notifications; the server decides what is verified or paid. This module only
 * shows those answers and sends the user's explicit actions (submit details, start checkout).
 * It never stores a status in localStorage and never marks anything done on its own.
 *
 * Users can always close the modals and keep mining: nothing here touches the mining flow.
 */
import '../css/xera-launch.css';
import '../css/xera-readiness.css';

let reqFn = null;
let getMining = () => null;
let overview = null;
let notifications = [];
let busy = false;
let listenerAdded = false;

const $ = (id) => document.getElementById(id);

function el(tag, attrs = {}, children = []) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
        if (k === 'class') n.className = v;
        else if (k === 'text') n.textContent = v;
        else if (k.startsWith('on')) n.addEventListener(k.slice(2), v);
        else n.setAttribute(k, v);
    }
    for (const c of [].concat(children)) if (c) n.append(c);
    return n;
}

// replaceChildren(null) would insert the text "null": drop empty children first.
const setChildren = (host, ...nodes) => host.replaceChildren(...nodes.filter(Boolean));

const fmtDate = (iso) => {
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? '' : d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
};

// ------------------------------------------------------------------ labels
const KYC_VIEW = {
    UNVERIFIED: { tone: 'warn', icon: '!', label: 'Unverified', line: 'Please verify your identity before your first transfer.' },
    PENDING: { tone: 'neutral', icon: '…', label: 'Verification pending', line: 'Your details are waiting for review.' },
    VERIFIED: { tone: 'ok', icon: '✓', label: 'Verified', line: 'Your identity is verified.' },
    FAILED: { tone: 'bad', icon: '✕', label: 'Verification failed', line: 'Your verification was not approved. You can try again.' },
    MORE_INFO: { tone: 'warn', icon: '!', label: 'More information needed', line: 'We need a little more information from you.' },
};
const FEE_VIEW = {
    UNPAID: { tone: 'warn', icon: '!', label: 'Unpaid' },
    PENDING: { tone: 'neutral', icon: '…', label: 'Payment pending' },
    PAID: { tone: 'ok', icon: '✓', label: 'Paid' },
    FAILED: { tone: 'bad', icon: '✕', label: 'Payment failed' },
};

function feeAmountText(fee) {
    return fee && fee.amount && fee.currency ? `${fee.currency === 'USD' ? '$' : ''}${fee.amount}${fee.currency === 'USD' ? ' USD' : ' ' + fee.currency}` : 'a one-time fee';
}

// ------------------------------------------------------------------ modal
function openModal({ labelId, content, onClose }) {
    const previouslyFocused = document.activeElement;
    const card = el('div', { class: 'xl-card', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': labelId, tabindex: '-1' }, content);
    const root = el('div', { class: 'xl-overlay' }, card);
    let closed = false;
    const close = () => {
        if (closed) return;
        closed = true;
        document.removeEventListener('keydown', onKey, true);
        root.remove();
        document.body.classList.remove('xl-lock');
        if (previouslyFocused && previouslyFocused.focus) { try { previouslyFocused.focus(); } catch (e) { /* ignore */ } }
        if (onClose) onClose();
    };
    const onKey = (e) => { if (e.key === 'Escape') { e.stopPropagation(); close(); } };
    root.addEventListener('mousedown', (e) => { if (e.target === root) close(); });
    document.addEventListener('keydown', onKey, true);
    document.body.classList.add('xl-lock');
    document.body.append(root);
    card.focus();
    return { card, close };
}

function closeAnyReadinessModal() {
    document.querySelectorAll('.xl-overlay[data-xr]').forEach((n) => n.remove());
    document.body.classList.remove('xl-lock');
}

function modal(labelId, build) {
    closeAnyReadinessModal();
    const m = openModal({ labelId, content: [] });
    m.card.parentElement.setAttribute('data-xr', '1');
    m.card.append(...[].concat(build(m.close)).filter(Boolean));
    return m;
}

// ------------------------------------------------------------------ KYC modal
const ID_TYPES = ['Ghana Card', 'Passport', "Driver's licence", "Voter's ID", 'Other government ID'];

function openKycModal() {
    const kyc = overview?.kyc || { status: 'UNVERIFIED' };
    const view = KYC_VIEW[kyc.status] || KYC_VIEW.UNVERIFIED;

    if (kyc.status === 'VERIFIED' || kyc.status === 'PENDING') {
        modal('xrKycTitle', (close) => [
            el('h2', { id: 'xrKycTitle', class: 'xl-title', text: view.label }),
            el('p', { class: 'xl-lead', text: kyc.status === 'VERIFIED'
                ? 'Your identity is verified. Wallet verification and the other transfer requirements still apply.'
                : 'Your details were received and are waiting for review. You can keep mining while you wait.' }),
            el('div', { class: 'xl-actions xl-actions-full' }, [el('button', { class: 'xl-btn xl-primary', type: 'button', text: 'Close', onclick: close })]),
        ]);
        return;
    }

    const showForm = (close, card) => {
        const err = el('p', { class: 'xl-error', role: 'alert', 'aria-live': 'assertive' });
        const name = el('input', { class: 'xr-input', type: 'text', maxlength: '120', autocomplete: 'name', placeholder: 'Full legal name' });
        const country = el('input', { class: 'xr-input', type: 'text', maxlength: '60', autocomplete: 'country-name', placeholder: 'Country' });
        const type = el('select', { class: 'xr-input' }, ID_TYPES.map((t) => el('option', { value: t, text: t })));
        const last4 = el('input', { class: 'xr-input', type: 'text', maxlength: '40', autocomplete: 'off', inputmode: 'text', placeholder: 'Last 4 characters of your ID number' });
        const submit = el('button', { class: 'xl-btn xl-primary', type: 'button', text: 'Submit for review' });
        submit.addEventListener('click', async () => {
            err.textContent = '';
            submit.disabled = true;
            try {
                const res = await reqFn('/api/xera/kyc/submit', { method: 'POST', body: JSON.stringify({
                    legal_name: name.value, country: country.value, id_type: type.value, id_last4: last4.value }) });
                overview = { ...(overview || {}), kyc: res.kyc };
                await refresh();
                close();
            } catch (e) {
                err.textContent = e.message || 'Could not submit. Please try again.';
                submit.disabled = false;
            }
        });
        card.replaceChildren(
            el('h2', { id: 'xrKycTitle', class: 'xl-title', text: 'Verify Your Identity' }),
            el('p', { class: 'xl-lead', text: 'Your details are reviewed by our team. Enter only the last 4 characters of your ID number, and never post a photo of your ID here.' }),
            el('label', { class: 'xr-label', text: 'Full legal name' }, name),
            el('label', { class: 'xr-label', text: 'Country' }, country),
            el('label', { class: 'xr-label', text: 'ID type' }, type),
            el('label', { class: 'xr-label', text: 'ID number (last 4 characters only)' }, last4),
            err,
            el('div', { class: 'xl-actions' }, [
                el('button', { class: 'xl-btn xl-ghost', type: 'button', text: 'Maybe Later', onclick: close }), submit]),
        );
        name.focus();
    };

    modal('xrKycTitle', (close) => {
        const intro = [
            el('h2', { id: 'xrKycTitle', class: 'xl-title', text: 'Verify Your Identity' }),
            kyc.note ? el('p', { class: 'xr-note', text: `Reviewer note: ${kyc.note}` }) : null,
            el('p', { class: 'xl-lead', text: 'Identity verification is required before your first eligible XERA transfer. You can continue mining while verification is pending, but verification must be completed before transferring.' }),
        ];
        const go = el('button', { class: 'xl-btn xl-primary', type: 'button', text: 'Verify My Identity' });
        const later = el('button', { class: 'xl-btn xl-ghost', type: 'button', text: 'Maybe Later', onclick: close });
        go.addEventListener('click', () => showForm(close, go.closest('.xl-card')));
        return [...intro, el('div', { class: 'xl-actions' }, [later, go])];
    });
}

// ------------------------------------------------------------------ fee modal
function openFeeModal() {
    const fee = overview?.fee;
    if (!fee) return;
    if (fee.paid) {
        modal('xrFeeTitle', (close) => [
            el('h2', { id: 'xrFeeTitle', class: 'xl-title', text: 'Processing fee paid' }),
            el('p', { class: 'xl-lead', text: 'Your one-time processing fee was confirmed. Wallet verification and all other requirements still apply, and payment does not guarantee a successful transfer.' }),
            el('div', { class: 'xl-actions xl-actions-full' }, [el('button', { class: 'xl-btn xl-primary', type: 'button', text: 'Close', onclick: close })]),
        ]);
        return;
    }
    const open = fee.collection_enabled;
    modal('xrFeeTitle', (close) => {
        const err = el('p', { class: 'xl-error', role: 'alert', 'aria-live': 'assertive' });
        const pay = el('button', { class: 'xl-btn xl-primary', type: 'button', text: 'Continue to Payment' });
        pay.disabled = !open;
        pay.addEventListener('click', async () => {
            err.textContent = '';
            pay.disabled = true;
            try {
                const res = await reqFn('/api/xera/fee/checkout', { method: 'POST' });
                location.assign(res.authorization_url);          // Paystack's hosted page; the result is verified server-side afterwards
            } catch (e) {
                err.textContent = e.message || 'Could not start the payment. Nothing was charged.';
                pay.disabled = false;
            }
        });
        return [
            el('h2', { id: 'xrFeeTitle', class: 'xl-title', text: `First-Time Transfer Processing Fee — ${feeAmountText(fee)}` }),
            el('p', { class: 'xl-lead', text: 'A one-time processing fee is required before your first eligible XERA transfer. This fee is separate from the price of XERA tokens and blockchain network gas fees. Payment does not guarantee a successful transfer.' }),
            fee.refund_policy ? el('p', { class: 'xr-policy' }, [el('b', { text: 'Refund policy: ' }), document.createTextNode(fee.refund_policy)]) : null,
            !open ? el('p', { class: 'xr-note', text: 'Payment is not open yet. You will see a notification here when it is.' }) : null,
            err,
            el('div', { class: 'xl-actions' }, [el('button', { class: 'xl-btn xl-ghost', type: 'button', text: 'Cancel', onclick: close }), pay]),
        ];
    });
}

// ------------------------------------------------------------------ "complete these first" modal
export function showRequirementsModal(missing) {
    const need = Array.isArray(missing) && missing.length ? missing : (overview?.missing || []);
    modal('xrReqTitle', (close) => [
        el('h2', { id: 'xrReqTitle', class: 'xl-title', text: 'Complete these steps before your first transfer' }),
        el('p', { class: 'xl-lead', text: 'You can close this and keep mining. Nothing you have mined is affected.' }),
        el('ul', { class: 'xr-req' }, [
            need.includes('kyc') ? el('li', {}, [el('span', { text: 'Verify your identity' }),
                el('button', { class: 'xl-btn xl-primary xr-sm', type: 'button', text: 'Verify My Identity', onclick: () => openKycModal() })]) : null,
            need.includes('fee') ? el('li', {}, [el('span', { text: 'Pay the one-time processing fee' }),
                el('button', { class: 'xl-btn xl-primary xr-sm', type: 'button', text: 'View fee', onclick: () => openFeeModal() })]) : null,
        ]),
        el('div', { class: 'xl-actions xl-actions-full' }, [el('button', { class: 'xl-btn xl-ghost', type: 'button', text: 'Keep mining', onclick: close })]),
    ]);
}

// ------------------------------------------------------------------ cards
function pill(view) {
    return el('span', { class: `xr-pill xr-${view.tone}` }, [el('span', { class: 'xr-ico', 'aria-hidden': 'true', text: view.icon }), document.createTextNode(view.label)]);
}

function renderKycCard() {
    const host = $('kycCard');
    if (!host || !overview) return;
    const kyc = overview.kyc;
    const view = KYC_VIEW[kyc.status] || KYC_VIEW.UNVERIFIED;
    setChildren(host,
        el('div', { class: 'mini-card-head' }, [el('span', { class: 'mini-card-title', text: 'Identity verification' }), pill(view)]),
        el('p', { class: 'mini-caption', text: kyc.status === 'UNVERIFIED' ? 'Unverified — Please verify.' : view.line }),
        kyc.note ? el('p', { class: 'xr-note', text: `Note: ${kyc.note}` }) : null,
        el('p', { class: 'xr-fine', text: 'You can keep mining without it. It is needed before your first transfer.' }),
    );
    host.setAttribute('data-tone', view.tone);
    host.setAttribute('aria-label', `Identity verification: ${view.label}. Open.`);
}

function renderFeeCard() {
    const host = $('feeCard');
    if (!host || !overview) return;
    const fee = overview.fee;
    const view = FEE_VIEW[fee.status] || FEE_VIEW.UNPAID;
    setChildren(host,
        el('div', { class: 'mini-card-head' }, [el('span', { class: 'mini-card-title', text: 'First-transfer fee' }), pill(view)]),
        el('p', { class: 'mini-caption', text: `${feeAmountText(fee)} — one-time processing fee` }),
        el('p', { class: 'xr-fine', text: 'Not the price of XERA and not blockchain gas. Payment does not guarantee a transfer. Wallet verification and all other requirements still apply.' }),
        !fee.paid && !fee.collection_enabled ? el('p', { class: 'xr-note', text: 'Payment is not open yet.' }) : null,
    );
    host.setAttribute('data-tone', view.tone);
    host.setAttribute('aria-label', `First-transfer processing fee: ${view.label}. Open.`);
}

function liveMiningItems() {
    const m = getMining();
    if (!m) return [];
    const end = new Date(m.expires_at).getTime();
    if (Number.isNaN(end)) return [];
    return end > Date.now()
        ? [{ title: 'Mining session in progress', body: `Ends ${fmtDate(m.expires_at)}.`, live: true }]
        : [{ title: 'Mining session complete', body: 'Your reward is ready to claim.', live: true }];
}

function requirementItems() {
    if (!overview) return [];
    const items = [];
    if (!overview.kyc.verified) items.push({ title: 'Identity verification needed', body: 'Required before your first transfer. Mining is not affected.', live: true });
    if (!overview.fee.paid) items.push({ title: 'Processing fee needed', body: 'A one-time fee is required before your first transfer.', live: true });
    return items;
}

export function renderNotificationsCard() {
    const host = $('notifCard');
    if (!host) return;
    const items = [...liveMiningItems(), ...requirementItems(), ...notifications.map((n) => ({ title: n.title, body: n.body, at: n.created_at, unread: !n.read }))];
    const unread = notifications.filter((n) => !n.read).length;
    const head = el('div', { class: 'mini-card-head' }, [
        el('span', { class: 'mini-card-title', text: 'Notifications' }),
        unread ? el('span', { class: 'xr-badge', text: String(unread), 'aria-label': `${unread} unread` }) : null,
    ]);
    const list = items.length
        ? el('ul', { class: 'xr-notifs' }, items.slice(0, 6).map((n) => el('li', { class: n.unread ? 'unread' : '' }, [
            el('b', { text: n.title }), el('span', { text: n.body }), n.at ? el('time', { text: fmtDate(n.at) }) : null])))
        : el('p', { class: 'mini-caption', text: 'No new updates.' });
    setChildren(host, head, list);
    if (unread) {
        // Marking read is a server write for this user's own rows; failure is harmless.
        reqFn('/api/xera/notifications/read', { method: 'POST' }).catch(() => {});
        notifications = notifications.map((n) => ({ ...n, read: true }));
    }
}

async function refresh() {
    try {
        const [o, n] = await Promise.all([reqFn('/api/xera/readiness'), reqFn('/api/xera/notifications')]);
        overview = o;
        notifications = n.notifications || [];
    } catch (e) {
        return;     // leave the cards hidden / as they were: never show a guessed status
    }
    const wrap = $('readinessCards');
    if (wrap) wrap.hidden = false;
    renderKycCard();
    renderFeeCard();
    renderNotificationsCard();
}

// ------------------------------------------------------------------ public API
async function handleFeeReturn() {
    const p = new URLSearchParams(location.search);
    const ref = p.get('reference') || p.get('trxref') || '';
    if (!ref.startsWith('xera-fee-')) return;
    history.replaceState({}, '', location.pathname + location.hash);
    // The URL only says WHICH payment to check; the server asks Paystack for the real result.
    try { await reqFn(`/api/xera/fee/verify?reference=${encodeURIComponent(ref)}`); } catch (e) { /* the webhook may still confirm it */ }
}

/** Call after sign-in. `getMiningState` returns the current mining session object (or null). */
export async function initReadiness(req, getMiningState) {
    reqFn = req;
    if (getMiningState) getMining = getMiningState;
    if (!listenerAdded) {
        listenerAdded = true;
        window.addEventListener('xera:transfer-requirements', (e) => showRequirementsModal(e.detail && e.detail.missing));
        const open = (id, fn) => { const n = $(id); if (n) { n.addEventListener('click', fn); n.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fn(); } }); } };
        open('kycCard', openKycModal);
        open('feeCard', openFeeModal);
        setInterval(() => { if (overview) renderNotificationsCard(); }, 30000);   // live session wording only
    }
    await handleFeeReturn();
    await refresh();
}

/** Hide everything on sign-out so nothing from the previous account lingers. */
export function resetReadiness() {
    overview = null;
    notifications = [];
    const wrap = $('readinessCards');
    if (wrap) wrap.hidden = true;
}
