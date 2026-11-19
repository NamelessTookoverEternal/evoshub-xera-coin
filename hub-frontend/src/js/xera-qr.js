// QR codes for XERA IDs (used by /xera-transfer).
//  - showQr: draws a QR for "your XERA ID" (the QR holds a link that opens the send form with the ID filled in).
//  - scanQr: opens the camera (or a photo) and returns the XERA ID found in a QR.
// The two small libraries live in /vendor (qrcode-generator, jsQR) and load only when a QR is actually used.
// A QR carries only the public XERA ID, never a name, balance or token. All text is set with textContent.

const XID_RE = /XR-[A-Z2-9]{8}/;

export function extractXeraId(text) {
  const m = String(text || '').toUpperCase().match(XID_RE);
  return m ? m[0] : null;
}

export function shareLink(xid) {
  return `${location.origin}/xera-transfer?to=${encodeURIComponent(xid)}`;
}

const loading = {};
function loadScript(src) {
  if (!loading[src]) {
    loading[src] = new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = src; s.async = true;
      s.onload = resolve;
      s.onerror = () => { delete loading[src]; reject(new Error('Could not load the QR tools. Check your connection and try again.')); };
      document.head.appendChild(s);
    });
  }
  return loading[src];
}

async function matrixFor(text) {
  await loadScript('/vendor/qrcode.js');
  const qr = window.qrcode(0, 'M');   // type 0 = pick the smallest size that fits; M = medium error correction
  qr.addData(text);
  qr.make();
  const n = qr.getModuleCount();
  return { n, dark: (r, c) => qr.isDark(r, c) };
}

const QUIET = 4;   // quiet-zone modules around the code, needed for reliable scanning

// Draws the QR as an inline SVG (black on white, whatever the page theme is).
export async function showQr(container, text) {
  const { n, dark } = await matrixFor(text);
  const size = n + QUIET * 2;
  const NS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('viewBox', `0 0 ${size} ${size}`);
  svg.setAttribute('shape-rendering', 'crispEdges');
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', 'QR code for your XERA ID');
  svg.style.cssText = 'width:100%;max-width:260px;height:auto;display:block;margin:0 auto;border-radius:10px';
  const bg = document.createElementNS(NS, 'rect');
  bg.setAttribute('width', size); bg.setAttribute('height', size); bg.setAttribute('fill', '#fff');
  let d = '';
  for (let r = 0; r < n; r++) for (let c = 0; c < n; c++) if (dark(r, c)) d += `M${c + QUIET} ${r + QUIET}h1v1h-1z`;
  const path = document.createElementNS(NS, 'path');
  path.setAttribute('d', d); path.setAttribute('fill', '#000');
  svg.append(bg, path);
  container.textContent = '';
  container.appendChild(svg);
}

// A PNG with the QR and the XERA ID under it, for saving or sharing.
export async function qrPngBlob(text, label) {
  const { n, dark } = await matrixFor(text);
  const cell = 10, pad = QUIET * cell, side = n * cell + pad * 2, footer = 56;
  const cv = document.createElement('canvas');
  cv.width = side; cv.height = side + footer;
  const g = cv.getContext('2d');
  g.fillStyle = '#fff'; g.fillRect(0, 0, cv.width, cv.height);
  g.fillStyle = '#000';
  for (let r = 0; r < n; r++) for (let c = 0; c < n; c++) if (dark(r, c)) g.fillRect(pad + c * cell, pad + r * cell, cell, cell);
  g.textAlign = 'center'; g.font = '600 26px system-ui, sans-serif';
  g.fillText(label, side / 2, side + 20);
  return new Promise((res) => cv.toBlob(res, 'image/png'));
}

// ------------------------------------------------------------------ scanner
function decodeImageData(img) {
  const r = window.jsQR(img.data, img.width, img.height, { inversionAttempts: 'dontInvert' });
  return r ? r.data : null;
}

const CSS =
  '.xqr{position:fixed;inset:0;z-index:10000;background:rgba(0,0,0,.92);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;padding:16px;color:#fff;font:inherit}' +
  '.xqr video{width:min(92vw,420px);max-height:60vh;border-radius:14px;background:#000;object-fit:cover}' +
  '.xqr p{margin:0;font-size:.85rem;text-align:center;max-width:380px;line-height:1.5}' +
  '.xqr .xqr-err{color:#ff9b9b;min-height:1.2em}' +
  '.xqr .xqr-row{display:flex;gap:10px;flex-wrap:wrap;justify-content:center}' +
  '.xqr button,.xqr label{font:inherit;color:#fff;border:1px solid rgba(255,255,255,.35);background:rgba(255,255,255,.1);border-radius:12px;padding:10px 16px;cursor:pointer}';

