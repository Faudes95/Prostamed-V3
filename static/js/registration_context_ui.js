(function () {
    function escapeHtml(value) {
        return String(value ?? "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    function formatRegistrationValue(value) {
        if (value === null || value === undefined || value === "") {
            return "No documentado";
        }
        return escapeHtml(value);
    }

    function parseHistoryValue(value) {
        if (!value) {
            return [];
        }
        if (Array.isArray(value)) {
            return value;
        }
        try {
            const parsed = JSON.parse(value);
            return Array.isArray(parsed) ? parsed : [];
        } catch (_error) {
            return [];
        }
    }

    const LINE_CONTEXT_OPTIONS = [
        { value: "", label: "Sin línea documentada" },
        { value: "mHSPC_initial", label: "mHSPC inicial" },
        { value: "mHSPC_post_docetaxel", label: "mHSPC post-docetaxel" },
        { value: "m0_CRPC_first_line", label: "m0 CRPC primera línea" },
        { value: "mCRPC_first_line", label: "mCRPC primera línea" },
        { value: "mCRPC_post_ARPI_pre_taxane", label: "mCRPC post-ARPI pre-taxano" },
        { value: "mCRPC_post_taxane", label: "mCRPC post-taxano" },
        { value: "mCRPC_post_PARP", label: "mCRPC post-PARP" },
        { value: "mCRPC_post_Lu177", label: "mCRPC post-Lu177" },
        { value: "later_line", label: "Líneas posteriores" },
    ];

    function normalizeClinicalState(value) {
        return String(value || "").trim().toLowerCase();
    }

    function lineContextOptionsForState(clinicalState, selectedValue = "") {
        const state = normalizeClinicalState(clinicalState);
        let allowedValues;
        if (state.includes("m1_crpc") || state.includes("mcrpc")) {
            allowedValues = LINE_CONTEXT_OPTIONS.map((option) => option.value);
        } else if (state.includes("m0_crpc")) {
            allowedValues = ["", "m0_CRPC_first_line"];
        } else if (state.includes("mcspc") || state.includes("mhspc")) {
            allowedValues = ["", "mHSPC_initial", "mHSPC_post_docetaxel"];
        } else {
            allowedValues = [""];
        }
        const options = LINE_CONTEXT_OPTIONS.filter((option) => allowedValues.includes(option.value));
        const hasSelected = options.some((option) => option.value === selectedValue);
        if (selectedValue && !hasSelected) {
            const legacy = LINE_CONTEXT_OPTIONS.find((option) => option.value === selectedValue);
            options.push(legacy || { value: selectedValue, label: selectedValue });
        }
        return options;
    }

    function renderLineContextOptions(selectedValue = "", clinicalState = "") {
        return lineContextOptionsForState(clinicalState, selectedValue)
            .map((option) => `<option value="${escapeHtml(option.value)}" ${option.value === selectedValue ? "selected" : ""}>${escapeHtml(option.label)}</option>`)
            .join("");
    }

    function renderScaleContext(field) {
        const parts = [];
        if (field.scale_descriptor) {
            parts.push(`<span class="block text-xs text-cyan-200">${escapeHtml(field.scale_descriptor)}</span>`);
        }
        if (field.score_interpretation) {
            parts.push(`<span class="block rounded-2xl border border-cyan-500/20 bg-cyan-500/5 px-3 py-2 text-xs text-cyan-100">${escapeHtml(field.score_interpretation)}</span>`);
        }
        return parts.join("");
    }

    function renderReferenceRange(field) {
        if (!field.reference_range_label) {
            return "";
        }
        return `<span class="block rounded-2xl border border-emerald-500/20 bg-emerald-500/5 px-3 py-2 text-xs text-emerald-200">${escapeHtml(field.reference_range_label)}</span>`;
    }

    function evaluateConditionalVisibility(root, conditions = {}) {
        if (!conditions || typeof conditions !== "object") {
            return true;
        }
        if (Array.isArray(conditions.__any__)) {
            return conditions.__any__.some((branch) => evaluateConditionalVisibility(root, branch));
        }
        if (Array.isArray(conditions.__all__)) {
            return conditions.__all__.every((branch) => evaluateConditionalVisibility(root, branch));
        }
        return Object.entries(conditions || {}).every(([fieldName, accepted]) => {
            const fieldNodes = Array.from(root.querySelectorAll(`[name="${fieldName}"]`));
            if (!fieldNodes.length) {
                return false;
            }
            const acceptedValues = Array.isArray(accepted) ? accepted.map(String) : [String(accepted)];
            const values = fieldNodes.flatMap((node) => {
                if (!(node instanceof HTMLInputElement || node instanceof HTMLSelectElement || node instanceof HTMLTextAreaElement)) {
                    return [];
                }
                if (node.type === "checkbox") {
                    return [node.checked ? "1" : "0"];
                }
                return [String(node.value ?? "")];
            });
            return values.some((value) => acceptedValues.includes(value));
        });
    }

    function setDisabledState(wrapper, disabled) {
        wrapper.querySelectorAll("input, select, textarea, button").forEach((node) => {
            if (!(node instanceof HTMLInputElement || node instanceof HTMLSelectElement || node instanceof HTMLTextAreaElement || node instanceof HTMLButtonElement)) {
                return;
            }
            if (node.closest("[data-registration-metastatic-widget]") || node.closest("[data-registration-gleason-widget]")) {
                return;
            }
            node.disabled = disabled;
        });
    }

    function updateConditionalVisibility(root = document) {
        Array.from(root.querySelectorAll("[data-conditions]")).forEach((wrapper) => {
            let conditions = {};
            try {
                conditions = JSON.parse(wrapper.dataset.conditions || "{}");
            } catch (_error) {
                conditions = {};
            }
            const visible = evaluateConditionalVisibility(root, conditions);
            wrapper.classList.toggle("hidden", !visible);
            setDisabledState(wrapper, !visible);
        });
    }

    function renderPsaHistoryRows(rows, clinicalState = "") {
        const initialRows = rows.length ? rows : [{}];
        return initialRows.map((row) => `
            <div data-psa-history-row class="grid gap-3 rounded-2xl border border-slate-800 bg-slate-950/50 p-4 md:grid-cols-2 xl:grid-cols-3">
                <label class="text-sm">
                    <span class="mb-1 block text-slate-300">Fecha de muestra</span>
                    <input type="date" data-history-key="sample_date" value="${escapeHtml(row.sample_date || "")}" class="pn-input w-full px-3 py-2">
                </label>
                <label class="text-sm">
                    <span class="mb-1 block text-slate-300">APE / PSA (ng/mL)</span>
                    <input type="number" step="0.01" min="0" data-history-key="psa_value" value="${escapeHtml(row.psa_value || "")}" class="pn-input w-full px-3 py-2">
                </label>
                <label class="text-sm">
                    <span class="mb-1 block text-slate-300">Tipo de ensayo</span>
                    <select data-history-key="assay_type" class="pn-input w-full px-3 py-2">
                        <option value="estándar" ${row.assay_type === "estándar" ? "selected" : ""}>Estándar</option>
                        <option value="ultrasensible" ${row.assay_type === "ultrasensible" ? "selected" : ""}>Ultrasensible</option>
                        <option value="desconocido" ${!row.assay_type || row.assay_type === "desconocido" ? "selected" : ""}>Desconocido</option>
                    </select>
                </label>
                <label class="text-sm">
                    <span class="mb-1 block text-slate-300">Contexto</span>
                    <select data-history-key="context" class="pn-input w-full px-3 py-2">
                        <option value="pretratamiento" ${row.context === "pretratamiento" ? "selected" : ""}>Pretratamiento</option>
                        <option value="postlocal" ${row.context === "postlocal" ? "selected" : ""}>Postlocal</option>
                        <option value="en adt" ${row.context === "en adt" ? "selected" : ""}>En ADT</option>
                        <option value="otro" ${!row.context || row.context === "otro" ? "selected" : ""}>Otro</option>
                    </select>
                </label>
                <label class="text-sm">
                    <span class="mb-1 block text-slate-300">Línea terapéutica</span>
                    <input type="number" min="1" step="1" data-history-key="line_of_therapy_number" value="${escapeHtml(row.line_of_therapy_number || "")}" class="pn-input w-full px-3 py-2" placeholder="1, 2, 3...">
                </label>
                <div class="flex items-end justify-end">
                    <button type="button" class="pn-btn pn-btn-secondary" data-remove-psa-row>Quitar</button>
                </div>
                <label class="text-sm lg:col-span-2">
                    <span class="mb-1 block text-slate-300">Contexto de línea (opcional)</span>
                    <select data-history-key="line_of_therapy_context" class="pn-input w-full px-3 py-2">
                        ${renderLineContextOptions(row.line_of_therapy_context || "", clinicalState)}
                    </select>
                </label>
                <label class="text-sm lg:col-span-3">
                    <span class="mb-1 block text-slate-300">Fuente documental (opcional)</span>
                    <input type="text" data-history-key="source" value="${escapeHtml(row.source || "")}" class="pn-input w-full px-3 py-2" placeholder="Laboratorio externo, expediente, nota clínica, etc.">
                </label>
            </div>
        `).join("");
    }

    function renderTestosteroneHistoryRows(rows, clinicalState = "") {
        const initialRows = rows.length ? rows : [{}];
        return initialRows.map((row) => `
            <div data-testosterone-history-row class="grid gap-3 rounded-2xl border border-slate-800 bg-slate-950/50 p-4 md:grid-cols-2 xl:grid-cols-3">
                <label class="text-sm">
                    <span class="mb-1 block text-slate-300">Fecha de muestra</span>
                    <input type="date" data-history-key="sample_date" value="${escapeHtml(row.sample_date || "")}" class="pn-input w-full px-3 py-2">
                </label>
                <label class="text-sm">
                    <span class="mb-1 block text-slate-300">Testosterona</span>
                    <input type="number" step="0.01" min="0" data-history-key="testosterone_value" value="${escapeHtml(row.testosterone_value || row.value || "")}" class="pn-input w-full px-3 py-2">
                </label>
                <label class="text-sm">
                    <span class="mb-1 block text-slate-300">Unidad</span>
                    <select data-history-key="unit" class="pn-input w-full px-3 py-2">
                        <option value="ng/dL" ${!row.unit || row.unit === "ng/dL" ? "selected" : ""}>ng/dL</option>
                        <option value="nmol/L" ${row.unit === "nmol/L" ? "selected" : ""}>nmol/L</option>
                    </select>
                </label>
                <label class="text-sm">
                    <span class="mb-1 block text-slate-300">Contexto</span>
                    <select data-history-key="context" class="pn-input w-full px-3 py-2">
                        <option value="pretratamiento" ${row.context === "pretratamiento" ? "selected" : ""}>Pretratamiento</option>
                        <option value="en adt" ${row.context === "en adt" ? "selected" : ""}>En ADT</option>
                        <option value="postlocal" ${row.context === "postlocal" ? "selected" : ""}>Postlocal</option>
                        <option value="otro" ${!row.context || row.context === "otro" ? "selected" : ""}>Otro</option>
                    </select>
                </label>
                <label class="text-sm">
                    <span class="mb-1 block text-slate-300">Línea terapéutica</span>
                    <input type="number" min="1" step="1" data-history-key="line_of_therapy_number" value="${escapeHtml(row.line_of_therapy_number || "")}" class="pn-input w-full px-3 py-2" placeholder="1, 2, 3...">
                </label>
                <div class="flex items-end justify-end">
                    <button type="button" class="pn-btn pn-btn-secondary" data-remove-testosterone-row>Quitar</button>
                </div>
                <label class="text-sm lg:col-span-2">
                    <span class="mb-1 block text-slate-300">Contexto de línea (opcional)</span>
                    <select data-history-key="line_of_therapy_context" class="pn-input w-full px-3 py-2">
                        ${renderLineContextOptions(row.line_of_therapy_context || "", clinicalState)}
                    </select>
                </label>
                <label class="text-sm lg:col-span-3">
                    <span class="mb-1 block text-slate-300">Fuente documental (opcional)</span>
                    <input type="text" data-history-key="source" value="${escapeHtml(row.source || "")}" class="pn-input w-full px-3 py-2" placeholder="Laboratorio externo, expediente, nota clínica, etc.">
                </label>
            </div>
        `).join("");
    }

    function syncPsaHistoryField(scope) {
        scope.querySelectorAll("[data-psa-history-field]").forEach((wrapper) => {
            const hidden = wrapper.querySelector("[data-psa-history-input]");
            if (!hidden) {
                return;
            }
            const rows = Array.from(wrapper.querySelectorAll("[data-psa-history-row]")).map((row) => ({
                sample_date: row.querySelector('[data-history-key="sample_date"]')?.value || "",
                psa_value: row.querySelector('[data-history-key="psa_value"]')?.value || "",
                assay_type: row.querySelector('[data-history-key="assay_type"]')?.value || "desconocido",
                context: row.querySelector('[data-history-key="context"]')?.value || "otro",
                line_of_therapy_number: row.querySelector('[data-history-key="line_of_therapy_number"]')?.value || "",
                line_of_therapy_context: row.querySelector('[data-history-key="line_of_therapy_context"]')?.value || "",
                source: row.querySelector('[data-history-key="source"]')?.value || "",
            })).filter((row) => row.sample_date || row.psa_value || row.source || row.line_of_therapy_number || row.line_of_therapy_context);
            hidden.value = JSON.stringify(rows);
            const summary = wrapper.querySelector("[data-psa-history-summary]");
            if (summary) {
                summary.textContent = rows.length
                    ? `${rows.length} medición(es) listas para guardarse en la serie longitudinal.`
                    : "Sin mediciones adicionales; el basal seguirá siendo el punto canónico principal.";
            }
        });
    }

    function syncTestosteroneHistoryField(scope) {
        scope.querySelectorAll("[data-testosterone-history-field]").forEach((wrapper) => {
            const hidden = wrapper.querySelector("[data-testosterone-history-input]");
            if (!hidden) {
                return;
            }
            const rows = Array.from(wrapper.querySelectorAll("[data-testosterone-history-row]")).map((row) => ({
                sample_date: row.querySelector('[data-history-key="sample_date"]')?.value || "",
                testosterone_value: row.querySelector('[data-history-key="testosterone_value"]')?.value || "",
                unit: row.querySelector('[data-history-key="unit"]')?.value || "ng/dL",
                context: row.querySelector('[data-history-key="context"]')?.value || "otro",
                line_of_therapy_number: row.querySelector('[data-history-key="line_of_therapy_number"]')?.value || "",
                line_of_therapy_context: row.querySelector('[data-history-key="line_of_therapy_context"]')?.value || "",
                source: row.querySelector('[data-history-key="source"]')?.value || "",
            })).filter((row) => row.sample_date || row.testosterone_value || row.source || row.line_of_therapy_number || row.line_of_therapy_context);
            hidden.value = JSON.stringify(rows);
            const summary = wrapper.querySelector("[data-testosterone-history-summary]");
            if (summary) {
                summary.textContent = rows.length
                    ? `${rows.length} medición(es) listas para guardarse en la serie longitudinal.`
                    : "Sin mediciones adicionales; el basal seguirá siendo el punto canónico principal.";
            }
        });
    }

    function bindPsaHistory(scope) {
        scope.querySelectorAll("[data-add-psa-row]").forEach((button) => {
            if (button.dataset.bound === "true") {
                return;
            }
            button.dataset.bound = "true";
            button.addEventListener("click", () => {
                const wrapper = button.closest("[data-psa-history-field]");
                const rowsContainer = wrapper?.querySelector("[data-psa-history-rows]");
                if (!rowsContainer) {
                    return;
                }
                rowsContainer.insertAdjacentHTML("beforeend", renderPsaHistoryRows([{}], scope.dataset.clinicalState || ""));
                syncPsaHistoryField(scope);
                window.clinicalSelects?.syncAll(rowsContainer);
                bindPsaHistory(scope);
            });
        });

        scope.addEventListener("click", (event) => {
            const target = event.target;
            if (!(target instanceof HTMLElement) || !target.matches("[data-remove-psa-row]")) {
                return;
            }
            const row = target.closest("[data-psa-history-row]") || target.closest(".grid");
            const container = target.closest("[data-psa-history-field]")?.querySelector("[data-psa-history-rows]");
            if (!container) {
                return;
            }
            const allRows = container.querySelectorAll("[data-psa-history-row]");
            if (allRows.length <= 1) {
                row?.querySelectorAll("input").forEach((input) => { input.value = ""; });
                row?.querySelectorAll("select").forEach((select) => { select.selectedIndex = 0; });
            } else {
                row?.remove();
            }
            syncPsaHistoryField(scope);
        });

        scope.querySelectorAll("[data-psa-history-field]").forEach((wrapper) => {
            wrapper.querySelectorAll("input, select").forEach((input) => {
                if (input.dataset.boundChange === "true") {
                    return;
                }
                input.dataset.boundChange = "true";
                input.addEventListener("change", () => syncPsaHistoryField(scope));
                input.addEventListener("input", () => syncPsaHistoryField(scope));
            });
        });
        syncPsaHistoryField(scope);
    }

    function bindTestosteroneHistory(scope) {
        scope.querySelectorAll("[data-add-testosterone-row]").forEach((button) => {
            if (button.dataset.bound === "true") {
                return;
            }
            button.dataset.bound = "true";
            button.addEventListener("click", () => {
                const wrapper = button.closest("[data-testosterone-history-field]");
                const rowsContainer = wrapper?.querySelector("[data-testosterone-history-rows]");
                if (!rowsContainer) {
                    return;
                }
                rowsContainer.insertAdjacentHTML("beforeend", renderTestosteroneHistoryRows([{}], scope.dataset.clinicalState || ""));
                syncTestosteroneHistoryField(scope);
                window.clinicalSelects?.syncAll(rowsContainer);
                bindTestosteroneHistory(scope);
            });
        });

        scope.addEventListener("click", (event) => {
            const target = event.target;
            if (!(target instanceof HTMLElement) || !target.matches("[data-remove-testosterone-row]")) {
                return;
            }
            const row = target.closest("[data-testosterone-history-row]") || target.closest(".grid");
            const container = target.closest("[data-testosterone-history-field]")?.querySelector("[data-testosterone-history-rows]");
            if (!container) {
                return;
            }
            const allRows = container.querySelectorAll("[data-testosterone-history-row]");
            if (allRows.length <= 1) {
                row?.querySelectorAll("input").forEach((input) => { input.value = ""; });
                row?.querySelectorAll("select").forEach((select) => { select.selectedIndex = 0; });
            } else {
                row?.remove();
            }
            syncTestosteroneHistoryField(scope);
        });

        scope.querySelectorAll("[data-testosterone-history-field]").forEach((wrapper) => {
            wrapper.querySelectorAll("input, select").forEach((input) => {
                if (input.dataset.boundChange === "true") {
                    return;
                }
                input.dataset.boundChange = "true";
                input.addEventListener("change", () => syncTestosteroneHistoryField(scope));
                input.addEventListener("input", () => syncTestosteroneHistoryField(scope));
            });
        });
        syncTestosteroneHistoryField(scope);
    }

    function calculateBmi(weightKg, heightCm) {
        const weight = Number.parseFloat(weightKg);
        const height = Number.parseFloat(heightCm);
        if (!Number.isFinite(weight) || !Number.isFinite(height) || weight <= 0 || height <= 0) {
            return "";
        }
        const heightMeters = height / 100;
        if (!Number.isFinite(heightMeters) || heightMeters <= 0) {
            return "";
        }
        return (weight / (heightMeters * heightMeters)).toFixed(1);
    }

    function bindAnthropometricDerivations(scope) {
        const sync = () => {
            const weightInput = scope.querySelector('[name="weight_kg"]');
            const heightInput = scope.querySelector('[name="height_cm"]');
            const bmiInput = scope.querySelector('[name="bmi_current"]');
            if (bmiInput instanceof HTMLInputElement) {
                bmiInput.readOnly = true;
                bmiInput.value = calculateBmi(weightInput?.value || "", heightInput?.value || "");
            }
        };
        ["weight_kg", "height_cm"].forEach((fieldName) => {
            const input = scope.querySelector(`[name="${fieldName}"]`);
            if (!(input instanceof HTMLInputElement)) {
                return;
            }
            if (input.dataset.bmiBound === "true") {
                return;
            }
            input.dataset.bmiBound = "true";
            input.addEventListener("input", sync);
            input.addEventListener("change", sync);
        });
        sync();
    }

    const sharedLongitudinalCapture = window.ProstaNetLongitudinalCaptureHelpers || null;
    if (sharedLongitudinalCapture) {
        parseHistoryValue = sharedLongitudinalCapture.parseHistoryValue;
        renderPsaHistoryRows = (rows) => sharedLongitudinalCapture.renderHistoryRows("psa", rows);
        renderTestosteroneHistoryRows = (rows) => sharedLongitudinalCapture.renderHistoryRows("testosterone", rows);
        syncPsaHistoryField = (scope) => sharedLongitudinalCapture.syncHistoryField(scope, "psa");
        syncTestosteroneHistoryField = (scope) => sharedLongitudinalCapture.syncHistoryField(scope, "testosterone");
        bindPsaHistory = (scope) => sharedLongitudinalCapture.bindHistoryField(scope, "psa");
        bindTestosteroneHistory = (scope) => sharedLongitudinalCapture.bindHistoryField(scope, "testosterone");
        calculateBmi = sharedLongitudinalCapture.calculateBmi;
        bindAnthropometricDerivations = (scope) => sharedLongitudinalCapture.bindAnthropometricDerivations(scope, {
            weightName: "weight_kg",
            heightName: "height_cm",
            bmiName: "bmi_current",
        });
    }

    function parseStructuredValue(value, fallback) {
        if (value === null || value === undefined || value === "") {
            return fallback;
        }
        if (typeof value === "object") {
            return value;
        }
        try {
            const parsed = JSON.parse(value);
            return typeof parsed === "object" && parsed !== null ? parsed : fallback;
        } catch (_error) {
            return fallback;
        }
    }

    function deriveIsupFromGleason(primary, secondary) {
        if (!primary || !secondary) {
            return "";
        }
        const total = primary + secondary;
        if (total <= 6) {
            return "1";
        }
        if (total === 7 && primary === 3 && secondary === 4) {
            return "2";
        }
        if (total === 7 && primary === 4 && secondary === 3) {
            return "3";
        }
        if (total === 8) {
            return "4";
        }
        return "5";
    }

    function renderGleasonProfileField(field, providedValue, badgeTone) {
        const value = parseStructuredValue(providedValue, {});
        const primary = String(value.gleason_primary || "");
        const secondary = String(value.gleason_secondary || "");
        const tertiary = String(value.gleason_tertiary || "");
        const score = String(value.gleason_score || "");
        const isup = String(value.isup_grade || "");
        const optionMarkup = (selectedValue) => ["3", "4", "5"].map((pattern) => (
            `<option value="${pattern}" ${String(selectedValue) === pattern ? "selected" : ""}>Patrón ${pattern}</option>`
        )).join("");
        return `
            <div class="text-sm">
                <div class="mb-1 flex flex-wrap items-center justify-between gap-2">
                    <span class="block text-slate-300">${escapeHtml(field.label)}${field.required ? " *" : ""}</span>
                    <span class="rounded-full border px-2.5 py-1 text-[11px] font-medium ${badgeTone}">${escapeHtml(field.clinical_role_label || "")}</span>
                </div>
                <div class="rounded-2xl border border-amber-500/20 bg-amber-500/5 p-4" data-registration-gleason-widget="1" data-field-name="${escapeHtml(field.name)}">
                    <div class="grid gap-4 md:grid-cols-3">
                        <label class="text-sm">
                            <span class="block text-slate-300">Gleason primario</span>
                            <select class="pn-input mt-2 w-full px-3 py-2" data-role="gleason-primary">
                                <option value="">Seleccione</option>
                                ${optionMarkup(primary)}
                            </select>
                        </label>
                        <label class="text-sm">
                            <span class="block text-slate-300">Gleason secundario</span>
                            <select class="pn-input mt-2 w-full px-3 py-2" data-role="gleason-secondary">
                                <option value="">Seleccione</option>
                                ${optionMarkup(secondary)}
                            </select>
                        </label>
                        <label class="text-sm">
                            <span class="block text-slate-300">Patrón terciario (opcional)</span>
                            <select class="pn-input mt-2 w-full px-3 py-2" data-role="gleason-tertiary">
                                <option value="">Sin patrón terciario</option>
                                ${optionMarkup(tertiary)}
                            </select>
                        </label>
                    </div>
                    <div class="mt-4 rounded-2xl border border-slate-700/70 bg-slate-950/60 p-4" data-role="gleason-summary-card">
                        <p class="text-xs uppercase tracking-[0.2em] text-slate-500">Resumen histopatológico derivado</p>
                        <p class="mt-2 text-sm text-slate-200" data-role="gleason-summary">Seleccione Gleason primario y secundario para derivar automáticamente Gleason total e ISUP.</p>
                    </div>
                    <input type="hidden" name="gleason_primary" value="${escapeHtml(primary)}">
                    <input type="hidden" name="gleason_secondary" value="${escapeHtml(secondary)}">
                    <input type="hidden" name="gleason_tertiary" value="${escapeHtml(tertiary)}">
                    <input type="hidden" name="${escapeHtml(field.name)}" value="${escapeHtml(score)}">
                    <input type="hidden" name="isup_grade" value="${escapeHtml(isup)}">
                    <input type="hidden" name="has_adverse_tertiary_pattern" value="${tertiary === "5" ? "1" : "0"}">
                </div>
                <div class="mt-1 space-y-1">
                    ${field.help_text ? `<span class="block text-xs text-slate-500">${escapeHtml(field.help_text)}</span>` : ""}
                    ${renderScaleContext(field)}
                </div>
            </div>
        `;
    }

    function syncRegistrationGleasonWidget(wrapper) {
        const primarySelect = wrapper.querySelector('[data-role="gleason-primary"]');
        const secondarySelect = wrapper.querySelector('[data-role="gleason-secondary"]');
        const tertiarySelect = wrapper.querySelector('[data-role="gleason-tertiary"]');
        const summaryNode = wrapper.querySelector('[data-role="gleason-summary"]');
        const primary = Number.parseInt(primarySelect?.value || "", 10) || 0;
        const secondary = Number.parseInt(secondarySelect?.value || "", 10) || 0;
        const tertiary = Number.parseInt(tertiarySelect?.value || "", 10) || 0;
        const score = primary && secondary ? String(primary + secondary) : "";
        const isup = primary && secondary ? deriveIsupFromGleason(primary, secondary) : "";

        wrapper.querySelector('[name="gleason_primary"]').value = primary ? String(primary) : "";
        wrapper.querySelector('[name="gleason_secondary"]').value = secondary ? String(secondary) : "";
        wrapper.querySelector('[name="gleason_tertiary"]').value = tertiary ? String(tertiary) : "";
        wrapper.querySelector(`[name="${wrapper.dataset.fieldName}"]`).value = score;
        wrapper.querySelector('[name="isup_grade"]').value = isup;
        wrapper.querySelector('[name="has_adverse_tertiary_pattern"]').value = tertiary >= 5 ? "1" : "0";

        if (!(primary && secondary)) {
            summaryNode.textContent = "Seleccione Gleason primario y secundario para derivar automáticamente Gleason total e ISUP.";
            wrapper.dataset.valid = "0";
            return;
        }
        const parts = [`Gleason ${score} (${primary}+${secondary})`, `ISUP ${isup}`];
        if (tertiary) {
            parts.push(`patrón terciario ${tertiary}`);
        }
        summaryNode.textContent = `${parts.join(", ")}. ${tertiary ? "El patrón terciario se conserva como rasgo adverso, sin modificar el ISUP." : "El ISUP se deriva automáticamente desde el patrón primario y secundario."}`;
        wrapper.dataset.valid = "1";
    }

    function bindGleasonProfiles(scope) {
        scope.querySelectorAll("[data-registration-gleason-widget]").forEach((wrapper) => {
            if (wrapper.dataset.bound === "true") {
                syncRegistrationGleasonWidget(wrapper);
                return;
            }
            wrapper.dataset.bound = "true";
            wrapper.addEventListener("change", () => syncRegistrationGleasonWidget(wrapper));
            syncRegistrationGleasonWidget(wrapper);
        });
    }

    function metastaticWidgetConfig(field) {
        const raw = Array.isArray(field.options) ? field.options[0] : field.options;
        return typeof raw === "object" && raw !== null ? raw : {};
    }

    function renderMetastaticField(field, providedValue, badgeTone) {
        const value = parseStructuredValue(providedValue, {});
        const config = metastaticWidgetConfig(field);
        const known = String(value.metastatic_disease_known || "0") === "1" ? "1" : "0";
        return `
            <div class="text-sm">
                <div class="mb-1 flex flex-wrap items-center justify-between gap-2">
                    <span class="block text-slate-300">${escapeHtml(field.label)}${field.required ? " *" : ""}</span>
                    <span class="rounded-full border px-2.5 py-1 text-[11px] font-medium ${badgeTone}">${escapeHtml(field.clinical_role_label || "")}</span>
                </div>
                <div
                    class="rounded-2xl border border-cyan-500/20 bg-cyan-500/5 p-4"
                    data-registration-metastatic-widget="1"
                    data-field-name="${escapeHtml(field.name)}"
                    data-widget-config="${escapeHtml(JSON.stringify(config))}"
                    data-widget-default="${escapeHtml(JSON.stringify(value))}"
                >
                    <label class="block text-sm">
                        <span class="block text-slate-300">Enfermedad metastásica conocida</span>
                        <select class="pn-input mt-2 w-full px-3 py-2" data-role="metastatic-known-select">
                            <option value="0" ${known === "0" ? "selected" : ""}>No</option>
                            <option value="1" ${known === "1" ? "selected" : ""}>Sí</option>
                        </select>
                    </label>
                    <div class="mt-4 hidden" data-role="components-shell">
                        <div class="grid gap-3 md:grid-cols-3">
                            <label class="rounded-2xl border border-slate-700/70 bg-slate-950/70 p-3">
                                <span class="flex items-center gap-3">
                                    <input type="checkbox" data-role="component-toggle" value="nodes" class="h-4 w-4 rounded border-slate-600 bg-slate-900 text-cyan-400">
                                    <span class="text-sm text-slate-200">Ganglionares no regionales</span>
                                </span>
                            </label>
                            <label class="rounded-2xl border border-slate-700/70 bg-slate-950/70 p-3">
                                <span class="flex items-center gap-3">
                                    <input type="checkbox" data-role="component-toggle" value="bone" class="h-4 w-4 rounded border-slate-600 bg-slate-900 text-cyan-400">
                                    <span class="text-sm text-slate-200">Óseas</span>
                                </span>
                            </label>
                            <label class="rounded-2xl border border-slate-700/70 bg-slate-950/70 p-3">
                                <span class="flex items-center gap-3">
                                    <input type="checkbox" data-role="component-toggle" value="visceral" class="h-4 w-4 rounded border-slate-600 bg-slate-900 text-cyan-400">
                                    <span class="text-sm text-slate-200">Viscerales</span>
                                </span>
                            </label>
                        </div>
                    </div>
                    <div class="mt-4 hidden" data-role="nodal-block">
                        <div class="flex flex-wrap items-start justify-between gap-3">
                            <div>
                                <p class="text-xs uppercase tracking-[0.2em] text-slate-500">Distribución ganglionar no regional</p>
                                <p class="mt-1 text-sm text-slate-400">Agregue cadena ganglionar y número de lesiones.</p>
                            </div>
                            <button type="button" class="pn-btn pn-btn-secondary" data-role="add-nodal-row">Añadir cadena ganglionar</button>
                        </div>
                        <div class="mt-4 space-y-3" data-role="nodal-rows"></div>
                    </div>
                    <div class="mt-4 hidden" data-role="bone-block">
                        <div class="flex flex-wrap items-start justify-between gap-3">
                            <div>
                                <p class="text-xs uppercase tracking-[0.2em] text-slate-500">Distribución ósea</p>
                                <p class="mt-1 text-sm text-slate-400">Agregue sitio anatómico y número de lesiones.</p>
                            </div>
                            <button type="button" class="pn-btn pn-btn-secondary" data-role="add-bone-row">Añadir sitio óseo</button>
                        </div>
                        <div class="mt-4 space-y-3" data-role="bone-rows"></div>
                    </div>
                    <div class="mt-4 hidden" data-role="visceral-block">
                        <div class="flex flex-wrap items-start justify-between gap-3">
                            <div>
                                <p class="text-xs uppercase tracking-[0.2em] text-slate-500">Distribución visceral</p>
                                <p class="mt-1 text-sm text-slate-400">Agregue órgano visceral y número de lesiones.</p>
                            </div>
                            <button type="button" class="pn-btn pn-btn-secondary" data-role="add-visceral-row">Añadir órgano visceral</button>
                        </div>
                        <div class="mt-4 space-y-3" data-role="visceral-rows"></div>
                    </div>
                    <div class="mt-4 rounded-2xl border border-slate-700/70 bg-slate-950/60 p-4">
                        <p class="text-xs uppercase tracking-[0.2em] text-slate-500">Resumen metastásico</p>
                        <p class="mt-2 text-sm text-slate-200" data-role="summary-text">Seleccione si existe enfermedad metastásica conocida para desplegar la captura anatómica del caso.</p>
                    </div>
                    <input type="hidden" name="${escapeHtml(field.name)}" value="">
                    <input type="hidden" name="metastatic_disease_known" value="${known}">
                    <input type="hidden" name="metastasis_site" value="${escapeHtml(String(value.metastasis_site || "M0"))}">
                    <input type="hidden" name="metastasis_count" value="${escapeHtml(String(value.metastatic_total_lesion_count || value.metastasis_count || 0))}">
                    <input type="hidden" name="metastatic_total_lesion_count" value="${escapeHtml(String(value.metastatic_total_lesion_count || value.metastasis_count || 0))}">
                    <input type="hidden" name="bone_metastasis_present" value="${escapeHtml(String(value.bone_metastasis_present || "0"))}">
                    <input type="hidden" name="bone_site_entries" value="${escapeHtml(JSON.stringify(value.bone_site_entries || []))}">
                    <input type="hidden" name="visceral_metastasis_present" value="${escapeHtml(String(value.visceral_metastasis_present || "0"))}">
                    <input type="hidden" name="visceral_site_entries" value="${escapeHtml(JSON.stringify(value.visceral_site_entries || []))}">
                    <input type="hidden" name="visceral_lesion_count" value="${escapeHtml(String(value.visceral_lesion_count || 0))}">
                    <input type="hidden" name="nonregional_nodal_metastasis_present" value="${escapeHtml(String(value.nonregional_nodal_metastasis_present || "0"))}">
                    <input type="hidden" name="nonregional_nodal_count" value="${escapeHtml(String(value.nonregional_nodal_count || 0))}">
                    <input type="hidden" name="nonregional_nodal_site_entries" value="${escapeHtml(JSON.stringify(value.nonregional_nodal_site_entries || []))}">
                </div>
                <div class="mt-1 space-y-1">
                    ${field.help_text ? `<span class="block text-xs text-slate-500">${escapeHtml(field.help_text)}</span>` : ""}
                    ${renderScaleContext(field)}
                </div>
            </div>
        `;
    }

    function registrationMetastaticConfig(wrapper) {
        return parseStructuredValue(wrapper.dataset.widgetConfig || "{}", {});
    }

    function registrationOptionMarkup(options, selectedValue) {
        return `<option value="">Seleccione</option>${(options || []).map((option) => {
            const selected = String(option.site_key || "") === String(selectedValue || "") ? " selected" : "";
            return `<option value="${escapeHtml(option.site_key || "")}"${selected}>${escapeHtml(option.label || option.site_key || "")}</option>`;
        }).join("")}`;
    }

    function registrationBoneMarkup(wrapper, selectedValue) {
        const config = registrationMetastaticConfig(wrapper);
        const groups = Array.isArray(config.bone_site_groups) ? config.bone_site_groups : [];
        const groupsHtml = groups.map((group) => {
            const optionsHtml = (group.options || []).map((option) => {
                const selected = String(option.site_key || "") === String(selectedValue || "") ? " selected" : "";
                return `<option value="${escapeHtml(option.site_key || "")}"${selected}>${escapeHtml(option.label || option.site_key || "")}</option>`;
            }).join("");
            return `<optgroup label="${escapeHtml(group.label || "")}">${optionsHtml}</optgroup>`;
        }).join("");
        return `<option value="">Seleccione un sitio</option>${groupsHtml}`;
    }

    function createRegistrationMetastaticRow(wrapper, type, entry = {}) {
        const map = {
            bone: {
                rowsSelector: '[data-role="bone-rows"]',
                rowAttr: 'data-bone-row',
                buttonAttr: 'data-role="remove-bone-row"',
                siteRole: 'bone-site-key',
                countRole: 'bone-lesion-count',
                label: 'Sitio óseo',
                options: registrationBoneMarkup(wrapper, entry.site_key || ''),
            },
            visceral: {
                rowsSelector: '[data-role="visceral-rows"]',
                rowAttr: 'data-visceral-row',
                buttonAttr: 'data-role="remove-visceral-row"',
                siteRole: 'visceral-site-key',
                countRole: 'visceral-lesion-count',
                label: 'Órgano visceral',
                options: registrationOptionMarkup(registrationMetastaticConfig(wrapper).visceral_site_options, entry.site_key || ''),
            },
            nodes: {
                rowsSelector: '[data-role="nodal-rows"]',
                rowAttr: 'data-nodal-row',
                buttonAttr: 'data-role="remove-nodal-row"',
                siteRole: 'nodal-site-key',
                countRole: 'nodal-lesion-count',
                label: 'Cadena ganglionar no regional',
                options: registrationOptionMarkup(registrationMetastaticConfig(wrapper).nonregional_nodal_site_options, entry.site_key || ''),
            },
        }[type];
        if (!map) {
            return;
        }
        const rows = wrapper.querySelector(map.rowsSelector);
        if (!rows) {
            return;
        }
        const row = document.createElement("div");
        row.className = "rounded-2xl border border-slate-700/70 bg-slate-950/70 p-3";
        row.setAttribute(map.rowAttr, "1");
        row.innerHTML = `
            <div class="grid gap-3 md:grid-cols-[minmax(0,2fr)_160px_auto]">
                <label class="text-sm">
                    <span class="block text-slate-300">${map.label}</span>
                    <select class="pn-input mt-2 w-full px-3 py-2" data-role="${map.siteRole}">
                        ${map.options}
                    </select>
                </label>
                <label class="text-sm">
                    <span class="block text-slate-300">Número de lesiones</span>
                    <input type="number" min="1" step="1" value="${escapeHtml(entry.lesion_count || 1)}" class="pn-input mt-2 w-full px-3 py-2" data-role="${map.countRole}">
                </label>
                <div class="flex items-end">
                    <button type="button" class="pn-btn pn-btn-secondary w-full" ${map.buttonAttr}>Quitar</button>
                </div>
            </div>
        `;
        rows.appendChild(row);
    }

    function collectRegistrationMetastaticEntries(wrapper, rowSelector, siteSelector, countSelector) {
        return Array.from(wrapper.querySelectorAll(rowSelector)).map((row) => {
            const siteKey = String(row.querySelector(siteSelector)?.value || "").trim();
            const lesionCount = Math.max(0, Number.parseInt(row.querySelector(countSelector)?.value || "0", 10) || 0);
            return { site_key: siteKey, lesion_count: lesionCount };
        }).filter((entry) => entry.site_key && entry.lesion_count > 0);
    }

    function syncRegistrationMetastaticWidget(wrapper) {
        const known = String(wrapper.querySelector('[data-role="metastatic-known-select"]')?.value || "0") === "1";
        const toggleSet = new Set(
            Array.from(wrapper.querySelectorAll('[data-role="component-toggle"]'))
                .filter((toggle) => toggle.checked)
                .map((toggle) => toggle.value)
        );
        if (known && toggleSet.has("bone") && !wrapper.querySelector('[data-bone-row="1"]')) {
            createRegistrationMetastaticRow(wrapper, "bone", {});
        }
        if (known && toggleSet.has("visceral") && !wrapper.querySelector('[data-visceral-row="1"]')) {
            createRegistrationMetastaticRow(wrapper, "visceral", {});
        }
        if (known && toggleSet.has("nodes") && !wrapper.querySelector('[data-nodal-row="1"]')) {
            createRegistrationMetastaticRow(wrapper, "nodes", {});
        }
        const shell = wrapper.querySelector('[data-role="components-shell"]');
        const boneBlock = wrapper.querySelector('[data-role="bone-block"]');
        const visceralBlock = wrapper.querySelector('[data-role="visceral-block"]');
        const nodalBlock = wrapper.querySelector('[data-role="nodal-block"]');
        shell?.classList.toggle("hidden", !known);
        boneBlock?.classList.toggle("hidden", !(known && toggleSet.has("bone")));
        visceralBlock?.classList.toggle("hidden", !(known && toggleSet.has("visceral")));
        nodalBlock?.classList.toggle("hidden", !(known && toggleSet.has("nodes")));

        const boneEntries = collectRegistrationMetastaticEntries(wrapper, '[data-bone-row="1"]', '[data-role="bone-site-key"]', '[data-role="bone-lesion-count"]');
        const visceralEntries = collectRegistrationMetastaticEntries(wrapper, '[data-visceral-row="1"]', '[data-role="visceral-site-key"]', '[data-role="visceral-lesion-count"]');
        const nodalEntries = collectRegistrationMetastaticEntries(wrapper, '[data-nodal-row="1"]', '[data-role="nodal-site-key"]', '[data-role="nodal-lesion-count"]');
        const total = known
            ? boneEntries.reduce((acc, item) => acc + item.lesion_count, 0)
                + visceralEntries.reduce((acc, item) => acc + item.lesion_count, 0)
                + nodalEntries.reduce((acc, item) => acc + item.lesion_count, 0)
            : 0;
        const legacySite = known && toggleSet.has("visceral") ? "Visceral" : known && toggleSet.has("bone") ? "Bone" : known && toggleSet.has("nodes") ? "Node" : "M0";

        wrapper.querySelector('[name="metastatic_disease_known"]').value = known ? "1" : "0";
        wrapper.querySelector('[name="metastasis_site"]').value = legacySite;
        wrapper.querySelector('[name="metastasis_count"]').value = String(total);
        wrapper.querySelector('[name="metastatic_total_lesion_count"]').value = String(total);
        wrapper.querySelector('[name="bone_metastasis_present"]').value = known && toggleSet.has("bone") ? "1" : "0";
        wrapper.querySelector('[name="bone_site_entries"]').value = JSON.stringify(known ? boneEntries : []);
        wrapper.querySelector('[name="visceral_metastasis_present"]').value = known && toggleSet.has("visceral") ? "1" : "0";
        wrapper.querySelector('[name="visceral_site_entries"]').value = JSON.stringify(known ? visceralEntries : []);
        wrapper.querySelector('[name="visceral_lesion_count"]').value = String(known ? visceralEntries.reduce((acc, item) => acc + item.lesion_count, 0) : 0);
        wrapper.querySelector('[name="nonregional_nodal_metastasis_present"]').value = known && toggleSet.has("nodes") ? "1" : "0";
        wrapper.querySelector('[name="nonregional_nodal_count"]').value = String(known ? nodalEntries.reduce((acc, item) => acc + item.lesion_count, 0) : 0);
        wrapper.querySelector('[name="nonregional_nodal_site_entries"]').value = JSON.stringify(known ? nodalEntries : []);
        wrapper.querySelector(`[name="${wrapper.dataset.fieldName}"]`).value = JSON.stringify({
            metastatic_disease_known: known,
            components: known ? Array.from(toggleSet) : [],
            bone_site_entries: known ? boneEntries : [],
            visceral_site_entries: known ? visceralEntries : [],
            nonregional_nodal_site_entries: known ? nodalEntries : [],
            total_lesions: total,
        });

        const summary = wrapper.querySelector('[data-role="summary-text"]');
        if (!known) {
            summary.textContent = "Seleccione si existe enfermedad metastásica conocida para desplegar la captura anatómica del caso.";
            wrapper.dataset.valid = "1";
            return;
        }
        const valid = toggleSet.size > 0
            && (!toggleSet.has("bone") || boneEntries.length > 0)
            && (!toggleSet.has("visceral") || visceralEntries.length > 0)
            && (!toggleSet.has("nodes") || nodalEntries.length > 0);
        wrapper.dataset.valid = valid ? "1" : "0";
        const parts = [];
        if (toggleSet.has("nodes")) {
            parts.push(`ganglios no regionales ${nodalEntries.reduce((acc, item) => acc + item.lesion_count, 0) || "pendiente"}`);
        }
        if (toggleSet.has("bone")) {
            parts.push(`hueso ${boneEntries.reduce((acc, item) => acc + item.lesion_count, 0) || "pendiente"}`);
        }
        if (toggleSet.has("visceral")) {
            parts.push(`víscera ${visceralEntries.reduce((acc, item) => acc + item.lesion_count, 0) || "pendiente"}`);
        }
        summary.textContent = parts.length
            ? `Composición metastásica actual: ${parts.join(" · ")}. Sitio legado resumido: ${legacySite}.`
            : "Active al menos un componente metastásico documentado para este formulario.";
    }

    function bindMetastaticComponents(scope) {
        scope.querySelectorAll("[data-registration-metastatic-widget]").forEach((wrapper) => {
            if (wrapper.dataset.bound !== "true") {
                wrapper.dataset.bound = "true";
                const defaults = parseStructuredValue(wrapper.dataset.widgetDefault || "{}", {});
                const boneEntries = Array.isArray(defaults.bone_site_entries) ? defaults.bone_site_entries : parseStructuredValue(defaults.bone_site_entries, []);
                const visceralEntries = Array.isArray(defaults.visceral_site_entries) ? defaults.visceral_site_entries : parseStructuredValue(defaults.visceral_site_entries, []);
                const nodalEntries = Array.isArray(defaults.nonregional_nodal_site_entries) ? defaults.nonregional_nodal_site_entries : parseStructuredValue(defaults.nonregional_nodal_site_entries, []);
                const known = String(defaults.metastatic_disease_known || "0") === "1"
                    || [boneEntries, visceralEntries, nodalEntries].some((items) => Array.isArray(items) && items.length);
                wrapper.querySelector('[data-role="metastatic-known-select"]').value = known ? "1" : "0";
                wrapper.querySelectorAll('[data-role="component-toggle"]').forEach((toggle) => {
                    if (toggle.value === "bone") {
                        toggle.checked = boneEntries.length > 0;
                    } else if (toggle.value === "visceral") {
                        toggle.checked = visceralEntries.length > 0;
                    } else if (toggle.value === "nodes") {
                        toggle.checked = nodalEntries.length > 0;
                    }
                });
                boneEntries.forEach((entry) => createRegistrationMetastaticRow(wrapper, "bone", entry));
                visceralEntries.forEach((entry) => createRegistrationMetastaticRow(wrapper, "visceral", entry));
                nodalEntries.forEach((entry) => createRegistrationMetastaticRow(wrapper, "nodes", entry));
                wrapper.addEventListener("click", (event) => {
                    const target = event.target;
                    if (!(target instanceof HTMLElement)) {
                        return;
                    }
                    if (target.closest('[data-role="add-bone-row"]')) {
                        createRegistrationMetastaticRow(wrapper, "bone", {});
                    } else if (target.closest('[data-role="add-visceral-row"]')) {
                        createRegistrationMetastaticRow(wrapper, "visceral", {});
                    } else if (target.closest('[data-role="add-nodal-row"]')) {
                        createRegistrationMetastaticRow(wrapper, "nodes", {});
                    } else if (target.closest('[data-role="remove-bone-row"]')) {
                        target.closest('[data-bone-row="1"]')?.remove();
                    } else if (target.closest('[data-role="remove-visceral-row"]')) {
                        target.closest('[data-visceral-row="1"]')?.remove();
                    } else if (target.closest('[data-role="remove-nodal-row"]')) {
                        target.closest('[data-nodal-row="1"]')?.remove();
                    }
                    syncRegistrationMetastaticWidget(wrapper);
                    window.clinicalSelects?.syncAll(wrapper);
                });
                wrapper.addEventListener("change", () => syncRegistrationMetastaticWidget(wrapper));
                wrapper.addEventListener("input", () => syncRegistrationMetastaticWidget(wrapper));
            }
            syncRegistrationMetastaticWidget(wrapper);
            window.clinicalSelects?.syncAll(wrapper);
        });
    }

    function renderRegistrationField(field, providedValue, clinicalState = "") {
        const value = providedValue ?? field.default ?? "";
        const required = field.required ? "required" : "";
        const conditionsAttr = field.conditional_visibility
            ? ` data-conditions='${escapeHtml(JSON.stringify(field.conditional_visibility))}'`
            : "";
        const badgeTone = {
            "required": "border-emerald-500/30 bg-emerald-500/10 text-emerald-200",
            "decision_refiner": "border-cyan-500/30 bg-cyan-500/10 text-cyan-200",
            "monitoring": "border-amber-500/30 bg-amber-500/10 text-amber-200",
            "optional": "border-slate-700 bg-slate-900 text-slate-300",
        }[field.clinical_role] || "border-slate-700 bg-slate-900 text-slate-300";

        if (field.field_type === "psa_history") {
            const rows = parseHistoryValue(value);
            return `
                <div class="text-sm" data-psa-history-field${conditionsAttr}>
                    <div class="mb-1 flex flex-wrap items-center justify-between gap-2">
                        <span class="block text-slate-300">${escapeHtml(field.label)}${field.required ? " *" : ""}</span>
                        <span class="rounded-full border px-2.5 py-1 text-[11px] font-medium ${badgeTone}">${escapeHtml(field.clinical_role_label || "")}</span>
                    </div>
                    <input type="hidden" name="${escapeHtml(field.name)}" data-psa-history-input value="${escapeHtml(JSON.stringify(rows))}">
                    <div class="space-y-3" data-psa-history-rows>
                        ${rows.length ? renderPsaHistoryRows(rows, clinicalState) : renderPsaHistoryRows([{}], clinicalState)}
                    </div>
                    <div class="mt-3 flex flex-wrap items-center justify-between gap-3">
                        <button type="button" class="pn-btn pn-btn-secondary" data-add-psa-row>Agregar medición</button>
                        <span class="text-xs text-slate-400" data-psa-history-summary></span>
                    </div>
                    <div class="mt-2 space-y-1">
                        ${field.help_text ? `<span class="block text-xs text-slate-500">${escapeHtml(field.help_text)}</span>` : ""}
                        ${renderReferenceRange(field)}
                        ${renderScaleContext(field)}
                    </div>
                </div>
            `;
        }

        if (field.field_type === "testosterone_history") {
            const rows = parseHistoryValue(value);
            return `
                <div class="text-sm" data-testosterone-history-field${conditionsAttr}>
                    <div class="mb-1 flex flex-wrap items-center justify-between gap-2">
                        <span class="block text-slate-300">${escapeHtml(field.label)}${field.required ? " *" : ""}</span>
                        <span class="rounded-full border px-2.5 py-1 text-[11px] font-medium ${badgeTone}">${escapeHtml(field.clinical_role_label || "")}</span>
                    </div>
                    <input type="hidden" name="${escapeHtml(field.name)}" data-testosterone-history-input value="${escapeHtml(JSON.stringify(rows))}">
                    <div class="space-y-3" data-testosterone-history-rows>
                        ${rows.length ? renderTestosteroneHistoryRows(rows, clinicalState) : renderTestosteroneHistoryRows([{}], clinicalState)}
                    </div>
                    <div class="mt-3 flex flex-wrap items-center justify-between gap-3">
                        <button type="button" class="pn-btn pn-btn-secondary" data-add-testosterone-row>Agregar medición</button>
                        <span class="text-xs text-slate-400" data-testosterone-history-summary></span>
                    </div>
                    <div class="mt-2 space-y-1">
                        ${field.help_text ? `<span class="block text-xs text-slate-500">${escapeHtml(field.help_text)}</span>` : ""}
                        ${renderReferenceRange(field)}
                        ${renderScaleContext(field)}
                    </div>
                </div>
            `;
        }

        if (field.field_type === "gleason_profile") {
            return `<div${conditionsAttr}>${renderGleasonProfileField(field, value, badgeTone)}</div>`;
        }

        if (field.field_type === "metastatic_components") {
            return `<div${conditionsAttr}>${renderMetastaticField(field, value, badgeTone)}</div>`;
        }

        if (field.field_type === "select") {
            const searchMode = field.name === "estado_residencia" ? "on" : "auto";
            const options = (field.display_options || []).map((option) => {
                const selected = String(option.value) === String(value) ? "selected" : "";
                return `<option value="${escapeHtml(option.value)}" ${selected}>${escapeHtml(option.label)}</option>`;
            }).join("");
            return `
                <div class="text-sm"${conditionsAttr}>
                <label class="text-sm block">
                    <div class="mb-1 flex flex-wrap items-center justify-between gap-2">
                        <span class="block text-slate-300">${escapeHtml(field.label)}${field.required ? " *" : ""}</span>
                        <span class="rounded-full border px-2.5 py-1 text-[11px] font-medium ${badgeTone}">${escapeHtml(field.clinical_role_label || "")}</span>
                    </div>
                    <select
                        name="${escapeHtml(field.name)}"
                        class="pn-input w-full px-3 py-2"
                        data-pn-select-variant="default"
                        data-pn-select-search="${searchMode}"
                        ${required}
                    >
                        ${options}
                    </select>
                    <div class="mt-1 space-y-1">
                        ${field.unit ? `<span class="block text-[11px] uppercase tracking-[0.2em] text-slate-500">Unidad: ${escapeHtml(field.unit)}</span>` : ""}
                        ${field.help_text ? `<span class="block text-xs text-slate-500">${escapeHtml(field.help_text)}</span>` : ""}
                        ${renderReferenceRange(field)}
                        ${renderScaleContext(field)}
                        ${field.benchmark_note ? `<span class="block rounded-2xl border border-cyan-500/20 bg-cyan-500/5 px-3 py-2 text-xs text-cyan-200">${escapeHtml(field.benchmark_note)}</span>` : ""}
                    </div>
                </label></div>
            `;
        }

        const inputType = field.field_type === "number"
            ? "number"
            : field.field_type === "date"
                ? "date"
                : "text";
        const inputValue = value === null || value === undefined ? "" : value;
        const readOnly = field.name === "bmi_current" ? "readonly" : "";

        return `
            <div class="text-sm"${conditionsAttr}>
            <label class="text-sm block">
                <div class="mb-1 flex flex-wrap items-center justify-between gap-2">
                    <span class="block text-slate-300">${escapeHtml(field.label)}${field.required ? " *" : ""}</span>
                    <span class="rounded-full border px-2.5 py-1 text-[11px] font-medium ${badgeTone}">${escapeHtml(field.clinical_role_label || "")}</span>
                </div>
                <input
                    type="${inputType}"
                    name="${escapeHtml(field.name)}"
                    value="${escapeHtml(inputValue)}"
                    class="pn-input w-full px-3 py-2"
                    ${readOnly}
                    ${required}
                >
                <div class="mt-1 space-y-1">
                    ${field.unit ? `<span class="block text-[11px] uppercase tracking-[0.2em] text-slate-500">Unidad: ${escapeHtml(field.unit)}</span>` : ""}
                    ${field.help_text ? `<span class="block text-xs text-slate-500">${escapeHtml(field.help_text)}</span>` : ""}
                    ${renderReferenceRange(field)}
                    ${renderScaleContext(field)}
                    ${field.benchmark_note ? `<span class="block rounded-2xl border border-cyan-500/20 bg-cyan-500/5 px-3 py-2 text-xs text-cyan-200">${escapeHtml(field.benchmark_note)}</span>` : ""}
                </div>
            </label></div>
        `;
    }

    function renderFragmentFields(fields, defaults, clinicalState = "") {
        if (!fields || !fields.length) {
            return '<p class="text-sm text-slate-400">Sin campos adicionales para este bloque.</p>';
        }

        let html = "";
        let currentGroup = "";
        fields.forEach((field, index) => {
            if (field.group !== currentGroup) {
                if (index > 0) {
                    html += "</div></div>";
                }
                currentGroup = field.group;
                html += `
                    <div class="pt-1">
                        <p class="text-xs uppercase tracking-[0.2em] text-slate-500" style="overflow-wrap:anywhere">${escapeHtml(currentGroup || "Datos longitudinales")}</p>
                        <div class="mt-3 grid gap-4 md:grid-cols-2">
                `;
            }
            html += renderRegistrationField(field, defaults[field.name], clinicalState);
            if (index === fields.length - 1) {
                html += "</div></div>";
            }
        });
        return html;
    }

    function renderFragment(fragment, defaults, clinicalState = "") {
        const body = `
            <section class="rounded-3xl border border-slate-800 bg-slate-950/40 p-5">
                <div class="flex flex-wrap items-start justify-between gap-3">
                    <div class="min-w-0">
                        <p class="text-xs uppercase tracking-[0.2em] text-slate-500" style="overflow-wrap:anywhere">${escapeHtml(fragment.id)}</p>
                        <h3 class="mt-1 text-base font-semibold text-white" style="overflow-wrap:anywhere">${escapeHtml(fragment.title)}</h3>
                        ${fragment.when_to_ask ? `<p class="mt-2 text-sm text-slate-400">${escapeHtml(fragment.when_to_ask)}</p>` : ""}
                    </div>
                    <div class="flex flex-wrap gap-2">
                        ${fragment.optional_research ? '<span class="rounded-full border border-slate-700 bg-slate-900 px-3 py-1 text-[11px] text-slate-300">Investigación opcional</span>' : ""}
                        ${fragment.benchmark_only ? '<span class="rounded-full border border-cyan-500/20 bg-cyan-500/10 px-3 py-1 text-[11px] text-cyan-200">Benchmarking</span>' : ""}
                    </div>
                </div>
                ${fragment.clinical_influence?.length ? `<ul class="mt-4 space-y-2 text-sm text-slate-300">${fragment.clinical_influence.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : ""}
                <div class="mt-4">${renderFragmentFields(fragment.fields || [], defaults, clinicalState)}</div>
            </section>
        `;
        if (fragment.collapsed_by_default || fragment.optional_research) {
            return `
                <details class="rounded-3xl border border-slate-800 bg-slate-950/20 p-2">
                    <summary class="cursor-pointer list-none rounded-2xl px-3 py-2 text-sm font-medium text-slate-200" style="overflow-wrap:anywhere">
                        ${escapeHtml(fragment.title)}
                    </summary>
                    <div class="mt-3">${body}</div>
                </details>
            `;
        }
        return body;
    }

    function renderRegistrationLedgerPanel(ledgerContext) {
        const context = ledgerContext || {};
        const summary = context.summary || {};
        const reused = context.reused_imported_fields || [];
        const conflicts = context.conflict_imported_fields || context.conflict_fields || [];
        const activeCount = Number(summary.ledger_mapped_field_count || 0)
            + Number(summary.reused_imported_field_count || 0)
            + Number(summary.conflict_imported_field_count || 0)
            + reused.length
            + conflicts.length;
        if (!activeCount) {
            return "";
        }
        const contract = context.ui_contract || {};
        const dataFlags = `
            data-source-clinical-facts-mutated="${String(Boolean(contract.source_clinical_facts_mutated || context.source_clinical_facts_mutated))}"
            data-external-order-created="${String(Boolean(contract.external_order_created || context.external_order_created))}"
            data-model-trained="${String(Boolean(contract.model_trained || context.model_trained))}"
        `;
        const renderFactPill = (item, tone) => `
            <span class="inline-flex max-w-full items-center gap-1 rounded-full border ${tone === "conflict" ? "border-amber-400/40 bg-amber-400/10 text-amber-100" : "border-emerald-400/30 bg-emerald-400/10 text-emerald-100"} px-3 py-1 text-[11px]">
                <span class="truncate">${escapeHtml(item.field_label || item.field_name || item.fact_key || "Hecho clínico")}</span>
                ${item.source_count ? `<span class="text-slate-400">${escapeHtml(String(item.source_count))} fuentes</span>` : ""}
            </span>
        `;
        return `
            <section data-testid="registration-ledger-prefill-panel" class="rounded-3xl border border-emerald-400/30 bg-emerald-400/10 p-5">
                <div data-testid="registration-ledger-contract" class="sr-only" ${dataFlags}>Contrato Ledger: solo lectura.</div>
                <div class="flex flex-wrap items-start justify-between gap-4">
                    <div>
                        <p class="text-xs uppercase tracking-[0.22em] text-emerald-200">Clinical Fact Ledger v1</p>
                        <h3 class="mt-1 text-base font-semibold text-white">Registro sin recaptura innecesaria</h3>
                        <p class="mt-2 text-sm text-slate-300">Los datos clínicos ya conocidos se reutilizan como contexto importado; las contradicciones se mantienen visibles para resolverlas antes de reutilizar.</p>
                    </div>
                    <div class="grid min-w-[13rem] grid-cols-3 gap-2 text-center text-xs">
                        <div class="rounded-2xl border border-slate-700/70 bg-slate-950/40 p-3">
                            <p class="text-lg font-semibold text-white">${escapeHtml(String(summary.imported_field_count || 0))}</p>
                            <p class="text-slate-400">importados</p>
                        </div>
                        <div class="rounded-2xl border border-emerald-400/30 bg-emerald-400/10 p-3">
                            <p class="text-lg font-semibold text-emerald-100">${escapeHtml(String(summary.reused_imported_field_count || reused.length || 0))}</p>
                            <p class="text-emerald-200">reusados</p>
                        </div>
                        <div class="rounded-2xl border border-amber-400/30 bg-amber-400/10 p-3">
                            <p class="text-lg font-semibold text-amber-100">${escapeHtml(String(summary.conflict_imported_field_count || conflicts.length || 0))}</p>
                            <p class="text-amber-200">conflictos</p>
                        </div>
                    </div>
                </div>
                ${reused.length || conflicts.length ? `
                    <div class="mt-4 flex flex-wrap gap-2">
                        ${reused.slice(0, 8).map((item) => renderFactPill(item, "reuse")).join("")}
                        ${conflicts.slice(0, 6).map((item) => renderFactPill(item, "conflict")).join("")}
                    </div>
                ` : ""}
            </section>
        `;
    }

    function renderRegistrationContext({ target, fragments, defaults = {}, captureLayers = [], ledgerContext = null, clinicalState = "" }) {
        if (!target) {
            return;
        }
        target.dataset.clinicalState = clinicalState || "";
        if (!fragments || !fragments.length) {
            target.innerHTML = '<p class="text-sm text-slate-400">Sin bloques de registro para este estado.</p>';
            return;
        }
        const fragmentMap = new Map((fragments || []).map((fragment) => [fragment.id, fragment]));
        const orderedLayers = captureLayers.length
            ? captureLayers.map((layer) => ({
                ...layer,
                fragments: (layer.fragment_ids || []).map((fragmentId) => fragmentMap.get(fragmentId)).filter(Boolean),
            }))
            : [{ id: "all", label: "Captura clínica", description: "", fragments }];

        const ledgerPanel = renderRegistrationLedgerPanel(ledgerContext);
        target.innerHTML = `${ledgerPanel}${orderedLayers.map((layer) => `
            <section class="space-y-4">
                <div class="rounded-3xl border border-slate-800 bg-slate-950/30 p-5">
                    <p class="text-xs uppercase tracking-[0.24em] text-cyan-300" style="overflow-wrap:anywhere">${escapeHtml(layer.label || "Captura clínica")}</p>
                    ${layer.description ? `<p class="mt-2 text-sm text-slate-300">${escapeHtml(layer.description)}</p>` : ""}
                </div>
                <div class="space-y-5">
                    ${(layer.fragments || []).map((fragment) => renderFragment(fragment, defaults, clinicalState)).join("")}
                </div>
            </section>
        `).join("")}`;
        window.clinicalSelects?.syncAll(target);
        bindPsaHistory(target);
        bindTestosteroneHistory(target);
        bindGleasonProfiles(target);
        bindMetastaticComponents(target);
        bindAnthropometricDerivations(target);
        updateConditionalVisibility(target);
        if (target.dataset.conditionalBound !== "true") {
            target.dataset.conditionalBound = "true";
            target.addEventListener("change", () => updateConditionalVisibility(target));
            target.addEventListener("input", () => updateConditionalVisibility(target));
        }
    }

    function renderImportedClinicalFields({ container, countNode, fields }) {
        if (!container || !countNode) {
            return;
        }
        if (!fields || !fields.length) {
            container.innerHTML = '<p class="text-sm text-slate-400">No se importaron variables clínicas para este borrador.</p>';
            countNode.textContent = "0 variables importadas";
            return;
        }
        countNode.textContent = `${fields.length} variables importadas`;
        container.innerHTML = fields.map((field) => {
            const ledgerChip = field.ledger_action === "reuse_prefill_hide"
                ? '<span class="rounded-full border border-emerald-400/30 bg-emerald-400/10 px-2.5 py-1 text-[11px] text-emerald-100">Ledger reutilizado</span>'
                : field.ledger_action === "resolve_conflict_before_reuse"
                    ? '<span class="rounded-full border border-amber-400/30 bg-amber-400/10 px-2.5 py-1 text-[11px] text-amber-100">Ledger conflicto</span>'
                    : "";
            return `
            <div class="rounded-2xl border border-slate-700/80 bg-slate-900/70 p-4">
                <div class="flex flex-wrap items-center gap-2">
                    <p class="text-sm font-medium text-white">${escapeHtml(field.label)}</p>
                    <span class="rounded-full border border-slate-700 bg-slate-900 px-2.5 py-1 text-[11px] text-slate-300">${escapeHtml(field.clinical_role_label || "")}</span>
                    ${field.capture_layer_label ? `<span class="rounded-full border border-cyan-500/20 bg-cyan-500/10 px-2.5 py-1 text-[11px] text-cyan-200">${escapeHtml(field.capture_layer_label)}</span>` : ""}
                    ${ledgerChip}
                </div>
                <p class="mt-2 text-sm text-cyan-100">${formatRegistrationValue(field.value_label)}</p>
                ${field.ledger_fact_key ? `<p class="mt-2 text-xs text-emerald-200">Ledger: ${escapeHtml(field.ledger_fact_key)}${field.ledger_source_count ? ` · ${escapeHtml(String(field.ledger_source_count))} fuentes` : ""}</p>` : ""}
                ${field.persist_targets?.length ? `<p class="mt-2 text-xs text-slate-500">Persistencia: ${field.persist_targets.map((item) => escapeHtml(item)).join(", ")}</p>` : ""}
                ${field.when_to_ask ? `<p class="mt-2 text-xs text-slate-400">${escapeHtml(field.when_to_ask)}</p>` : ""}
            </div>
        `; }).join("");
    }

    function buildRegistrationPayload(form) {
        bindGleasonProfiles(form);
        bindMetastaticComponents(form);
        syncPsaHistoryField(form);
        syncTestosteroneHistoryField(form);
        window.ProstaNetRealWorldEnrollment?.syncForm?.(form);
        const payload = {};
        const formData = new FormData(form);
        formData.forEach((value, key) => {
            if (key === "psa_history" || key === "ape_history" || key === "testosterone_history") {
                payload[key] = parseHistoryValue(value);
                return;
            }
            payload[key] = value;
        });
        return payload;
    }

    window.ProstaNetRegistrationContextUI = {
        escapeHtml,
        formatRegistrationValue,
        renderRegistrationLedgerPanel,
        renderImportedClinicalFields,
        renderRegistrationContext,
        buildRegistrationPayload,
        syncPsaHistoryField,
        parseHistoryValue,
        bindPsaHistory,
        bindTestosteroneHistory,
        bindAnthropometricDerivations,
    };
})();
