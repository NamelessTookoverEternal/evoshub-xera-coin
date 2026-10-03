// Runs before first paint. If the XERA splash already played this session, hide it immediately.
try { if (sessionStorage.getItem('xera-splash-seen') === '1') document.documentElement.classList.add('xs-skip') } catch (e) {}
