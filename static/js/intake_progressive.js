/* Faubot LXCIII (plan LXXXVII) — Progressive Disclosure intake JS.
 *
 * Controla:
 * - Step 1: render quick classifier fields + collect input
 * - Classify: POST /api/intake/classify → render Step 2 dynamically
 * - Step 2: always_visible fields + 3 expandable accordion groups
 * - Live updates: cada input update → re-classify → update preview rail
 * - Step 3: persist via /api/register_patient + redirect to profile
 *
 * Skills: frontend-patterns (vanilla JS state management),
 * api-design (REST integration), ui-ux-pro-max (accordion UX).
 */

(function () {
    "use strict";

    // ──────────────────────────────────────────────────────────────────
    // State management
    // ──────────────────────────────────────────────────────────────────
    const state = {
        step: 1,
        captured: {},      // All field values captured so far
        diseaseState: null,
        stageCapture: null,
        debounceTimer: null,
    };

    // Quick classifier default fields (for Step 1, before classification)
    // Faubot LXCVI.F — Expanded de 8 a 12 fields incluyendo demographics críticos:
    // nss + full_name (required en POST), preferred_language + country (audit + Cortana)
    const QUICK_CLASSIFIER_FIELDS = [
        // ─── Identity (LXCVI.F.1: required + audit trail) ───
        {
            name: "nss", label: "NSS / Identificador único", type: "text",
            placeholder: "ej. 12345678901", required: true,
        },
        {
            name: "full_name", label: "Nombre completo", type: "text",
            placeholder: "Apellidos + Nombres", required: true,
        },
        {
            name: "preferred_language", label: "Idioma preferido", type: "select",
            options: [
                {value: "es", label: "Español"},
                {value: "en", label: "Inglés"},
                {value: "otra", label: "Otra"},
            ],
            required: false,
        },
        {
            name: "country", label: "País", type: "select",
            options: [
                {value: "MX", label: "México"},
                {value: "US", label: "USA"},
                {value: "ES", label: "España"},
                {value: "otra", label: "Otro"},
            ],
            required: false,
        },
        // ─── Clinical (original 8 fields) ───
        {
            name: "psa_value", label: "PSA actual (ng/mL)", type: "number",
            placeholder: "ej. 12.5", required: true,
        },
        {
            name: "age", label: "Edad (años)", type: "number",
            placeholder: "ej. 68", required: true,
        },
        {
            name: "gleason_score", label: "Gleason score (suma)", type: "number",
            placeholder: "6-10", required: true, min: 6, max: 10,
        },
        {
            name: "clinical_t_stage", label: "Estadio T", type: "select",
            options: [
                {value: "", label: "Seleccionar…"},
                {value: "T1a", label: "T1a"}, {value: "T1b", label: "T1b"}, {value: "T1c", label: "T1c"},
                {value: "T2a", label: "T2a"}, {value: "T2b", label: "T2b"}, {value: "T2c", label: "T2c"},
                {value: "T3a", label: "T3a"}, {value: "T3b", label: "T3b"},
                {value: "T4", label: "T4"},
            ],
            required: true,
        },
        {
            name: "metastasis_site", label: "Sitio metástasis", type: "select",
            options: [
                {value: "", label: "Seleccionar…"},
                {value: "M0", label: "M0 (sin metástasis)"},
                {value: "M1a", label: "M1a (nodos no regionales)"},
                {value: "M1b", label: "M1b (óseas)"},
                {value: "M1c", label: "M1c (visceral)"},
                {value: "Mx", label: "Mx (desconocido)"},
            ],
            required: true,
        },
        {
            name: "ecog_score", label: "ECOG (0-4)", type: "select",
            options: [
                {value: "", label: "Seleccionar…"},
                {value: "0", label: "0 (asintomático)"},
                {value: "1", label: "1 (síntomas leves)"},
                {value: "2", label: "2 (cama <50% día)"},
                {value: "3", label: "3 (cama >50% día)"},
                {value: "4", label: "4 (postrado)"},
            ],
            required: true,
        },
        {
            name: "prior_prostatectomy", label: "RP previa", type: "select",
            options: [
                {value: "0", label: "No"}, {value: "1", label: "Sí"},
            ],
        },
        {
            name: "prior_radiation", label: "RT primaria previa", type: "select",
            options: [
                {value: "0", label: "No"}, {value: "1", label: "Sí"},
            ],
        },
    ];

    // ──────────────────────────────────────────────────────────────────
    // Field rendering helpers
    // ──────────────────────────────────────────────────────────────────

    function renderField(field) {
        const wrapper = document.createElement("div");
        wrapper.className = "pm2-field";

        const label = document.createElement("label");
        label.className = "pm2-field-label";
        label.htmlFor = `field-${field.name}`;
        label.textContent = field.label || field.name;
        if (field.required) {
            const star = document.createElement("span");
            star.className = "pm2-field-required-marker";
            star.textContent = " *";
            star.setAttribute("aria-label", "requerido");
            label.appendChild(star);
        }
        wrapper.appendChild(label);

        const fieldType = (field.type || "text").toLowerCase();
        let input;
        if (fieldType === "select") {
            input = document.createElement("select");
            input.className = "pm2-field-select";
            const opts = field.options || [];
            opts.forEach((opt) => {
                const optEl = document.createElement("option");
                if (typeof opt === "object" && opt !== null) {
                    optEl.value = opt.value;
                    optEl.textContent = opt.label || opt.value;
                } else {
                    optEl.value = opt;
                    optEl.textContent = opt;
                }
                input.appendChild(optEl);
            });
        } else {
            input = document.createElement("input");
            input.type = fieldType === "number" ? "number" : (fieldType === "date" ? "date" : "text");
            input.className = "pm2-field-input";
            if (field.placeholder) input.placeholder = field.placeholder;
            if (fieldType === "number") {
                input.step = "any";
                if (field.min !== undefined) input.min = field.min;
                if (field.max !== undefined) input.max = field.max;
            }
        }
        input.id = `field-${field.name}`;
        input.name = field.name;
        input.dataset.fieldName = field.name;
        if (field.required) input.required = true;

        // Restore value if already captured
        if (state.captured[field.name] !== undefined && state.captured[field.name] !== null) {
            input.value = state.captured[field.name];
        }

        // Live update on change
        input.addEventListener("input", onFieldInput);
        input.addEventListener("change", onFieldInput);

        wrapper.appendChild(input);

        if (field.help) {
            const help = document.createElement("p");
            help.className = "pm2-field-help";
            help.textContent = field.help;
            wrapper.appendChild(help);
        }

        return wrapper;
    }

    function renderFieldsGrid(fields, containerId) {
        const container = document.getElementById(containerId);
        if (!container) return;
        container.innerHTML = "";
        fields.forEach((field) => container.appendChild(renderField(field)));
    }

    function renderExpandableGroup(group) {
        const details = document.createElement("details");
        details.className = "pm2-disclosure-group";
        details.dataset.groupKey = group.key;

        const summary = document.createElement("summary");
        summary.className = "pm2-disclosure-summary";

        const labelWrap = document.createElement("div");
        labelWrap.className = "pm2-disclosure-label-wrap";

        const icon = document.createElement("span");
        icon.className = "pm2-disclosure-icon";
        icon.textContent = group.icon || "📋";

        const labelBlock = document.createElement("div");
        const labelEl = document.createElement("div");
        labelEl.className = "pm2-disclosure-label";
        labelEl.textContent = group.label;
        labelBlock.appendChild(labelEl);
        if (group.description) {
            const desc = document.createElement("div");
            desc.className = "pm2-disclosure-description";
            desc.textContent = group.description;
            labelBlock.appendChild(desc);
        }

        labelWrap.appendChild(icon);
        labelWrap.appendChild(labelBlock);
        summary.appendChild(labelWrap);

        const rightSide = document.createElement("div");
        rightSide.style.cssText = "display:flex; align-items:center; gap:0.625rem;";

        const badge = document.createElement("span");
        badge.className = "pm2-disclosure-badge";
        badge.textContent = `${group.field_count || 0} campos`;
        rightSide.appendChild(badge);

        const chevron = document.createElement("svg");
        chevron.setAttribute("width", "16");
        chevron.setAttribute("height", "16");
        chevron.setAttribute("fill", "none");
        chevron.setAttribute("stroke", "currentColor");
        chevron.setAttribute("viewBox", "0 0 24 24");
        chevron.classList.add("pm2-disclosure-chevron");
        chevron.innerHTML = '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>';
        rightSide.appendChild(chevron);

        summary.appendChild(rightSide);
        details.appendChild(summary);

        const body = document.createElement("div");
        body.className = "pm2-disclosure-body";

        // Lazy-render fields when accordion is opened (perf optimization)
        details.addEventListener("toggle", () => {
            if (details.open && body.children.length === 0) {
                const fieldsGrid = document.createElement("div");
                fieldsGrid.className = "pm2-fields-grid";
                fieldsGrid.style.marginTop = "1.25rem";
                (group.fields || []).forEach((field) => {
                    fieldsGrid.appendChild(renderField(field));
                });
                body.appendChild(fieldsGrid);
            }
        });

        details.appendChild(body);
        return details;
    }

    // ──────────────────────────────────────────────────────────────────
    // Event handlers
    // ──────────────────────────────────────────────────────────────────

    function onFieldInput(event) {
        const target = event.target;
        const name = target.dataset.fieldName || target.name;
        if (!name) return;

        // Update captured state
        const value = target.type === "number" ? parseFloat(target.value) || 0 : target.value;
        if (target.value === "" || target.value === null) {
            delete state.captured[name];
        } else {
            state.captured[name] = value;
        }

        // Debounced re-classify (300ms)
        if (state.debounceTimer) clearTimeout(state.debounceTimer);
        state.debounceTimer = setTimeout(updateLivePreview, 300);
    }

    async function updateLivePreview() {
        // Only classify if we have minimum critical fields
        const required = ["psa_value", "ecog_score"];
        const hasMinimum = required.every((f) => state.captured[f] !== undefined);
        if (!hasMinimum) return;

        try {
            const response = await fetch("/api/intake/classify", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify(state.captured),
            });
            if (!response.ok) return;
            const data = await response.json();
            if (data.success) {
                state.diseaseState = data.disease_state;
                state.stageCapture = data.stage_capture;
                renderRailPreview(data);
            }
        } catch (err) {
            console.warn("Live classify failed:", err);
        }
    }

    function renderRailPreview(data) {
        const sc = data.stage_capture || {};

        // Disease state badge
        const stateEl = document.getElementById("railDiseaseState");
        if (stateEl) {
            stateEl.innerHTML = `
                <div class="pm2-rail-state-badge">${escapeHtml(sc.stage_label || data.disease_state)}</div>
                <p style="color:#94a3b8; font-size:0.75rem; margin:0.25rem 0 0;">${escapeHtml(data.classification_reason || "")}</p>
            `;
        }

        // Live classification
        const lcEl = document.getElementById("railLiveClassification");
        if (lcEl) {
            const lc = sc.live_classification || {};
            const items = Object.entries(lc).map(([k, v]) => `
                <div class="pm2-rail-classification-item">
                    <span class="pm2-rail-classification-key">${escapeHtml(k)}</span>
                    <span class="pm2-rail-classification-value">${escapeHtml(String(v))}</span>
                </div>
            `).join("");
            lcEl.innerHTML = items || `<p style="color:#64748b; font-size:0.8125rem;">Pendiente más datos…</p>`;
        }

        // Recommendation
        const recEl = document.getElementById("railRecommendation");
        if (recEl) {
            const rec = sc.recommendation_preview || {};
            if (rec.primary_action) {
                recEl.innerHTML = `
                    <div class="pm2-rail-recommendation-card">
                        <p class="pm2-rail-recommendation-action">${escapeHtml(rec.primary_action)}</p>
                        <p class="pm2-rail-recommendation-rationale">${escapeHtml(rec.rationale || "")}</p>
                    </div>
                `;
            } else {
                recEl.innerHTML = `<p style="color:#64748b; font-size:0.8125rem;">La acción clínica sugerida aparecerá tras clasificar el estadio.</p>`;
            }
        }

        // Summary
        const sumEl = document.getElementById("railSummary");
        if (sumEl) {
            const s = sc.summary || {};
            sumEl.innerHTML = `
                <p style="color:#cbd5e1; font-size:0.8125rem; margin:0;">
                    <strong>${s.total_always_visible || 0}</strong> visibles ·
                    <strong>${s.total_refiners || 0}</strong> refinadores ·
                    <strong>${s.total_monitoring || 0}</strong> monitoreo
                </p>
            `;
        }
    }

    async function onClassifyClick() {
        // Validate required fields filled
        const requiredFields = QUICK_CLASSIFIER_FIELDS.filter((f) => f.required);
        const missing = requiredFields.filter((f) => !state.captured[f.name]);
        if (missing.length > 0) {
            alert(`Faltan campos requeridos: ${missing.map((f) => f.label).join(", ")}`);
            return;
        }

        // Trigger classify and advance to step 2
        await updateLivePreview();
        if (state.diseaseState && state.stageCapture) {
            advanceToStep2();
        } else {
            alert("No se pudo clasificar el estadio. Verifique los datos ingresados.");
        }
    }

    function advanceToStep2() {
        // Hide step 1, show step 2
        document.getElementById("step1Container").hidden = true;
        document.getElementById("step2Container").hidden = false;

        // Update step indicators
        document.querySelectorAll(".pm2-progressive-step").forEach((el) => {
            const num = parseInt(el.dataset.step);
            el.classList.remove("is-active");
            if (num === 2) el.classList.add("is-active");
            else if (num === 1) el.classList.add("is-completed");
        });

        const sc = state.stageCapture;

        // Render always_visible for the resolved state
        const titleEl = document.getElementById("stateAlwaysVisibleTitle");
        if (titleEl) titleEl.textContent = `Refinadores críticos: ${sc.stage_label}`;

        const descEl = document.getElementById("stateAlwaysVisibleDescription");
        if (descEl) descEl.textContent = `Datos esenciales para el estadio resuelto. Todos requeridos para emitir recomendación.`;

        renderFieldsGrid(sc.always_visible || [], "stateAlwaysVisibleFields");

        // Render expandable groups
        const groupsContainer = document.getElementById("expandableGroupsContainer");
        if (groupsContainer) {
            groupsContainer.innerHTML = "";
            (sc.expandable_groups || []).forEach((group) => {
                if (group.field_count > 0) {
                    groupsContainer.appendChild(renderExpandableGroup(group));
                }
            });
        }

        // Show next-step hint
        const hintEl = document.getElementById("nextStepHint");
        const hintTextEl = document.getElementById("nextStepText");
        if (hintEl && hintTextEl && sc.next_step_hint) {
            hintTextEl.textContent = sc.next_step_hint;
            hintEl.hidden = false;
        }

        // Scroll to top of step 2
        document.getElementById("step2Container").scrollIntoView({behavior: "smooth", block: "start"});
    }

    function onBackToStep1() {
        document.getElementById("step1Container").hidden = false;
        document.getElementById("step2Container").hidden = true;
        document.querySelectorAll(".pm2-progressive-step").forEach((el) => {
            const num = parseInt(el.dataset.step);
            el.classList.remove("is-active", "is-completed");
            if (num === 1) el.classList.add("is-active");
        });
    }

    async function onConfirmAndPersist() {
        // Build final payload from all captured fields
        const payload = {
            ...state.captured,
            disease_state: state.diseaseState,
            audit_source: "intake_progressive_v2_LXCIII",
        };

        try {
            const response = await fetch("/api/register_patient", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify(payload),
            });
            const data = await response.json();
            if (data.success) {
                const nss = data.nss || data.patient_nss || payload.nss || "";
                if (nss) {
                    window.location.href = `/patient_profile/${nss}`;
                } else {
                    alert("Paciente registrado. Recargue la página para ver el perfil.");
                }
            } else {
                alert(`Error al registrar: ${data.error || "desconocido"}`);
            }
        } catch (err) {
            alert(`Error de red: ${err.message}`);
        }
    }

    // ──────────────────────────────────────────────────────────────────
    // Initialization
    // ──────────────────────────────────────────────────────────────────

    function escapeHtml(str) {
        if (str === null || str === undefined) return "";
        return String(str)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    function init() {
        // Render Step 1 fields
        renderFieldsGrid(QUICK_CLASSIFIER_FIELDS, "quickClassifierFields");

        // Wire buttons
        const classifyBtn = document.getElementById("btnClassify");
        if (classifyBtn) classifyBtn.addEventListener("click", onClassifyClick);

        const backBtn = document.getElementById("btnBackToStep1");
        if (backBtn) backBtn.addEventListener("click", onBackToStep1);

        const confirmBtn = document.getElementById("btnConfirmAndPersist");
        if (confirmBtn) confirmBtn.addEventListener("click", onConfirmAndPersist);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }

    // Expose for testing
    window.IntakeProgressive = {
        state,
        QUICK_CLASSIFIER_FIELDS,
        renderField,
        renderExpandableGroup,
        updateLivePreview,
    };
})();
