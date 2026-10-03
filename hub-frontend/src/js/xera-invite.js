// XERA invite landing page (/xera/invite?ref=CODE)
//   Step 1: install the app (PWA)   Step 2: create account with the code pre-filled.
// The code is saved to localStorage so it is still there when the person opens the
// installed app (Android/Chrome share storage with the browser; iOS does not, which
// is why the code is also shown on screen with a Copy button).
import './pwa.js' // registers the service worker (needed for the install prompt)

const API = window.XERA_API_BASE || (import.meta.env && import.meta.env.VITE_API_BASE_URL) || ((location.hostname === 'localhost' || location.hostname === '127.0.0.1') ? 'http://localhost:8000' : 'https://api.evoshub.xyz')
const $ = (id) => document.getElementById(id)
const REF_KEY = 'xera_ref'
const REF_RE = /^[A-Za-z0-9_-]{3,64}$/

const safeGet = (k) => { try { return localStorage.getItem(k) || '' } catch (e) { return '' } }
const safeSet = (k, v) => { try { localStorage.setItem(k, v) } catch (e) { /* storage blocked: the URL still carries the code */ } }

let code = (new URLSearchParams(location.search).get('ref') || '').trim()
if (!REF_RE.test(code)) code = ''
if (!code) { const saved = safeGet(REF_KEY); code = REF_RE.test(saved) ? saved : '' }

const standalone = window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true
const createUrl = (c) => '/xera' + (c ? '?ref=' + encodeURIComponent(c) : '')

// Already inside the installed app: skip straight to account creation.
if (standalone) {
    if (code) safeSet(REF_KEY, code)
    location.replace(createUrl(code))
}

function showCode(c) {
    $('inviteCode').textContent = c
    $('inviteCodeBox').hidden = false
    $('createLink').href = createUrl(c)
}

if (code) {
    safeSet(REF_KEY, code)   // keep it even if validation below fails (offline etc.)
    showCode(code)

    fetch(API + '/api/xera/referral/validate?code=' + encodeURIComponent(code))
        .then((r) => r.json())
        .then((d) => {
            if (d.valid) {
                code = d.code || code
                safeSet(REF_KEY, code)
                showCode(code)
                $('inviteTitle').textContent = `${d.inviter} invited you to XERA`
            } else {
                $('inviteLine').textContent = "This invite code wasn't recognised, but you can still create an account."
                $('createNote').textContent = 'You can also enter a code on the sign-up form.'
            }
        })
        .catch(() => { /* leave the generic copy in place */ })
} else {
    $('createNote').textContent = 'Have an invite code? You can enter it on the sign-up form.'
}

$('copyInviteCode').onclick = async () => {
    try {
        await navigator.clipboard.writeText(code)
        $('copyInviteCode').textContent = 'Copied'
    } catch (e) {
        $('copyInviteCode').textContent = 'Select the code to copy'
    }
}

// ---------- Step 1: install ----------
const isIOS = /iphone|ipad|ipod/i.test(navigator.userAgent)
let deferred = null

if (isIOS) {
    $('installNote').textContent = 'On iPhone/iPad: tap the Share button in Safari, then “Add to Home Screen”. Open XERA from your home screen and enter the invite code above when you sign up.'
} else {
    $('installNote').textContent = 'If you don’t see an Install button, open this page in Chrome and use the menu → “Install app” / “Add to Home screen”. You can also just continue to step 2.'
}

window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault()
    deferred = e
    $('installBtn').hidden = false
    $('installNote').textContent = 'Installs in a few seconds. Then open XERA and create your account.'
})

$('installBtn').addEventListener('click', async () => {
    if (!deferred) return
    deferred.prompt()
    const choice = await deferred.userChoice.catch(() => null)
    deferred = null
    $('installBtn').hidden = true
    if (choice && choice.outcome === 'accepted') {
        $('stepInstall').classList.add('done')
        $('installNote').textContent = 'Installed. Open XERA from your home screen to create your account — or continue below.'
    }
})

window.addEventListener('appinstalled', () => {
    $('stepInstall').classList.add('done')
    $('installBtn').hidden = true
})
