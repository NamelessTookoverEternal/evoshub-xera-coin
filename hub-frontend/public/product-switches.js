/* EVOS Hub — product switches.
 *
 * Admins can switch a product off from the admin console ("Product switches"). This one small
 * script greys that product's tile on the Ecosystem, app home and Hub pages, and shows a short
 * message instead of opening it. No dependencies, no build step. Included with
 *   <script src="/product-switches.js" defer></script>
 *
 * Rules:
 *   - FAIL OPEN: if the status request fails for any reason, nothing is greyed.
 *   - Greying is only the display. The backend separately refuses NEW EVOS Data orders and
 *     EVOSGPT chats while those are off; payments already in progress are never stopped.
 *   - The status is remembered for 30 s per tab, and browsers cache it for ~30 s, so a change
 *     reaches visitors within about a minute.
 */
(function () {
  'use strict';
  if (window.__evosProductSwitches) return;
  window.__evosProductSwitches = true;

  // The build fills data-api with VITE_API_BASE_URL (same value the rest of the app uses).
  var me = document.currentScript, fromBuild = me && me.getAttribute('data-api');
  var API = (fromBuild && /^https?:\/\//.test(fromBuild)) ? fromBuild.replace(/\/+$/, '')
    : (location.hostname === 'localhost' || location.hostname === '127.0.0.1') ? 'http://localhost:8000' : 'https://api.evoshub.xyz';
  var CACHE_KEY = 'evos_product_switches', TTL = 30000;
  var GRIDS = ['appGrid', 'hubAppGrid'];
  // Link prefix -> product key. First match wins.
  var MAP = [
    ['/xera', 'xera'], ['/evosdata', 'evosdata'], ['/evosgpt', 'evosgpt'],
    ['/games', 'games'], ['/evoxera_master_roadmap_frontend', 'roadmap'], ['/website-creation', 'website']
  ];
  var LABEL = { xera: 'XERA', evosdata: 'EVOS Data', evosgpt: 'EVOSGPT', games: 'Africa Games', roadmap: 'Roadmap', website: 'Website creation' };
  var status = null;

  var css = document.createElement('style');
  css.textContent =
    '.ps-off{opacity:.45;filter:grayscale(1);cursor:not-allowed}' +
    '.ps-toast{position:fixed;left:50%;bottom:24px;transform:translateX(-50%);max-width:min(92vw,380px);z-index:9999;' +
    'background:#1b1f2a;color:#fff;padding:12px 16px;border-radius:12px;font:500 14px/1.4 system-ui,sans-serif;' +
    'box-shadow:0 8px 28px rgba(0,0,0,.35);text-align:center}';
  document.head.appendChild(css);

  function keyFor(a) {
    var path;
    try { path = new URL(a.getAttribute('href') || '', location.href).pathname; } catch (e) { return null; }
    for (var i = 0; i < MAP.length; i++) {
      var p = MAP[i][0];
      if (path === p || path.indexOf(p + '/') === 0 || path.indexOf(p + '.') === 0) return MAP[i][1];
    }
    return null;
  }

  function messageFor(key) {
    var s = status && status[key];
    return (s && s.message) || ((LABEL[key] || 'This product') + ' is switched off for now. Please check back soon.');
  }

  var toastTimer = null;
  function toast(text) {
    var t = document.querySelector('.ps-toast');
    if (!t) { t = document.createElement('div'); t.className = 'ps-toast'; t.setAttribute('role', 'status'); document.body.appendChild(t); }
    t.textContent = text;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { if (t.parentNode) t.parentNode.removeChild(t); }, 3500);
  }

  function apply(root) {
    if (!status) return;
    var links = root.querySelectorAll ? root.querySelectorAll('a[href]') : [];
    for (var i = 0; i < links.length; i++) {
      var a = links[i], key = keyFor(a);
      if (!key) continue;
      var off = !!(status[key] && status[key].enabled === false);
      if (off) {
        a.classList.add('ps-off'); a.setAttribute('aria-disabled', 'true'); a.dataset.psOff = key;
        a.style.pointerEvents = 'auto'; // the old "soon" style blocks taps; we still want to show the message
      } else if (a.dataset.psOff) {
        a.classList.remove('ps-off'); a.removeAttribute('aria-disabled'); delete a.dataset.psOff; a.style.pointerEvents = '';
      }
    }
  }

  function run() {
    GRIDS.forEach(function (id) {
      var g = document.getElementById(id);
      if (!g) return;
      apply(g);
      // admin-curated tiles are appended after load
      new MutationObserver(function () { apply(g); }).observe(g, { childList: true });
    });
  }

  document.addEventListener('click', function (e) {
    var a = e.target.closest && e.target.closest('a[data-ps-off]');
    if (!a) return;
    e.preventDefault(); e.stopPropagation();
    toast(messageFor(a.dataset.psOff));
  }, true);

  function load() {
    try {
      var c = JSON.parse(sessionStorage.getItem(CACHE_KEY) || 'null');
      if (c && Date.now() - c.at < TTL) { status = c.data; return Promise.resolve(); }
    } catch (e) { /* ignore */ }
    return fetch(API + '/api/products/status', { headers: { Accept: 'application/json' } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) {
        if (!j || !j.products) return;
        status = j.products;
        try { sessionStorage.setItem(CACHE_KEY, JSON.stringify({ at: Date.now(), data: status })); } catch (e) { /* ignore */ }
      })
      .catch(function () { /* fail open */ });
  }

  function start() { load().then(run); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