// Opens the scanner. Resolves with a XERA ID, or null if the person closed it.
export function scanQr() {
  return new Promise((resolve) => {
    if (!document.getElementById('xqr-css')) {
      const st = document.createElement('style'); st.id = 'xqr-css'; st.textContent = CSS; document.head.appendChild(st);
    }
    const root = document.createElement('div'); root.className = 'xqr'; root.setAttribute('role', 'dialog'); root.setAttribute('aria-modal', 'true'); root.setAttribute('aria-label', 'Scan a XERA QR code');
    const video = document.createElement('video'); video.setAttribute('playsinline', ''); video.muted = true;
    const msg = document.createElement('p'); msg.textContent = 'Point your camera at a XERA QR code.';
    const err = document.createElement('p'); err.className = 'xqr-err'; err.setAttribute('role', 'alert');
    const row = document.createElement('div'); row.className = 'xqr-row';
    const photo = document.createElement('label'); photo.textContent = 'Choose a photo';
    const file = document.createElement('input'); file.type = 'file'; file.accept = 'image/*'; file.hidden = true; photo.appendChild(file);
    const close = document.createElement('button'); close.type = 'button'; close.textContent = 'Close';
    row.append(photo, close);
    root.append(video, msg, err, row);
    document.body.appendChild(root);

    let stream = null, stopped = false, timer = 0;
    const cv = document.createElement('canvas');
    const g = cv.getContext('2d', { willReadFrequently: true });

    const done = (xid) => {
      if (stopped) return; stopped = true;
      clearTimeout(timer);
      if (stream) stream.getTracks().forEach((t) => t.stop());
      root.remove();
      resolve(xid);
    };
    const accept = (text) => {
      const xid = extractXeraId(text);
      if (xid) { done(xid); return true; }
      err.textContent = 'That QR code is not a XERA ID.';
      return false;
    };
    close.addEventListener('click', () => done(null));
    root.addEventListener('keydown', (e) => { if (e.key === 'Escape') done(null); });

    file.addEventListener('change', async () => {
      const f = file.files && file.files[0]; if (!f) return;
      try {
        await loadScript('/vendor/jsQR.js');
        const bmp = await createImageBitmap(f);
        const scale = Math.min(1, 1200 / Math.max(bmp.width, bmp.height));
        cv.width = Math.round(bmp.width * scale); cv.height = Math.round(bmp.height * scale);
        g.drawImage(bmp, 0, 0, cv.width, cv.height);
        const text = decodeImageData(g.getImageData(0, 0, cv.width, cv.height));
        if (!text) err.textContent = 'No QR code found in that photo. Try a clearer one.'; else accept(text);
      } catch (_e) { err.textContent = 'Could not read that photo.'; }
      file.value = '';
    });

    (async () => {
      try {
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) throw new Error('nocam');
        // BarcodeDetector is built into Chrome on Android; everywhere else the jsQR library reads the frames.
        let detector = null;
        if ('BarcodeDetector' in window) {
          try { detector = new window.BarcodeDetector({ formats: ['qr_code'] }); } catch (_e) { detector = null; }
        }
        if (!detector) await loadScript('/vendor/jsQR.js');
        stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: 'environment' } }, audio: false });
        if (stopped) { stream.getTracks().forEach((t) => t.stop()); return; }
        video.srcObject = stream;
        await video.play();
        const tick = async () => {
          if (stopped) return;
          try {
            if (video.readyState >= 2 && video.videoWidth) {
              if (detector) {
                const found = await detector.detect(video);
                if (found.length && accept(found[0].rawValue)) return;
              } else {
                const scale = Math.min(1, 640 / video.videoWidth);
                cv.width = Math.round(video.videoWidth * scale); cv.height = Math.round(video.videoHeight * scale);
                g.drawImage(video, 0, 0, cv.width, cv.height);
                const text = decodeImageData(g.getImageData(0, 0, cv.width, cv.height));
                if (text && accept(text)) return;
              }
            }
          } catch (_e) { /* a bad frame: try the next one */ }
          timer = setTimeout(tick, 150);
        };
        tick();
      } catch (e) {
        video.hidden = true;
        err.textContent = e && e.name === 'NotAllowedError'
          ? 'Camera permission was denied. Allow the camera for this site, or choose a photo of the QR code.'
          : (e && e.message && e.message !== 'nocam' ? e.message : 'Could not open the camera. You can choose a photo of the QR code instead.');
      }
    })();
  });
}
