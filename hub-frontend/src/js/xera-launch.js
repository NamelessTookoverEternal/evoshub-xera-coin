/* XERA official launch UI: welcome notice, miner agreement, activation.
 *
 * Nothing here is an authority. The server decides whether the agreement was
 * accepted, which version is current, whether a session started and whether a
 * bonus was granted. This module only shows what the API returns and sends the
 * user's explicit actions. No acceptance, eligibility or bonus state is kept in
 * localStorage; the only in-memory flags avoid double-submits and re-prompting
 * within one page view.
 *
 * Exports:
 *   maybeShowWelcome(req)          once per page view, if the server says unseen
 *   startMiningWithOnboarding(req) resolves to the /mining/start response, or
 *                                  null if the user cancelled the agreement
 */
import '../css/xera-launch.css';

const WELCOME_COPY = {
    title: 'Welcome to the official XERA mining phase',
    paragraphs: [
        'Thank you for being part of the evolving XERA ecosystem. The official mining phase is now live.',
        'The test period has ended and all test data (balances, sessions, transactions and daily-claim progress) has been reset. Your account was kept.',
        'The first 100 eligible miners to start a mining session may receive a one-time bonus of 100 XERA. Eligibility is decided by the platform when your session starts and is not guaranteed.',
        'Your XERA balance is an in-platform balance. On-chain claiming has not launched, and no value, exchange listing or profit is promised.',
    ],
};

const CONGRATS_COPY = 'Welcome to XERA Mining! Your miner onboarding is complete. Your mining session has started successfully. Your rewards follow the current XERA mining rules. In-platform balances are not yet on-chain tokens, and future claiming will be subject to separately announced requirements.';

let welcomeChecked = false;
let flowBusy = false;

// ---------------------------------------------------------------- dom helpers
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

const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]),[tabindex]:not([tabindex="-1"])';

