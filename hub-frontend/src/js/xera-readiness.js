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
    if (k === 'PENDING') items.push({ title: 'Verification pending', body: state.kyc.method === 'PROVIDER' && state.kyc.provider_status === 'STARTED' ? 'Finish the ID check to continue. You can keep mining.' : 'We are reviewing your details. You can keep mining.', tone: 'neutral' });
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
    if (!items.length) { list.appendChild(el('p', 'rd-empty', 'No new notifications.')); return; }
    items.slice(0, 6).forEach((it) => {
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

// ISO-2 codes shown in the country picker. The SERVER decides which provider handles the country.
const COUNTRY_CODES = ('AF AL DZ AD AO AG AR AM AU AT AZ BS BH BD BB BY BE BZ BJ BT BO BA BW BR BN BG BF BI KH CM CA CV CF TD CL CN CO KM CG CD CR CI HR CU CY CZ DK DJ DM DO EC EG SV GQ ER EE SZ ET FJ FI FR GA GM GE DE GH GR GD GT GN GW GY HT HN HK HU IS IN ID IR IQ IE IL IT JM JP JO KZ KE KI KW KG LA LV LB LS LR LY LI LT LU MO MG MW MY MV ML MT MH MR MU MX FM MD MC MN ME MA MZ MM NA NR NP NL NZ NI NE NG MK NO OM PK PW PA PG PY PE PH PL PT QA RO RU RW KN LC VC WS SM ST SA SN RS SC SL SG SK SI SB SO ZA KR SS ES LK SD SR SE CH SY TW TJ TZ TH TL TG TO TT TN TR TM TV UG UA AE GB US UY UZ VU VA VE VN YE ZM ZW').split(' ');
let countriesBuilt = false;
function buildCountries() {
    if (countriesBuilt) return;
    countriesBuilt = true;
    let names = null;
    try { names = new Intl.DisplayNames(['en'], { type: 'region' }); } catch (_e) { /* fall back to codes */ }
    const list = COUNTRY_CODES.map((c) => [c, (names && names.of(c)) || c]).sort((a, b) => a[1].localeCompare(b[1]));
    ['kycProviderCountry', 'kycUpCountry'].forEach((id) => {
        const sel = $(id);
        if (sel) list.forEach(([c, n]) => { const o = document.createElement('option'); o.value = c; o.textContent = n; sel.appendChild(o); });
    });
}

function openKyc() {
    const k = state.kyc;
    const opts = state.kycOptions || {};
    const providers = !!opts.providers_available;
    const form = $('kycForm'), pform = $('kycProviderForm'), uform = $('kycUploadForm'), info = $('kycInfo'), err = $('kycError');
    err.textContent = ''; $('kycProviderError').textContent = ''; $('kycUpError').textContent = '';
    const open_ = ['UNVERIFIED', 'FAILED', 'INFO_REQUIRED'].includes(k.status) && !k.unavailable;
    const resumable = k.status === 'PENDING' && k.method === 'PROVIDER' && ['STARTED', 'ABANDONED'].includes(k.provider_status) && !k.unavailable;
    const showProvider = providers && (open_ || resumable);
    const upload = !providers && !!opts.upload_enabled;
    const showUpload = upload && open_;
    const showManual = !providers && !upload && open_ && opts.manual_allowed !== false;
    pform.hidden = !showProvider;
    uform.hidden = !showUpload;
    form.hidden = !showManual;
    info.hidden = showProvider || showManual || showUpload;
    if (showUpload) { buildCountries(); syncBackField(); }
    $('kycNote').hidden = !k.note;
    $('kycNote').textContent = k.note ? `Reviewer note: ${k.note}` : '';
    if (showProvider) {
        buildCountries();
        if (k.country) $('kycProviderCountry').value = k.country;
        $('kycProviderStart').textContent = resumable ? 'Continue verification' : 'Continue to verification';
    }
    if (info.hidden === false) {
        info.textContent = k.unavailable ? 'Verification is temporarily unavailable. Please try again later.'
            : k.status === 'VERIFIED' ? 'Your identity is verified. Nothing more to do here.'
            : k.method === 'PROVIDER' && ['APPROVED', 'IN_REVIEW'].includes(k.provider_status)
                ? 'Your documents have been checked. Our team will confirm shortly. You can keep mining while you wait.'
                : k.method === 'MANUAL' && upload
                    ? 'Your documents are with our team for review. They are deleted as soon as the check is finished. You can keep mining while you wait.'
                    : 'Your details are with our team for review. You can keep mining while you wait.';
    }
    open('kycModal');
}

// ---- document upload (manual review). Photos are shrunk + re-encoded as JPEG in the browser first (smaller, no phone
// metadata, and iPhone HEIC photos become JPEG). The server re-checks and re-encodes everything again.
function syncBackField() {
    const passport = $('kycUpIdType').value === 'passport';
    $('kycUpBackWrap').hidden = passport;
    $('kycUpBack').required = !passport;
    if (passport) $('kycUpBack').value = '';
}

async function shrink(file, maxSide = 1600) {
    try {
        const bmp = await createImageBitmap(file);
        const scale = Math.min(1, maxSide / Math.max(bmp.width, bmp.height));
        const c = document.createElement('canvas');
        c.width = Math.round(bmp.width * scale); c.height = Math.round(bmp.height * scale);
        c.getContext('2d').drawImage(bmp, 0, 0, c.width, c.height);
        const blob = await new Promise((res) => c.toBlob(res, 'image/jpeg', 0.85));
        return blob || file;
    } catch (_e) { return file; }
}

async function submitUpload(ev) {
    ev.preventDefault();
    const btn = $('kycUpSubmit'), err = $('kycUpError');
    err.textContent = '';
    if (!$('kycUpConsent').checked) { err.textContent = 'Please tick the box to agree before uploading.'; return; }
    btn.disabled = true;
    const label = btn.textContent;
    btn.textContent = 'Uploading…';
    try {
        const fd = new FormData();
        fd.append('legal_name', $('kycUpName').value);
        fd.append('country', $('kycUpCountry').value);
        fd.append('id_type', $('kycUpIdType').value);
        fd.append('consent', 'true');
        fd.append('id_front', await shrink($('kycUpFront').files[0]), 'front.jpg');
        if ($('kycUpIdType').value !== 'passport' && $('kycUpBack').files[0]) fd.append('id_back', await shrink($('kycUpBack').files[0]), 'back.jpg');
        fd.append('selfie', await shrink($('kycUpSelfie').files[0]), 'selfie.jpg');
        await ctx.req('/api/xera/kyc/documents', { method: 'POST', body: fd });
        ['kycUpFront', 'kycUpBack', 'kycUpSelfie'].forEach((id) => { $(id).value = ''; });
        await refresh();
        close('kycModal');
    } catch (e) {
        err.textContent = e.message || 'Could not upload your documents. Please try again.';
    } finally { btn.disabled = false; btn.textContent = label; }
}

async function startProviderKyc(ev) {
    ev.preventDefault();
    const btn = $('kycProviderStart'), err = $('kycProviderError');
    err.textContent = '';
    const country = $('kycProviderCountry').value;
    if (!country) { err.textContent = 'Please select your country.'; return; }
    btn.disabled = true;
    try {
        // Only the country is sent. The server picks the provider and returns the hosted link.
        const d = await ctx.req('/api/xera/kyc/start', { method: 'POST', body: JSON.stringify({ country }) });
        const url = new URL(d.verification_url, location.href);
        if (url.protocol !== 'https:') throw new Error('Verification link was not valid. Please try again.');
        location.href = url.href;
    } catch (e) {
        err.textContent = e.message || 'Could not start verification. Please try again.';
        btn.disabled = false;
    }
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
    // The server decides whether collection is open (XERA_FEE_COLLECTION_ENABLED) and builds the
    // invoice; this button only asks it to. The amount is never sent from here.
    const canPay = f.collection_enabled && f.status !== 'PAID';
    pay.disabled = !canPay;
    pay.textContent = f.status === 'PAID' ? 'Already paid' : (f.collection_enabled ? 'Pay with USDT (BNB Smart Chain)' : 'Payment not open yet');
    $('feeRefund').textContent = f.collection_enabled
        ? 'Refund policy: shown here before any payment is taken.'
        : 'Refund policy: will be shown here, and must be accepted, before payment opens. Nothing is charged today.';
    open('feeModal');
}

async function startFeePayment() {
    const pay = $('feePay');
    const status = $('feeModalStatus');
    pay.disabled = true;
    try {
        const d = await ctx.req('/api/xera/fee/pay', { method: 'POST' });
        const url = d?.payment?.invoice_url;
        if (typeof url !== 'string' || !url.startsWith('https://')) throw new Error('Payment session was not created.');
        window.location.href = url;   // leave the button disabled while the browser navigates away
    } catch (e) {
        status.textContent = e.message || 'Could not start the payment. Please try again.';
        pay.disabled = false;
    }
}

// Back from the USDT checkout (?fee=return): the webhook marks the fee paid, so re-read the
// server's answer a few times instead of showing a stale "unpaid".
function pollAfterFeeReturn(attempt = 0) {
    refresh().then(() => {
        if (state && state.fee.status === 'PAID') return;
        if (attempt < 12) setTimeout(() => pollAfterFeeReturn(attempt + 1), 5000);
    });
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
        state = { kyc: d.kyc, fee: d.fee, missing: d.missing || [], notifications: d.notifications || [], kycOptions: d.kyc_options || {} };
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
    $('feePay').addEventListener('click', startFeePayment);
    $('kycForm').addEventListener('submit', submitKyc);
    $('kycProviderForm').addEventListener('submit', startProviderKyc);
    $('kycUploadForm').addEventListener('submit', submitUpload);
    $('kycUpIdType').addEventListener('change', syncBackField);
    [['kycLater', 'kycModal'], ['kycProviderLater', 'kycModal'], ['kycUpLater', 'kycModal'], ['kycClose', 'kycModal'], ['feeCancel', 'feeModal'], ['feeClose', 'feeModal'], ['reqClose', 'reqModal'], ['reqLater', 'reqModal']]
        .forEach(([btn, modal]) => { const b = $(btn); if (b) b.addEventListener('click', () => close(modal)); });
    ['kycModal', 'feeModal', 'reqModal'].forEach((id) => $(id).addEventListener('click', (e) => { if (e.target.id === id) close(id); }));
}

export function initReadiness(c) {
    if (!$('readinessCards')) return;
    ctx = c;
    wire();
    const returning = new URLSearchParams(location.search).get('fee') === 'return';
    if (returning) history.replaceState({}, '', location.pathname + location.hash);
    if (returning) pollAfterFeeReturn(); else refresh();
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
