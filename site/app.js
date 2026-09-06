// Arcaflame site — two small behaviours, no dependencies.
// The site is light-only by design, so there is no theme code here.

document.documentElement.classList.add('js');

/* 1. Copy buttons. Clipboard can reject (insecure context, denied permission),
      so the failure path says so instead of silently claiming success. */
for (const btn of document.querySelectorAll('.copy')) {
  const state = btn.querySelector('.copy-state');
  btn.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(btn.dataset.copy);
      state.textContent = 'Copied';
    } catch (e) {
      state.textContent = 'Press ⌘/Ctrl+C';
    }
    btn.classList.add('is-done');
    clearTimeout(btn._t);
    btn._t = setTimeout(() => { state.textContent = 'Copy'; btn.classList.remove('is-done'); }, 1800);
  });
}

/* 2. Reveal on scroll, and a hairline under the nav once it lifts off. */
const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
const items = document.querySelectorAll('.reveal');

if (reduced) {
  for (const el of items) el.classList.add('is-in');
} else {
  const io = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      entry.target.classList.add('is-in');
      io.unobserve(entry.target);       // one-shot: never re-animate on scroll back
    }
  }, { rootMargin: '0px 0px -8% 0px', threshold: 0.05 });
  for (const el of items) io.observe(el);
}

const nav = document.querySelector('.nav');
const sentinel = document.createElement('div');
document.body.prepend(sentinel);
new IntersectionObserver(
  ([e]) => nav.classList.toggle('is-stuck', !e.isIntersecting)
).observe(sentinel);
