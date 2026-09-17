// XERA — ambient space layer
// Decorative only: stars, soft particles and a restrained parallax drift.
// No application state or API behavior is touched.
(() => {
  const field = document.getElementById('xeraStarfield') || document.getElementById('xeraPublicStars');
  if (!field) return;

  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const count = window.innerWidth < 640 ? 46 : window.innerWidth < 1000 ? 72 : 104;
  const frag = document.createDocumentFragment();

  for (let i = 0; i < count; i++) {
    const star = document.createElement('span');
    star.className = 'xera-star';
    const size = (Math.random() * 2 + 0.7).toFixed(2);
    star.style.width = `${size}px`;
    star.style.height = `${size}px`;
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
})();