/** Opens a modal dialog. Returns {root, close}. Esc closes if `dismissible`. */
function openModal({ labelId, dismissible, onClose, content }) {
    const previouslyFocused = document.activeElement;
    const card = el('div', { class: 'xl-card', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': labelId, tabindex: '-1' }, content);
    const root = el('div', { class: 'xl-overlay' }, card);
    let closed = false;

    const close = (reason) => {
        if (closed) return;
        closed = true;
        document.removeEventListener('keydown', onKey, true);
        root.remove();
        document.body.classList.remove('xl-lock');
        if (previouslyFocused && previouslyFocused.focus) { try { previouslyFocused.focus(); } catch (e) { /* ignore */ } }
        if (onClose) onClose(reason);
    };
    function onKey(e) {
        if (e.key === 'Escape' && dismissible) { e.stopPropagation(); close('escape'); return; }
        if (e.key === 'Tab') {
            const items = [...card.querySelectorAll(FOCUSABLE)].filter((n) => n.offsetParent !== null);
            if (!items.length) { e.preventDefault(); return; }
            const first = items[0], last = items[items.length - 1];
            if (e.shiftKey && (document.activeElement === first || document.activeElement === card)) { e.preventDefault(); last.focus(); }
            else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
        }
    }
    document.addEventListener('keydown', onKey, true);
    document.body.classList.add('xl-lock');
    document.body.append(root);
    card.focus();
    return { root, card, close };
}

function waitForModal(build) {
    return new Promise((resolve) => build(resolve));
}

// ------------------------------------------------------------------- welcome
const WELCOME_KEY = 'xera_welcome_shown';

/** Call on sign-out so the next sign-in shows the welcome popup again. */
export function resetLaunchSession() {
    welcomeChecked = false;
    try { sessionStorage.removeItem(WELCOME_KEY); } catch (e) { /* ignore */ }
}

/** Shown once per sign-in session (per tab), not on every in-page reload.
 *  This only controls display; it is not an authority for anything. */
export async function maybeShowWelcome(req) {
    if (welcomeChecked) return;
    try { if (sessionStorage.getItem(WELCOME_KEY)) { welcomeChecked = true; return; } } catch (e) { /* ignore */ }
    welcomeChecked = true;
    let launch;
    try {
        launch = (await req('/api/xera/launch/status')).launch;
    } catch (e) {
        welcomeChecked = false; // transient failure: try again on the next load
        return;
    }
    if (!launch) return;
    try { sessionStorage.setItem(WELCOME_KEY, '1'); } catch (e) { /* ignore */ }

    const slots = Number(launch.bonus_slots_remaining);
    const slotsLine = launch.bonus_enabled && Number.isFinite(slots)
        ? `Early-miner bonus slots remaining: ${slots} of ${launch.bonus_total_slots}.` : '';

    await waitForModal((done) => {
        let marked = false;
        const markSeen = async () => {
            if (marked) return;
            marked = true;
            try {
                await req('/api/xera/launch/welcome/seen', {
                    method: 'POST', body: JSON.stringify({ notice_version: launch.welcome_notice_version }),
                });
            } catch (e) { /* shown again next time at worst; never blocks the user */ }
        };
        const { close } = openModal({
            labelId: 'xlWelcomeTitle',
            dismissible: false,
            onClose: done,
            content: [
                el('h2', { id: 'xlWelcomeTitle', class: 'xl-title', text: WELCOME_COPY.title }),
                ...WELCOME_COPY.paragraphs.map((t) => el('p', { class: 'xl-p', text: t })),
                slotsLine ? el('p', { class: 'xl-note', text: slotsLine }) : null,
                el('div', { class: 'xl-actions' }, [
                    el('button', { class: 'xl-btn xl-primary', type: 'button', text: 'Continue to XERA',
                        onclick: async (e) => { e.currentTarget.disabled = true; await markSeen(); close('continue'); } }),
                ]),
            ],
        });
    });
}

// ----------------------------------------------------------------- agreement
async function showAgreement(req) {
    let doc;
    try {
        doc = (await req('/api/xera/launch/agreement')).agreement;
    } catch (e) {
        throw new Error('Could not load the agreement. Please check your connection and try again.');
    }

    return waitForModal((done) => {
        const errBox = el('p', { class: 'xl-error', role: 'alert', 'aria-live': 'assertive' });
        const hint = el('p', { class: 'xl-hint', id: 'xlScrollHint', text: 'Scroll to the end of the agreement to continue.' });
        const scroller = el('div', { class: 'xl-scroll', tabindex: '0', role: 'region',
            'aria-label': `${doc.title}, version ${doc.version}`, 'aria-describedby': 'xlScrollHint' });
        scroller.append(el('p', { class: 'xl-ver', text: `Version ${doc.version}` }));
        for (const s of doc.sections) {
            scroller.append(el('h3', { class: 'xl-sec', text: s.title }));
            for (const p of s.paragraphs) scroller.append(el('p', { class: 'xl-p', text: p }));
        }

        const cb = el('input', { type: 'checkbox', id: 'xlAgreeCb' });
        const cbRow = el('label', { class: 'xl-check', for: 'xlAgreeCb', hidden: '' }, [
            cb, el('span', { text: 'I have read and agree to the XERA Miner Agreement and Rules.' }),
        ]);
        const agree = el('button', { class: 'xl-btn xl-primary', type: 'button', text: 'I Agree & Continue', disabled: '' });
        const cancel = el('button', { class: 'xl-btn xl-ghost', type: 'button', text: 'Not now' });

        let reachedEnd = false;
        let submitting = false;
        const sync = () => { agree.disabled = submitting || !(reachedEnd && cb.checked); };
        const checkEnd = () => {
            if (reachedEnd) return;
            if (scroller.scrollTop + scroller.clientHeight >= scroller.scrollHeight - 8) {
                reachedEnd = true;
                cbRow.hidden = false;
                hint.textContent = 'Thank you. Tick the box to confirm, then continue.';
            }
        };
        scroller.addEventListener('scroll', checkEnd, { passive: true });
        cb.addEventListener('change', sync);

        const modal = openModal({
            labelId: 'xlAgreeTitle',
            dismissible: true,
            onClose: (reason) => { if (reason !== 'accepted') done(false); },
            content: [
                el('h2', { id: 'xlAgreeTitle', class: 'xl-title', text: doc.title }),
                hint, scroller, cbRow, errBox,
                el('div', { class: 'xl-actions' }, [cancel, agree]),
            ],
        });

        cancel.addEventListener('click', () => modal.close('cancel'));
        agree.addEventListener('click', async () => {
            if (submitting || !(reachedEnd && cb.checked)) return;
            submitting = true; sync();
            errBox.textContent = '';
            agree.textContent = 'Saving…';
            try {
                await req('/api/xera/launch/agreement/accept', {
                    method: 'POST',
                    body: JSON.stringify({ agreement_version: doc.version, content_sha256: doc.sha256, confirmed: true }),
                });
                done(true);
                modal.close('accepted');
            } catch (e) {
                errBox.textContent = e.message || 'Could not record your acceptance. Please try again.';
                submitting = false; agree.textContent = 'I Agree & Continue'; sync();
            }
        });

        // Short text that already fits on screen: nothing to scroll.
        requestAnimationFrame(checkEnd);
    });
}

// --------------------------------------------------------------- congrats
function showCongrats(m) {
    const bonus = m.bonus;
    const granted = bonus && bonus.status === 'GRANTED' && Number(bonus.amount) > 0;
    return waitForModal((done) => {
        const { close } = openModal({
            labelId: 'xlDoneTitle', dismissible: false, onClose: done,
            content: [
                el('h2', { id: 'xlDoneTitle', class: 'xl-title', text: 'Mining started' }),
                el('p', { class: 'xl-p', text: CONGRATS_COPY }),
                m.estimated_reward != null ? el('p', { class: 'xl-note', text: `Session reward: ${Number(m.estimated_reward).toLocaleString('en-US')} XERA${m.expires_at ? ` · ends ${new Date(m.expires_at).toLocaleString()}` : ''}` }) : null,
                granted ? el('p', { class: 'xl-bonus', text: `Early-miner bonus credited: ${Number(bonus.amount).toLocaleString('en-US')} XERA` }) : null,
                el('div', { class: 'xl-actions' }, [
                    el('button', { class: 'xl-btn xl-primary', type: 'button', text: 'Continue', onclick: () => close('continue') }),
                ]),
            ],
        });
    });
}

// -------------------------------------------------------------------- flow
/**
 * Start mining, asking for the agreement first when the server says it is
 * required. Success is only reported when /mining/start itself succeeds.
 * The congratulations popup is shown after every session that really started.
 */
export async function startMiningWithOnboarding(req) {
    if (flowBusy) return null;
    flowBusy = true;
    try {
        let acceptedNow = false;

        // Ask the server first so a user who still has to accept is not sent
        // through a doomed start request.
        let accepted = true;
        try {
            const st = (await req('/api/xera/launch/status')).launch;
            accepted = !!st.agreement_accepted;
            if (st.agreement_consistent === false) {
                throw Object.assign(new Error('The agreement is being updated. Please try again shortly.'), { code: 'agreement_unavailable' });
            }
        } catch (e) {
            if (e.code === 'agreement_unavailable') throw e;
            // Status unavailable: fall through; the start call enforces the rule anyway.
        }

        if (!accepted) {
            if (!(await showAgreement(req))) return null;
            acceptedNow = true;
        }

        let result;
        try {
            result = await req('/api/xera/mining/start', { method: 'POST', body: '{}' });
        } catch (e) {
            // Version changed between status and start, or status was unavailable.
            if (e.code === 'agreement_required' && !acceptedNow) {
                if (!(await showAgreement(req))) return null;
                acceptedNow = true;
                result = await req('/api/xera/mining/start', { method: 'POST', body: '{}' });
            } else {
                throw e;
            }
        }

        if (!result || !result.mining || !result.mining.id) {
            throw new Error('Mining could not be started. Please try again.');
        }
        await showCongrats(result.mining);
        return result;
    } finally {
        flowBusy = false;
    }
}
