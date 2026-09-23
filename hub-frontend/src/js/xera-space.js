// XERA — cinematic ambient visual system.
// Visual-only: rotating branded backgrounds + stars + subtle pointer parallax.
// It never reads or changes auth, mining, wallet, Supabase, API or blockchain state.
(() => {
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const root = document.querySelector('.xera-space') || document.querySelector('.xera-public-space');
  if (!root) return;

  const publicRoot = root.classList.contains('xera-public-space');
  const imageBase = '/assets/images/xera-gallery/';
  const images = [
    'xera-future-city.jpg',
    'xera-global-network.jpg',
    'xera-ai-data-core.jpg',
    'xera-digital-mining.jpg'
  ];

  // Pick a meaningful first scene for each page, then continue rotating.
  const path = location.pathname.toLowerCase();
  let preferred = 0;
  if (path.includes('tokenomics')) preferred = 1;
  else if (path.includes('stats')) preferred = 2;
  else if (path.includes('roadmap')) preferred = 0;
  else if (path.includes('faq')) preferred = 2;
  else if (path.includes('disclosure')) preferred = 1;
  else if (path.includes('whitepaper')) preferred = 0;
  else if (path.includes('dashboard') || root.classList.contains('xera-space')) preferred = 3;

  const rotator = document.createElement('div');
  rotator.className = 'xera-bg-rotator';
  rotator.setAttribute('aria-hidden', 'true');
  root.prepend(rotator);

  const ordered = images.map((_, i) => images[(preferred + i) % images.length]);
  const slides = ordered.map((src, i) => {
    const img = document.createElement('img');
    img.className = 'xera-bg-slide' + (i === 0 ? ' is-active' : '');
    img.src = imageBase + src;
    img.alt = '';
    img.decoding = 'async';
    img.loading = i === 0 ? 'eager' : 'lazy';
    rotator.appendChild(img);
    return img;
  });

  // Warm all assets without blocking the page, so transitions don't flash.
  slides.slice(1).forEach(img => { const pre = new Image(); pre.src = img.src; });

  let active = 0;
  let timer = null;
  const show = (next) => {
    slides[active].classList.remove('is-active');
    slides[active].classList.add('is-previous');
    slides[next].classList.remove('is-previous');
    slides[next].classList.add('is-active');
    active = next;
  };

  if (!reduced) {
    timer = window.setInterval(() => show((active + 1) % slides.length), 11000);

    let px = 0, py = 0, raf = 0;
    const update = () => {
      raf = 0;
      rotator.style.setProperty('--xera-parallax-x', `${px}px`);
      rotator.style.setProperty('--xera-parallax-y', `${py}px`);
    };
    window.addEventListener('pointermove', (e) => {
      px = ((e.clientX / Math.max(window.innerWidth, 1)) - .5) * 14;
      py = ((e.clientY / Math.max(window.innerHeight, 1)) - .5) * 10;
      if (!raf) raf = requestAnimationFrame(update);
    }, { passive: true });
  }

  // Existing star system, preserved.
  const field = document.getElementById('xeraStarfield') || document.getElementById('xeraPublicStars');
  if (!field) return;
  const count = window.innerWidth < 640 ? 46 : window.innerWidth < 1000 ? 72 : 104;
  const frag = document.createDocumentFragment();
  for (let i = 0; i < count; i++) {
    const star = document.createElement('span');
    star.className = 'xera-star';
    const size = (Math.random() * 2 + 0.7).toFixed(2);
    star.style.width = `${size}px`; star.style.height = `${size}px`;
    star.style.left = `${(Math.random() * 100).toFixed(2)}%`;
    star.style.top = `${(Math.random() * 100).toFixed(2)}%`;
    star.style.setProperty('--star-delay', `${(Math.random() * 7).toFixed(2)}s`);
    star.style.setProperty('--star-duration', `${(2.4 + Math.random() * 4).toFixed(2)}s`);
    star.style.setProperty('--star-opacity', `${(0.35 + Math.random() * 0.65).toFixed(2)}`);
    frag.appendChild(star);
  }
  if (!reduced) {
    for (let i = 0; i < 3; i++) {
      const shooting = document.createElement('span');
      shooting.className = 'xera-shooting-star';
      shooting.style.top = `${8 + Math.random() * 34}%`;
      shooting.style.left = `${58 + Math.random() * 35}%`;
      shooting.style.setProperty('--shoot-delay', `${(2 + i * 6 + Math.random() * 3).toFixed(2)}s`);
      frag.appendChild(shooting);
    }
  }
  field.appendChild(frag);

  window.addEventListener('pagehide', () => { if (timer) clearInterval(timer); }, { once: true });
})();
