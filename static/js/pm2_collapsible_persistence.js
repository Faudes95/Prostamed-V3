/* EPIC 33.A — Collapsible sections persistence + HIPAA audit log
 *
 * Wraps <details data-section-key="X"> elements:
 * - Reads localStorage[pm2_collapse_X] on page load to restore user state
 * - On toggle, persists state + POSTs audit log to /api/clinical-view-audit
 *
 * Importance-aware defaults:
 *  - critical: ALWAYS open (override localStorage to prevent missing critical data)
 *  - standard: respects localStorage (default open)
 *  - archival: respects localStorage (default collapsed)
 *
 * Council concession (Critic): each open/close logs to clinical_view_audit
 * for HIPAA §164.312(b) accountability.
 */

(function () {
    'use strict';

    const STORAGE_PREFIX = 'pm2_collapse_';

    function getPatientNss() {
        // Extract NSS from URL path /patient_profile/<nss>
        // EPIC 0.H fix C1 (FAUBOT CXLVI): decodeURIComponent porque el
        // capture group viene URL-encoded (NSS reales contienen espacios →
        // %20 en URL). Sin decode el server busca NSS literal '%2033...' y
        // retorna 404 en cada toggle → audit log HIPAA §164.312(b) silently empty.
        const match = window.location.pathname.match(/\/patient_profile\/([^\/?#]+)/);
        if (!match) return null;
        try {
            return decodeURIComponent(match[1]);
        } catch (_) {
            return match[1];
        }
    }

    function getSessionId() {
        let sid = sessionStorage.getItem('pm2_session_id');
        if (!sid) {
            sid = 'sess_' + Date.now() + '_' + Math.random().toString(36).slice(2, 10);
            sessionStorage.setItem('pm2_session_id', sid);
        }
        return sid;
    }

    function postAuditEvent(sectionKey, action, importance) {
        const nss = getPatientNss();
        if (!nss) return; // not on patient profile, skip
        const body = {
            patient_nss: nss,
            section_key: sectionKey,
            action: action,
            importance: importance || null,
            actor_session_id: getSessionId(),
        };
        // Use sendBeacon for reliable delivery even on page unload
        try {
            if (navigator.sendBeacon) {
                const blob = new Blob([JSON.stringify(body)], { type: 'application/json' });
                navigator.sendBeacon('/api/clinical-view-audit', blob);
                return;
            }
        } catch (e) { /* fall through */ }
        // Fallback fetch
        try {
            fetch('/api/clinical-view-audit', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
                keepalive: true,
            }).catch(() => { /* silent */ });
        } catch (e) { /* silent */ }
    }

    function applyStoredState(details) {
        const key = details.dataset.sectionKey;
        const importance = details.dataset.importance || 'standard';
        if (!key) return;

        // Critical sections ALWAYS open (override localStorage)
        if (importance === 'critical') {
            details.open = true;
            return;
        }

        const stored = localStorage.getItem(STORAGE_PREFIX + key);
        if (stored === 'open') {
            details.open = true;
        } else if (stored === 'collapsed') {
            details.open = false;
        }
        // Otherwise leave HTML default (set via `open` attribute server-side)
    }

    function attachToggleHandler(details) {
        const key = details.dataset.sectionKey;
        const importance = details.dataset.importance || 'standard';
        if (!key) return;

        details.addEventListener('toggle', function () {
            const newState = details.open ? 'open' : 'collapsed';
            // Persist (skip critical sections — always open)
            if (importance !== 'critical') {
                try {
                    localStorage.setItem(STORAGE_PREFIX + key, newState);
                } catch (e) { /* quota exceeded or disabled */ }
            }
            // Audit log
            const action = details.open ? 'opened' : 'collapsed';
            postAuditEvent(key, action, importance);
        });
    }

    function logCollapsedViewedOnPageLoad(details) {
        // For sections collapsed at page load, audit log "viewed_collapsed"
        // so reconstruction knows clinician saw this section in collapsed state
        const key = details.dataset.sectionKey;
        const importance = details.dataset.importance || 'standard';
        if (!key) return;
        if (!details.open) {
            postAuditEvent(key, 'viewed_collapsed', importance);
        }
    }

    function buildSectionNav() {
        const allDetails = document.querySelectorAll('details[data-section-key]');
        if (allDetails.length < 4) return; // not worth nav if <4 sections

        const nav = document.createElement('nav');
        nav.className = 'pm2-section-nav';
        nav.setAttribute('aria-label', 'Index de secciones del perfil clínico');

        allDetails.forEach(function (details) {
            const key = details.dataset.sectionKey;
            const label = details.dataset.sectionLabel || details.querySelector('summary')?.textContent?.trim().split('\n')[0] || key;
            const importance = details.dataset.importance || 'standard';

            // Anchor target
            if (!details.id) details.id = 'sec_' + key;

            const link = document.createElement('a');
            link.href = '#' + details.id;
            link.textContent = label.length > 28 ? label.slice(0, 26) + '…' : label;
            if (importance === 'critical') link.className = 'is-critical';

            link.addEventListener('click', function (e) {
                e.preventDefault();
                // Force open the section + scroll
                if (!details.open) details.open = true;
                details.scrollIntoView({ behavior: 'smooth', block: 'start' });
            });

            nav.appendChild(link);
        });

        // Insert after first <h1> or at top of <main>
        const main = document.querySelector('main') || document.body;
        const firstChild = main.firstElementChild;
        if (firstChild) {
            main.insertBefore(nav, firstChild.nextSibling);
        }
    }

    function init() {
        const collapsibles = document.querySelectorAll('details.pm2-section-collapsible[data-section-key]');
        collapsibles.forEach(function (details) {
            applyStoredState(details);
            attachToggleHandler(details);
            logCollapsedViewedOnPageLoad(details);
        });
        buildSectionNav();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
