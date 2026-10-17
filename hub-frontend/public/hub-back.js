/* EVOS Hub — floating "back" tab.
 *
 * One tiny self-contained script (no dependencies, no build step) that sits on the
 * left edge of the screen, vertically centred, on top of every product that lives in
 * the Hub: EvosData, EVOSGPT, XERA, Website Creation and anything added later.
 * It is not a sidebar — just a small tab that expands on hover/focus.
 *
 * Tap behaviour:
 *   - the visitor came from another page of this site  -> one step back (history.back())
 *   - otherwise (deep link, new tab, refresh)           -> the product hub (/appevoxera)
 *
 * Hub pages include it with <script src="/hub-back.js" defer>; the EvosData and
 * EVOSGPT apps inject it when they are built for the Hub mount.
 */
(function () {
  'use strict';
  if (window.__evosHubBack) return;
  window.__evosHubBack = true;

  var HUB_PATH = '/appevoxera';
  // Pages that ARE the hub (or its public front door): nothing to go back to.
  var HIDE_ON = ['/', '/index.html', '/home', '/home.html', '/appevoxera', '/appevoxera.html'];
  function hidden() {
    var p = location.pathname.replace(/\/+$/, '') || '/';
    return HIDE_ON.indexOf(p) !== -1;
  }

  function cameFromThisSite() {
    try {
      if (!document.referrer || history.length < 2) return false;
      var r = new URL(document.referrer);
      return r.origin === location.origin && r.pathname !== location.pathname;
    } catch (e) { return false; }
  }

  function goBack(e) {
    e.preventDefault();
    if (cameFromThisSite()) history.back();
    else location.href = HUB_PATH;
  }

  var css = [
    '.evos-back{position:fixed;left:0;top:50%;transform:translateY(-50%);z-index:2147483000;',
    'display:flex;align-items:center;gap:8px;height:62px;width:64px;padding:0 0 0 8px;overflow:hidden;',
    'border:1px solid rgba(150,185,255,.28);border-left:0;border-radius:0 20px 20px 0;',
    'color:#e9f0ff;text-decoration:none;cursor:pointer;-webkit-tap-highlight-color:transparent;',
    'background:linear-gradient(160deg,rgba(24,34,56,.82),rgba(8,12,22,.9));',
    '-webkit-backdrop-filter:blur(14px) saturate(160%);backdrop-filter:blur(14px) saturate(160%);',
    'box-shadow:0 10px 30px -8px rgba(0,0,0,.7),0 0 22px -6px rgba(47,123,255,.45),inset 0 1px 0 rgba(255,255,255,.14);',
    'transition:width .35s cubic-bezier(.2,.8,.2,1),box-shadow .3s,border-color .3s;',
    'padding-left:max(8px,env(safe-area-inset-left));font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}',
    '.evos-back:hover,.evos-back:focus-visible{width:158px;border-color:rgba(120,200,255,.7);',
    'box-shadow:0 10px 34px -8px rgba(0,0,0,.75),0 0 30px -4px rgba(47,123,255,.7),inset 0 1px 0 rgba(255,255,255,.2)}',
    '.evos-back:focus-visible{outline:2px solid #7cc8ff;outline-offset:2px}',
    '.evos-back:active{transform:translateY(-50%) scale(.97)}',
    '.evos-back__chev{flex:none;width:16px;height:16px;opacity:.85}',
    '.evos-back__logo{flex:none;width:30px;height:30px;border-radius:50%;background:#fff;object-fit:contain;',
    'box-shadow:0 0 0 1px rgba(120,160,255,.45),0 0 14px rgba(47,123,255,.5)}',
    '.evos-back__txt{display:flex;flex-direction:column;gap:3px;white-space:nowrap;opacity:0;transform:translateX(-6px);',
    'transition:opacity .25s .05s,transform .3s .05s}',
    '.evos-back:hover .evos-back__txt,.evos-back:focus-visible .evos-back__txt{opacity:1;transform:none}',
    '.evos-back__txt b{font-size:13px;font-weight:700;letter-spacing:.01em}',
    '.evos-back__txt i{font-style:normal;font-size:10px;letter-spacing:.18em;text-transform:uppercase;color:#8fb4ff}',
    '@media (max-width:640px){.evos-back{height:54px;width:56px;padding-left:max(6px,env(safe-area-inset-left))}',
    '.evos-back__logo{width:26px;height:26px}.evos-back__chev{width:14px;height:14px}}',
    '@media (prefers-reduced-motion:reduce){.evos-back,.evos-back__txt{transition:none}}',
    '@media print{.evos-back{display:none}}'
  ].join('');

  function mount() {
    if (hidden() || document.getElementById('evos-back')) return;
    var style = document.createElement('style');
    style.id = 'evos-back-style';
    style.textContent = css;
    document.head.appendChild(style);

    var a = document.createElement('a');
    a.id = 'evos-back';
    a.className = 'evos-back';
    a.href = HUB_PATH;
    a.setAttribute('aria-label', 'Go back to EVOS Hub');
    a.innerHTML =
      '<svg class="evos-back__chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 5l-7 7 7 7"/></svg>' +
      '<img class="evos-back__logo" src="/assets/images/evoxera-mark.png" alt="" width="30" height="30" draggable="false">' +
      '<span class="evos-back__txt"><b>Back</b><i>EVOS Hub</i></span>';
    a.addEventListener('click', goBack);
    document.body.appendChild(a);
  }

  if (document.body) mount();
  else document.addEventListener('DOMContentLoaded', mount);
})();
