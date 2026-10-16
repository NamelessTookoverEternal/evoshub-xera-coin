// Splash init (moved out of index.html so the Hub's script-src 'self' CSP allows it).
(function () {
  var p = location.pathname.replace(/^\/evosdata(?=\/|$)/, "") || "/";
  var el = document.getElementById("splash");
  var skip = p.indexOf("/dashxera") === 0 || p === "/success";
  try { if (sessionStorage.getItem("evos_splash")) skip = true; } catch (e) {}
  window.__splashStart = Date.now();
  if (skip && el) el.parentNode.removeChild(el);
})();
