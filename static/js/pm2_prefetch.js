/* ProstaMed v2 — Hover prefetch (LXCI Fase 6)
   Reduces perceived latency on sidebar navigation by preloading routes when
   the user hovers over a nav link. Idempotent (won't prefetch same URL twice).
   No-op on touch devices (avoid wasted bandwidth on mobile).
*/
(function() {
    if (!('PointerEvent' in window)) return;
    // Skip on touch-primary devices
    if (window.matchMedia && window.matchMedia('(hover: none)').matches) return;

    const prefetched = new Set();

    function prefetchLink(link) {
        const href = link.getAttribute('href');
        if (!href || href === '#' || href.startsWith('#') ||
            href.startsWith('http') || href.startsWith('javascript:')) return;
        if (prefetched.has(href)) return;
        prefetched.add(href);
        try {
            const l = document.createElement('link');
            l.rel = 'prefetch';
            l.href = href;
            l.as = 'document';
            document.head.appendChild(l);
            link.dataset.prefetched = 'true';
        } catch (e) { /* silent */ }
    }

    // Capture phase to catch hover early
    document.addEventListener('mouseenter', (e) => {
        const link = e.target.closest && e.target.closest(
            'a.pm2-sidebar-link, a.pm2-sidebar-action, a.pm2-tab[href]'
        );
        if (!link) return;
        prefetchLink(link);
    }, true);

    // Touch-equivalent: prefetch on touchstart (anticipate click)
    document.addEventListener('touchstart', (e) => {
        const link = e.target.closest && e.target.closest(
            'a.pm2-sidebar-link, a.pm2-sidebar-action'
        );
        if (link) prefetchLink(link);
    }, { passive: true, capture: true });
})();
