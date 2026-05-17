/**
 * EPIC 43.4 — Smart Capture intake controller.
 *
 * Single-page dynamic intake: collapsible sections, conditional visibility,
 * smart defaults, auto-save to localStorage, voice per section + composite
 * hub, inline reasoning trail per section, Cmd-K quick-jump, completion
 * indicators, keyboard navigation.
 *
 * Architecture:
 *   - Reads schema-derived sections from server-rendered DOM (data attrs).
 *   - All state held in `state.values` (Map<fieldName, value>) +
 *     `state.sectionStatus` (Map<sectionKey, 'empty'|'partial'|'complete'>).
 *   - Persists to localStorage under key `pm2.intake.smart.draft`.
 *   - Calls existing endpoints: /api/voice/quick-capture/<field>,
 *     /api/intake/reasoning-trail, /api/intake/smart-defaults,
 *     /api/state-classifier.
 *
 * Privacy: localStorage NEVER stores PHI — clinician must explicitly Submit.
 * Draft contains form values, NO audio bytes, NO patient identity beyond
 * what's typed in the form.
 */
(function () {
    'use strict';

    const LS_DRAFT_KEY = 'pm2.intake.smart.draft.v1';
    const LS_SECTIONS_KEY = 'pm2.intake.smart.sections.v1';
    const AUTO_SAVE_INTERVAL_MS = 5000;

    const state = {
        schema: null,
        sections: [],
        values: Object.create(null),   // fieldName → value
        fieldsByName: Object.create(null),
        sectionsByAnchor: Object.create(null),
        sectionStatus: Object.create(null),
        currentClassification: null,
        lastSavedAt: null,
        smartDefaults: Object.create(null),
        cmdkIndex: [],
        cmdkOpen: false,
        cmdkFocusIdx: 0,
    };

    function $(sel, root) { return (root || document).querySelector(sel); }
    function $$(sel, root) { return Array.from((root || document).querySelectorAll(sel)); }

    function toast(msg, level) {
        const host = $('#iscToastHost');
        if (!host) return;
        const t = document.createElement('div');
        t.className = 'isc-toast is-' + (level || 'info');
        t.textContent = msg;
        host.appendChild(t);
        setTimeout(() => t.remove(), 4500);
    }

    // ────────────────── Schema ingest from rendered DOM ──────────────────

    function ingestSchemaFromDom() {
        $$('[data-isc-section]').forEach(secEl => {
            const anchor = secEl.dataset.iscSection;
            state.sectionsByAnchor[anchor] = secEl;
            state.sectionStatus[anchor] = 'empty';
        });
        $$('[data-isc-field]').forEach(inp => {
            const name = inp.dataset.iscField;
            state.fieldsByName[name] = inp;
            state.values[name] = inp.value || '';
            inp.addEventListener('input', onFieldChange);
            inp.addEventListener('change', onFieldChange);
            inp.addEventListener('blur', () => persistDraft(false));
        });
    }

    // ────────────────── Smart defaults ──────────────────

    async function loadSmartDefaults() {
        try {
            const resp = await fetch('/api/intake/smart-defaults');
            const data = await resp.json();
            if (data.success && data.defaults) {
                state.smartDefaults = data.defaults;
                applySmartDefaults();
            }
        } catch (err) {
            console.warn('Smart defaults load failed', err);
        }
    }

    function applySmartDefaults() {
        Object.entries(state.smartDefaults).forEach(([name, value]) => {
            const inp = state.fieldsByName[name];
            if (!inp) return;
            // Apply ONLY if input is empty (no clinician input + no draft restore)
            if (inp.value && inp.value !== '' && inp.value !== 'unknown') return;
            inp.value = String(value);
            state.values[name] = String(value);
            inp.classList.add('is-autofilled');
        });
        recomputeAllSections();
    }

    // ────────────────── Field change → status recompute ──────────────────

    function onFieldChange(evt) {
        const inp = evt.target;
        const name = inp.dataset.iscField;
        const value = inp.value;
        state.values[name] = value;
        if (value && value !== '' && value !== 'unknown') {
            inp.classList.add('is-filled');
            inp.classList.remove('is-autofilled');
        } else {
            inp.classList.remove('is-filled');
        }
        recomputeAllSections();
        applyConditionalVisibility();
        debouncedClassifyAndTrail();
        scheduleAutoSave();
    }

    function recomputeAllSections() {
        let totalRequired = 0;
        let filledRequired = 0;
        Object.keys(state.sectionsByAnchor).forEach(anchor => {
            const secEl = state.sectionsByAnchor[anchor];
            const visibleFields = $$('[data-isc-field]', secEl).filter(f => !f.closest('.isc-field.is-hidden'));
            if (!visibleFields.length) {
                state.sectionStatus[anchor] = 'empty';
                return;
            }
            let secTotal = 0, secFilled = 0, reqInSec = 0, reqFilled = 0;
            visibleFields.forEach(f => {
                secTotal++;
                const v = f.value;
                const meaningful = v && v !== '' && v !== 'unknown' && v !== 'Desconocido';
                if (meaningful) secFilled++;
                if (f.dataset.iscRequired === '1') {
                    reqInSec++;
                    totalRequired++;
                    if (meaningful) { reqFilled++; filledRequired++; }
                }
            });
            let status;
            if (secFilled === 0) status = 'empty';
            else if (reqInSec > 0 && reqFilled < reqInSec) status = 'partial';
            else if (secFilled < secTotal) status = 'partial';
            else status = 'complete';
            state.sectionStatus[anchor] = status;
            updateSectionUi(anchor, secFilled, secTotal, status);
        });
        updateGlobalProgress(filledRequired, totalRequired);
    }

    function updateSectionUi(anchor, filled, total, status) {
        const secEl = state.sectionsByAnchor[anchor];
        if (!secEl) return;
        secEl.classList.remove('is-empty', 'is-partial', 'is-complete');
        secEl.classList.add('is-' + status);
        const counter = $('.isc-section-status-count', secEl);
        if (counter) counter.textContent = filled + '/' + total;
        const statusBadge = $('.isc-section-status-text', secEl);
        if (statusBadge) {
            statusBadge.textContent = ({
                empty: 'sin capturar',
                partial: 'parcial',
                complete: 'completo',
            })[status] || status;
        }
        // Nav item
        const navItem = $('.isc-nav-item[data-anchor="' + anchor + '"]');
        if (navItem) {
            navItem.classList.remove('is-empty', 'is-partial', 'is-complete');
            navItem.classList.add('is-' + status);
            const navCount = $('.isc-nav-completion', navItem);
            if (navCount) navCount.textContent = filled + '/' + total;
        }
    }

    function updateGlobalProgress(filledRequired, totalRequired) {
        const pct = totalRequired ? Math.round(100 * filledRequired / totalRequired) : 0;
        const bar = $('#iscProgressBar');
        const label = $('#iscProgressLabel');
        if (bar) bar.style.width = pct + '%';
        if (label) label.innerHTML = `<strong>${filledRequired}/${totalRequired}</strong> requeridos · ${pct}%`;
    }

    // ────────────────── Conditional visibility ──────────────────

    function applyConditionalVisibility() {
        $$('.isc-field[data-cv]').forEach(fieldEl => {
            let cv;
            try { cv = JSON.parse(fieldEl.dataset.cv); } catch (e) { return; }
            let visible = true;
            Object.entries(cv).forEach(([depName, allowed]) => {
                const depVal = state.values[depName];
                const allowedArr = Array.isArray(allowed) ? allowed : [allowed];
                if (!allowedArr.map(String).includes(String(depVal))) visible = false;
            });
            fieldEl.classList.toggle('is-hidden', !visible);
        });
    }

    // ────────────────── Live classifier + reasoning trail ──────────────────

    let classifyDebounceTimer = null;
    function debouncedClassifyAndTrail() {
        if (classifyDebounceTimer) clearTimeout(classifyDebounceTimer);
        classifyDebounceTimer = setTimeout(classifyAndShowTrail, 700);
    }

    async function classifyAndShowTrail() {
        try {
            const resp = await fetch('/api/intake/reasoning-trail', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(state.values),
            });
            const data = await resp.json();
            if (!data.success) return;
            renderGlobalClassification(data);
            renderSectionTrails(data);
        } catch (err) {
            console.warn('Reasoning trail failed', err);
        }
    }

    function renderGlobalClassification(data) {
        const el = $('#iscClassificationBadge');
        if (!el) return;
        const cls = data.current_classification || {};
        if (cls.state) {
            el.style.display = 'inline-flex';
            el.innerHTML = `<strong>Clasificación actual:</strong> <code>${cls.state}</code>`;
            if (cls.confidence) el.innerHTML += ` <small>(${(cls.confidence*100).toFixed(0)}%)</small>`;
        } else {
            el.style.display = 'inline-flex';
            el.innerHTML = `<em style="color:var(--isc-text-muted)">Sin clasificación aún · faltan ${data.missing_blocking_count || 0} campos blocking</em>`;
        }
    }

    function renderSectionTrails(data) {
        // Show alternative_paths inline under the section that contains the missing fields
        $$('.isc-reasoning-trail').forEach(el => { el.innerHTML = ''; el.classList.remove('is-visible'); });
        (data.alternative_paths || []).forEach(p => {
            const triggerFields = p.trigger_fields || [];
            triggerFields.forEach(fldName => {
                const inp = state.fieldsByName[fldName];
                if (!inp) return;
                // Find the section ancestor
                const secEl = inp.closest('[data-isc-section]');
                if (!secEl) return;
                const trail = $('.isc-reasoning-trail', secEl);
                if (!trail) return;
                if (!trail.innerHTML) {
                    trail.innerHTML = `<strong>📍 Compass clínico:</strong><br>`;
                    trail.classList.add('is-visible');
                }
                if (!trail.innerHTML.includes(p.rationale)) {
                    trail.innerHTML += `<div style="margin-top:4px;">→ <strong>${p.path.replace(/_/g, ' ')}</strong>: ${p.rationale}</div>`;
                }
            });
        });
    }

    // ────────────────── Section collapse/expand + persistence ──────────────────

    function toggleSection(secEl) {
        const isOpen = secEl.dataset.open === 'true';
        secEl.dataset.open = isOpen ? 'false' : 'true';
        persistSectionStates();
    }

    function persistSectionStates() {
        const states = {};
        Object.keys(state.sectionsByAnchor).forEach(anchor => {
            states[anchor] = state.sectionsByAnchor[anchor].dataset.open === 'true';
        });
        try { localStorage.setItem(LS_SECTIONS_KEY, JSON.stringify(states)); } catch (e) { /* quota */ }
    }

    function restoreSectionStates() {
        let saved;
        try { saved = JSON.parse(localStorage.getItem(LS_SECTIONS_KEY) || '{}'); } catch (e) { saved = {}; }
        Object.entries(saved).forEach(([anchor, isOpen]) => {
            const el = state.sectionsByAnchor[anchor];
            if (el) el.dataset.open = isOpen ? 'true' : 'false';
        });
    }

    // ────────────────── Auto-save draft to localStorage ──────────────────

    let autoSaveTimer = null;
    function scheduleAutoSave() {
        if (autoSaveTimer) clearTimeout(autoSaveTimer);
        autoSaveTimer = setTimeout(() => persistDraft(true), AUTO_SAVE_INTERVAL_MS);
    }

    function persistDraft(showToast) {
        try {
            const payload = {
                values: state.values,
                savedAt: new Date().toISOString(),
            };
            localStorage.setItem(LS_DRAFT_KEY, JSON.stringify(payload));
            state.lastSavedAt = payload.savedAt;
            updateFooterStatus();
            if (showToast) toast('Draft guardado en este navegador ✓', 'success');
        } catch (e) {
            toast('No se pudo guardar el draft (quota o privado)', 'warn');
        }
    }

    function restoreDraft() {
        let saved;
        try { saved = JSON.parse(localStorage.getItem(LS_DRAFT_KEY) || 'null'); } catch (e) { return false; }
        if (!saved || !saved.values) return false;
        Object.entries(saved.values).forEach(([name, value]) => {
            const inp = state.fieldsByName[name];
            if (inp && value !== '' && value !== undefined) {
                inp.value = value;
                state.values[name] = value;
                if (value !== 'unknown' && value !== 'Desconocido') {
                    inp.classList.add('is-filled');
                }
            }
        });
        state.lastSavedAt = saved.savedAt;
        return true;
    }

    function clearDraft() {
        try { localStorage.removeItem(LS_DRAFT_KEY); } catch (e) { /* ignore */ }
        toast('Draft eliminado', 'info');
    }

    function updateFooterStatus() {
        const el = $('#iscFooterStatus');
        if (!el) return;
        if (state.lastSavedAt) {
            const d = new Date(state.lastSavedAt);
            el.innerHTML = `Draft guardado · ${d.toLocaleTimeString()}`;
        } else {
            el.innerHTML = 'Sin draft guardado aún';
        }
    }

    // ────────────────── Voice per section (mini-mic) ──────────────────

    function wireSectionMics() {
        $$('.isc-mini-mic').forEach(btn => {
            btn.addEventListener('click', async () => {
                const secEl = btn.closest('[data-isc-section]');
                if (!secEl) return;
                await runVoiceCaptureForSection(secEl, btn);
            });
        });
        const composite = $('#iscVoiceCompositeMic');
        if (composite) {
            composite.addEventListener('click', () => runCompositeVoice(composite));
        }
    }

    async function runVoiceCaptureForSection(secEl, btn) {
        // Determine which extractors are relevant by inspecting field names
        const fieldNames = $$('[data-isc-field]', secEl).map(f => f.dataset.iscField);
        const extractors = [];
        if (fieldNames.includes('ecog_score')) extractors.push('ecog');
        if (fieldNames.some(n => n.startsWith('castrate') || n.startsWith('testosterone'))) extractors.push('castration');
        if (fieldNames.includes('hrr_status') || fieldNames.includes('hrr_gene')) extractors.push('hrr');
        if (fieldNames.some(n => n.startsWith('psma_'))) extractors.push('psma_pet');
        if (!extractors.length) {
            toast('Esta sección no tiene extractores de voz configurados.', 'info');
            return;
        }
        await captureAudioAndExtract(btn, extractors);
    }

    async function runCompositeVoice(btn) {
        await captureAudioAndExtract(btn, ['ecog', 'castration', 'hrr', 'psma_pet']);
    }

    async function captureAudioAndExtract(btn, extractors) {
        if (btn.dataset.recording === 'true') {
            // stop
            window._iscCurrentRecorder?.stop();
            return;
        }
        if (!navigator.mediaDevices) {
            toast('MediaRecorder no soportado.', 'error');
            return;
        }
        let stream;
        try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
        catch (e) { toast('Permiso micrófono denegado.', 'error'); return; }
        const chunks = [];
        let recorder;
        try { recorder = new MediaRecorder(stream, { mimeType: 'audio/webm' }); }
        catch (e) { recorder = new MediaRecorder(stream); }
        window._iscCurrentRecorder = recorder;
        recorder.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };
        recorder.onstop = async () => {
            btn.dataset.recording = 'false';
            stream.getTracks().forEach(t => t.stop());
            const blob = new Blob(chunks, { type: 'audio/webm' });
            const fills = [];
            await Promise.all(extractors.map(async (fld) => {
                const f = new FormData();
                f.append('audio', blob, `intake_${fld}.webm`);
                try {
                    const resp = await fetch(`/api/voice/quick-capture/${fld}`, { method: 'POST', body: f });
                    const data = await resp.json();
                    if (data.success) applyExtractionToFields(fld, data.extraction || {}, fills);
                } catch (e) { /* swallow individual extractor failures */ }
            }));
            if (fills.length) {
                toast(`✓ ${fills.length} campo(s) auto-completado(s): ${fills.join(', ')}`, 'success');
                recomputeAllSections();
                applyConditionalVisibility();
                debouncedClassifyAndTrail();
                scheduleAutoSave();
            } else {
                toast('⚠ No se detectaron valores extraíbles.', 'warn');
            }
        };
        recorder.start();
        btn.dataset.recording = 'true';
        toast('🔴 Grabando · habla los valores clínicos (10s máx)', 'info');
        setTimeout(() => { if (recorder.state === 'recording') recorder.stop(); }, 10000);
    }

    function applyExtractionToFields(field, ext, fills) {
        const setIfEmpty = (name, value) => {
            const inp = state.fieldsByName[name];
            if (!inp) return;
            if (inp.value && inp.value !== '' && inp.value !== 'unknown') return;
            inp.value = value;
            inp.classList.add('is-autofilled');
            state.values[name] = String(value);
            fills.push(name);
        };
        if (field === 'ecog' && ext.value !== null && ext.value !== undefined) {
            setIfEmpty('ecog_score', String(ext.value));
        }
        if (field === 'castration' && ext.status) {
            setIfEmpty('castrate_testosterone_status', ext.status);
            if (ext.testosterone_value) setIfEmpty('testosterone_value', ext.testosterone_value);
        }
        if (field === 'hrr' && ext.status) {
            setIfEmpty('hrr_status', ext.status);
            if (ext.gene) setIfEmpty('hrr_gene', ext.gene);
        }
        if (field === 'psma_pet' && ext.status) {
            setIfEmpty('psma_pet_done', '1');
            if (ext.status.startsWith('positive')) setIfEmpty('psma_positive', '1');
            else if (ext.status === 'negative') setIfEmpty('psma_positive', '0');
            if (ext.lesion_count) setIfEmpty('psma_lesion_count', ext.lesion_count);
            if (ext.suv_max_value) setIfEmpty('psma_index_lesion_suvmax', ext.suv_max_value);
        }
    }

    // ────────────────── Cmd-K quick-jump ──────────────────

    function buildCmdkIndex() {
        state.cmdkIndex = [];
        Object.entries(state.fieldsByName).forEach(([name, inp]) => {
            const label = inp.dataset.iscLabel || name;
            const sec = inp.closest('[data-isc-section]');
            const group = sec ? (sec.dataset.iscSectionName || '') : '';
            state.cmdkIndex.push({ name, label, group, element: inp });
        });
    }

    function openCmdk() {
        state.cmdkOpen = true;
        state.cmdkFocusIdx = 0;
        $('#iscCmdkOverlay').classList.add('is-open');
        const inp = $('#iscCmdkInput');
        inp.value = '';
        renderCmdkResults('');
        setTimeout(() => inp.focus(), 60);
    }

    function closeCmdk() {
        state.cmdkOpen = false;
        $('#iscCmdkOverlay').classList.remove('is-open');
    }

    function renderCmdkResults(query) {
        const q = query.toLowerCase().trim();
        const matches = state.cmdkIndex.filter(it =>
            !q || it.label.toLowerCase().includes(q) ||
                  it.name.toLowerCase().includes(q) ||
                  it.group.toLowerCase().includes(q)
        ).slice(0, 30);
        const list = $('#iscCmdkList');
        if (!matches.length) {
            list.innerHTML = '<div class="isc-cmdk-empty">Sin resultados</div>';
            return;
        }
        list.innerHTML = matches.map((it, i) =>
            `<div class="isc-cmdk-item${i === state.cmdkFocusIdx ? ' is-focused' : ''}" data-cmdk-idx="${i}">
                <span>${it.label}</span>
                <span class="isc-cmdk-item-group">${it.group}</span>
            </div>`
        ).join('');
        $$('.isc-cmdk-item').forEach(el => {
            el.addEventListener('click', () => {
                const idx = parseInt(el.dataset.cmdkIdx, 10);
                jumpToField(matches[idx]);
            });
        });
        state._cmdkMatches = matches;
    }

    function jumpToField(item) {
        if (!item) return;
        closeCmdk();
        // Ensure section open
        const sec = item.element.closest('[data-isc-section]');
        if (sec) sec.dataset.open = 'true';
        setTimeout(() => {
            item.element.scrollIntoView({ behavior: 'smooth', block: 'center' });
            item.element.focus();
        }, 80);
    }

    function wireCmdk() {
        const overlay = $('#iscCmdkOverlay');
        const input = $('#iscCmdkInput');
        if (!overlay || !input) return;
        input.addEventListener('input', () => {
            state.cmdkFocusIdx = 0;
            renderCmdkResults(input.value);
        });
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') { closeCmdk(); return; }
            if (e.key === 'ArrowDown') {
                e.preventDefault();
                state.cmdkFocusIdx = Math.min(state.cmdkFocusIdx + 1, (state._cmdkMatches?.length || 1) - 1);
                renderCmdkResults(input.value);
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                state.cmdkFocusIdx = Math.max(state.cmdkFocusIdx - 1, 0);
                renderCmdkResults(input.value);
            } else if (e.key === 'Enter') {
                e.preventDefault();
                jumpToField(state._cmdkMatches?.[state.cmdkFocusIdx]);
            }
        });
        overlay.addEventListener('click', (e) => { if (e.target === overlay) closeCmdk(); });
    }

    function wireKeyboardShortcuts() {
        document.addEventListener('keydown', (e) => {
            const isCmd = e.metaKey || e.ctrlKey;
            if (isCmd && e.key.toLowerCase() === 'k') {
                e.preventDefault();
                if (state.cmdkOpen) closeCmdk(); else openCmdk();
            }
            if (isCmd && e.key.toLowerCase() === 's') {
                e.preventDefault();
                persistDraft(true);
            }
        });
    }

    // ────────────────── Nav clicks ──────────────────

    function wireNavigator() {
        $$('.isc-nav-item').forEach(item => {
            item.addEventListener('click', (e) => {
                e.preventDefault();
                const anchor = item.dataset.anchor;
                const sec = state.sectionsByAnchor[anchor];
                if (!sec) return;
                $$('.isc-nav-item').forEach(n => n.classList.remove('is-active'));
                item.classList.add('is-active');
                sec.dataset.open = 'true';
                persistSectionStates();
                setTimeout(() => sec.scrollIntoView({ behavior: 'smooth', block: 'start' }), 60);
            });
        });
    }

    function wireSectionHeaders() {
        $$('.isc-section-header').forEach(h => {
            h.addEventListener('click', () => {
                const sec = h.closest('[data-isc-section]');
                if (sec) toggleSection(sec);
            });
        });
    }

    function wireHelpToggles() {
        $$('.isc-field-help-toggle').forEach(btn => {
            btn.addEventListener('click', () => {
                const help = btn.parentElement.parentElement.querySelector('.isc-field-help');
                if (help) help.classList.toggle('is-visible');
            });
        });
    }

    // ────────────────── Submit ──────────────────

    async function submitIntake(mode) {
        // mode = 'draft' (save server-side draft, future) or 'submit' (full register)
        if (mode === 'draft') {
            persistDraft(true);
            return;
        }
        // Submit → POST /api/register_patient (existing endpoint)
        const payload = Object.assign({}, state.values);
        // Required: full_name + nss
        if (!payload.full_name || !payload.nss) {
            toast('Faltan campos obligatorios: nombre + NSS', 'error');
            return;
        }
        const submitBtn = $('#iscSubmitBtn');
        submitBtn.disabled = true;
        submitBtn.textContent = 'Registrando...';
        try {
            const resp = await fetch('/api/register_patient', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            const data = await resp.json();
            if (data.success || data.patient_id) {
                toast('✓ Paciente registrado · ' + (data.message || ''), 'success');
                clearDraft();
                setTimeout(() => {
                    window.location.href = '/patient_profile/' + encodeURIComponent(payload.nss);
                }, 1200);
            } else {
                toast('Error: ' + (data.error || data.message || 'unknown'), 'error');
                submitBtn.disabled = false;
                submitBtn.textContent = 'Registrar paciente';
            }
        } catch (err) {
            toast('Error de red: ' + err.message, 'error');
            submitBtn.disabled = false;
            submitBtn.textContent = 'Registrar paciente';
        }
    }

    function wireFooter() {
        const saveBtn = $('#iscSaveDraftBtn');
        const submitBtn = $('#iscSubmitBtn');
        const clearBtn = $('#iscClearDraftBtn');
        if (saveBtn) saveBtn.addEventListener('click', () => submitIntake('draft'));
        if (submitBtn) submitBtn.addEventListener('click', () => submitIntake('submit'));
        if (clearBtn) clearBtn.addEventListener('click', () => {
            if (confirm('¿Eliminar todo el draft y reiniciar el formulario?')) {
                clearDraft();
                location.reload();
            }
        });
    }

    // ────────────────── Init ──────────────────

    function init() {
        ingestSchemaFromDom();
        const restored = restoreDraft();
        if (restored) toast('Draft anterior restaurado · ' + state.lastSavedAt, 'info');
        restoreSectionStates();
        applyConditionalVisibility();
        recomputeAllSections();
        wireNavigator();
        wireSectionHeaders();
        wireHelpToggles();
        wireSectionMics();
        wireCmdk();
        wireKeyboardShortcuts();
        wireFooter();
        buildCmdkIndex();
        if (!restored) loadSmartDefaults();
        updateFooterStatus();
        // First classification pass after load
        setTimeout(classifyAndShowTrail, 600);
        // Open first 2 critical sections by default
        const headers = Object.values(state.sectionsByAnchor).slice(0, 2);
        headers.forEach(sec => { if (!sec.dataset.open) sec.dataset.open = 'true'; });
        recomputeAllSections();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
