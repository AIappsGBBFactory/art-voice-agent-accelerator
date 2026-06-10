// ============================================================
// ART Agent Docs v2 — Main JS (no build step required)
// ============================================================

// --- Legacy-docs URL override ---
// The "Legacy" header pill and sidebar link default to `legacy-site/index.html`,
// which is the mkdocs build output (sources live at `docs/legacy/`, built into
// `docs/legacy-site/`). Run `make docs-legacy-build` once to populate it.
//
// In production, set LEGACY_DOCS_URL to an absolute URL (e.g. the GH Pages
// site at https://azure-samples.github.io/art-voice-agent-accelerator/, or a
// dedicated `/legacy/` subpath) to repoint all legacy links from one place.
// Leave as null to keep the relative `legacy-site/index.html` default.
const LEGACY_DOCS_URL = null;

document.addEventListener('DOMContentLoaded', () => {

  // --- Apply legacy-docs URL override (if configured) ---
  if (LEGACY_DOCS_URL) {
    document.querySelectorAll('#legacy-docs-link, #legacy-docs-sidebar-link')
      .forEach(el => { el.href = LEGACY_DOCS_URL; });
  }

  // --- Theme toggle ---
  const toggle = document.querySelector('.theme-toggle');
  const saved = localStorage.getItem('art-docs-theme');
  if (saved) document.documentElement.setAttribute('data-theme', saved);
  else if (window.matchMedia('(prefers-color-scheme: dark)').matches) {
    document.documentElement.setAttribute('data-theme', 'dark');
  }
  if (toggle) {
    const update = () => {
      const dark = document.documentElement.getAttribute('data-theme') === 'dark';
      toggle.textContent = dark ? '☀️' : '🌙';
    };
    update();
    toggle.addEventListener('click', () => {
      const next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      localStorage.setItem('art-docs-theme', next);
      update();
      document.dispatchEvent(new CustomEvent('art-theme-changed', { detail: { theme: next } }));
    });
  }

  // --- Active sidebar link tracking ---
  const sidebarLinks = document.querySelectorAll('.sidebar-section a[href^="#"]');
  if (sidebarLinks.length) {
    const sections = [];
    sidebarLinks.forEach(link => {
      const id = link.getAttribute('href').slice(1);
      const el = document.getElementById(id);
      if (el) sections.push({ link, el });
    });

    const setActive = () => {
      let current = sections[0];
      for (const s of sections) {
        if (s.el.getBoundingClientRect().top <= 100) current = s;
      }
      sidebarLinks.forEach(l => l.classList.remove('active'));
      if (current) current.link.classList.add('active');
    };
    window.addEventListener('scroll', setActive, { passive: true });
    setActive();
  }

  // --- Tab groups ---
  document.querySelectorAll('.tab-group').forEach(group => {
    const btns = group.querySelectorAll('.tab-btn');
    const panels = group.querySelectorAll('.tab-panel');
    btns.forEach(btn => {
      btn.addEventListener('click', () => {
        btns.forEach(b => b.classList.remove('active'));
        panels.forEach(p => p.classList.remove('active'));
        btn.classList.add('active');
        const target = group.querySelector(`#${btn.dataset.tab}`);
        if (target) target.classList.add('active');
      });
    });
  });

  // --- Mobile sidebar ---
  const sidebarToggle = document.querySelector('.sidebar-toggle');
  const sidebar = document.querySelector('.sidebar');
  if (sidebarToggle && sidebar) {
    sidebarToggle.addEventListener('click', () => sidebar.classList.toggle('open'));
    document.addEventListener('click', (e) => {
      if (!sidebar.contains(e.target) && !sidebarToggle.contains(e.target)) {
        sidebar.classList.remove('open');
      }
    });
  }

  // --- Copy code buttons ---
  document.querySelectorAll('pre').forEach(pre => {
    if (pre.closest('.code-block')) return;

    const wrapper = document.createElement('div');
    wrapper.className = 'code-block';

    const toolbar = document.createElement('div');
    toolbar.className = 'code-block-toolbar';

    const label = document.createElement('span');
    label.className = 'code-block-label';
    label.textContent = 'Code';

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'code-block-copy';

    const resetLabel = () => {
      btn.textContent = 'Copy';
      btn.setAttribute('aria-label', 'Copy code to clipboard');
    };

    resetLabel();
    btn.addEventListener('click', async () => {
      const text = pre.textContent.trimEnd();
      await navigator.clipboard.writeText(text);
      btn.textContent = 'Copied';
      btn.setAttribute('aria-label', 'Copied to clipboard');
      window.setTimeout(resetLabel, 1500);
    });

    toolbar.append(label, btn);
    pre.parentNode.insertBefore(wrapper, pre);
    wrapper.append(toolbar, pre);

    pre.addEventListener('mouseenter', () => btn.classList.add('is-visible'));
    pre.addEventListener('mouseleave', () => btn.classList.remove('is-visible'));
  });

  // --- Header active page ---
  const path = window.location.pathname.split('/').pop() || 'index.html';
  document.querySelectorAll('.header-nav a').forEach(a => {
    const href = a.getAttribute('href');
    if (href === path || (path === 'index.html' && href === 'index.html')) {
      a.classList.add('active');
    }
  });

  // --- Expandable architecture diagrams (lightbox) ---
  const overlay = document.createElement('div');
  overlay.className = 'lightbox-overlay';
  overlay.innerHTML = '<img src="" alt="">';
  document.body.appendChild(overlay);
  const overlayImg = overlay.querySelector('img');

  document.querySelectorAll('.arch-diagram[data-expandable]').forEach(fig => {
    fig.addEventListener('click', () => {
      const img = fig.querySelector('img');
      if (img) {
        overlayImg.src = img.src;
        overlayImg.alt = img.alt;
        overlay.classList.add('open');
      }
    });
  });
  overlay.addEventListener('click', () => overlay.classList.remove('open'));
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') overlay.classList.remove('open');
  });

  // --- Render mermaid diagrams ---
  if (typeof mermaid !== 'undefined') {
    const dark = document.documentElement.getAttribute('data-theme') === 'dark';
    mermaid.initialize({
      startOnLoad: true,
      theme: dark ? 'dark' : 'default',
      securityLevel: 'loose',
      flowchart: { useMaxWidth: true, htmlLabels: true },
    });
  }

});
