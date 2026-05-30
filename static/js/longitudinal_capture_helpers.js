(function () {
    function escapeHtml(value) {
        return String(value ?? "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
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

    function currentClinicalState() {
        const bodyClass = document.body?.className || "";
        const match = String(bodyClass).match(/pm2-longitudinal-state-([a-zA-Z0-9_]+)/);
        return match ? match[1] : "";
    }

    function lineContextOptionsForState(clinicalState, selectedValue = "") {
        const state = String(clinicalState || "").trim().toLowerCase();
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
        if (selectedValue && !options.some((option) => option.value === selectedValue)) {
            const legacy = LINE_CONTEXT_OPTIONS.find((option) => option.value === selectedValue);
            options.push(legacy || { value: selectedValue, label: selectedValue });
        }
        return options;
    }

    function renderLineContextOptions(selectedValue = "", clinicalState = currentClinicalState()) {
        return lineContextOptionsForState(clinicalState, selectedValue)
            .map((option) => `<option value="${escapeHtml(option.value)}" ${option.value === selectedValue ? "selected" : ""}>${escapeHtml(option.label)}</option>`)
            .join("");
    }

    function renderPsaHistoryRows(rows, clinicalState = currentClinicalState()) {
        const initialRows = rows.length ? rows : [{}];
        return initialRows.map((row) => `
            <div data-psa-history-row class="grid gap-3 rounded-2xl border border-slate-800 bg-slate-950/50 p-4 md:grid-cols-2 xl:grid-cols-3">
                <label class="text-sm">
                    <span class="mb-1 block text-slate-300">Fecha de muestra</span>
                    <input type="date" data-history-key="sample_date" value="${escapeHtml(row.sample_date || "")}" class="pn-input w-full px-3 py-2">
                </label>
                <label class="text-sm">
                    <span class="mb-1 block text-slate-300">APE / PSA (ng/mL)</span>
                    <input type="number" step="0.01" min="0" data-history-key="psa_value" value="${escapeHtml(row.psa_value || row.value || "")}" class="pn-input w-full px-3 py-2">
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

    function renderTestosteroneHistoryRows(rows, clinicalState = currentClinicalState()) {
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

    // Faubot 2026-04-25 (LXVI) — Auditoría #63C
    // Widget multi-row para captura de N líneas terapéuticas previas al
    // intake. Reusa el pattern psa_history pero estructura por línea
    // terapéutica (no por measurement). Cada row representa una línea
    // sistémica previa con: start_date, end_date, drug_scheme, line_number,
    // reason_for_change, best_psa_response_pct.
    function renderPriorLinesHistoryRows(rows) {
        const initialRows = rows.length ? rows : [{}];
        return initialRows.map((row) => `
            <div data-prior-lines-history-row class="grid gap-3 rounded-2xl border border-slate-800 bg-slate-950/50 p-4 md:grid-cols-2 xl:grid-cols-3">
                <label class="text-sm">
                    <span class="mb-1 block text-slate-300">Fecha de inicio</span>
                    <input type="date" data-history-key="start_date" value="${escapeHtml(row.start_date || "")}" class="pn-input w-full px-3 py-2">
                </label>
                <label class="text-sm">
                    <span class="mb-1 block text-slate-300">Fecha de fin</span>
                    <input type="date" data-history-key="end_date" value="${escapeHtml(row.end_date || "")}" class="pn-input w-full px-3 py-2">
                </label>
                <label class="text-sm">
                    <span class="mb-1 block text-slate-300">Línea (#)</span>
                    <input type="number" min="1" step="1" data-history-key="line_of_therapy_number" value="${escapeHtml(row.line_of_therapy_number || "")}" class="pn-input w-full px-3 py-2" placeholder="1, 2, 3...">
                </label>
                <label class="text-sm">
                    <span class="mb-1 block text-slate-300">Motivo de cambio</span>
                    <select data-history-key="reason_for_change" class="pn-input w-full px-3 py-2">
                        <option value="" ${!row.reason_for_change ? "selected" : ""}>Sin documentar</option>
                        <option value="progression_psa" ${row.reason_for_change === "progression_psa" ? "selected" : ""}>Progresión PSA</option>
                        <option value="progression_radiographic" ${row.reason_for_change === "progression_radiographic" ? "selected" : ""}>Progresión radiográfica</option>
                        <option value="progression_clinical" ${row.reason_for_change === "progression_clinical" ? "selected" : ""}>Progresión clínica</option>
                        <option value="toxicity" ${row.reason_for_change === "toxicity" ? "selected" : ""}>Toxicidad</option>
                        <option value="completion_planned" ${row.reason_for_change === "completion_planned" ? "selected" : ""}>Plan completado</option>
                        <option value="patient_choice" ${row.reason_for_change === "patient_choice" ? "selected" : ""}>Decisión paciente</option>
                        <option value="other" ${row.reason_for_change === "other" ? "selected" : ""}>Otro</option>
                    </select>
                </label>
                <label class="text-sm">
                    <span class="mb-1 block text-slate-300">% cambio PSA nadir</span>
                    <input type="number" step="0.1" data-history-key="best_psa_response_pct" value="${escapeHtml(row.best_psa_response_pct || "")}" class="pn-input w-full px-3 py-2" placeholder="-75 (negativo = reducción)">
                </label>
                <div class="flex items-end justify-end">
                    <button type="button" class="pn-btn pn-btn-secondary" data-remove-prior-lines-row>Quitar</button>
                </div>
                <label class="text-sm lg:col-span-3">
                    <span class="mb-1 block text-slate-300">Esquema farmacológico (canónico)</span>
                    <input type="text" data-history-key="drug_scheme" value="${escapeHtml(row.drug_scheme || "")}" class="pn-input w-full px-3 py-2" placeholder="ADT_MONO, ADT_ENZALUTAMIDE, ADT_DOCETAXEL, etc.">
                </label>
                <label class="text-sm lg:col-span-3">
                    <span class="mb-1 block text-slate-300">Contexto de línea (opcional)</span>
                    <select data-history-key="line_of_therapy_context" class="pn-input w-full px-3 py-2">
                        <option value="" ${!row.line_of_therapy_context ? "selected" : ""}>Sin contexto documentado</option>
                        <option value="mHSPC_initial" ${row.line_of_therapy_context === "mHSPC_initial" ? "selected" : ""}>mHSPC inicial</option>
                        <option value="mHSPC_post_docetaxel" ${row.line_of_therapy_context === "mHSPC_post_docetaxel" ? "selected" : ""}>mHSPC post-docetaxel</option>
                        <option value="m0_CRPC_first_line" ${row.line_of_therapy_context === "m0_CRPC_first_line" ? "selected" : ""}>m0 CRPC primera línea</option>
                        <option value="mCRPC_first_line" ${row.line_of_therapy_context === "mCRPC_first_line" ? "selected" : ""}>mCRPC primera línea</option>
                        <option value="mCRPC_post_ARPI_pre_taxane" ${row.line_of_therapy_context === "mCRPC_post_ARPI_pre_taxane" ? "selected" : ""}>mCRPC post-ARPI pre-taxano</option>
                        <option value="mCRPC_post_taxane" ${row.line_of_therapy_context === "mCRPC_post_taxane" ? "selected" : ""}>mCRPC post-taxano</option>
                        <option value="mCRPC_post_PARP" ${row.line_of_therapy_context === "mCRPC_post_PARP" ? "selected" : ""}>mCRPC post-PARP</option>
                        <option value="mCRPC_post_Lu177" ${row.line_of_therapy_context === "mCRPC_post_Lu177" ? "selected" : ""}>mCRPC post-Lu177</option>
                        <option value="later_line" ${row.line_of_therapy_context === "later_line" ? "selected" : ""}>Líneas posteriores</option>
                    </select>
                </label>
            </div>
        `).join("");
    }

    function renderHistoryRows(kind, rows) {
        if (kind === "testosterone") {
            return renderTestosteroneHistoryRows(rows);
        }
        if (kind === "prior_lines") {
            return renderPriorLinesHistoryRows(rows);
        }
        return renderPsaHistoryRows(rows);
    }

    function _selectorsForKind(kind) {
        // Faubot LXVI #63C — selectors centralizados (3 kinds: psa, testosterone, prior_lines)
        if (kind === "testosterone") {
            return {
                wrapper: "[data-testosterone-history-field]",
                input: "[data-testosterone-history-input]",
                summary: "[data-testosterone-history-summary]",
                row: "[data-testosterone-history-row]",
                rows: "[data-testosterone-history-rows]",
                add: "[data-add-testosterone-row]",
                remove: "[data-remove-testosterone-row]",
                clickKey: "testosteroneHistoryClickBound",
            };
        }
        if (kind === "prior_lines") {
            return {
                wrapper: "[data-prior-lines-history-field]",
                input: "[data-prior-lines-history-input]",
                summary: "[data-prior-lines-history-summary]",
                row: "[data-prior-lines-history-row]",
                rows: "[data-prior-lines-history-rows]",
                add: "[data-add-prior-lines-row]",
                remove: "[data-remove-prior-lines-row]",
                clickKey: "priorLinesHistoryClickBound",
            };
        }
        return {
            wrapper: "[data-psa-history-field]",
            input: "[data-psa-history-input]",
            summary: "[data-psa-history-summary]",
            row: "[data-psa-history-row]",
            rows: "[data-psa-history-rows]",
            add: "[data-add-psa-row]",
            remove: "[data-remove-psa-row]",
            clickKey: "psaHistoryClickBound",
        };
    }

    function syncHistoryField(scope, kind) {
        const sel = _selectorsForKind(kind);

        scope.querySelectorAll(sel.wrapper).forEach((wrapper) => {
            const hidden = wrapper.querySelector(sel.input);
            if (!hidden) {
                return;
            }
            const rows = Array.from(wrapper.querySelectorAll(sel.row)).map((row) => {
                if (kind === "prior_lines") {
                    // Faubot LXVI #63C — payload prior_lines (estructura per línea)
                    return {
                        start_date: row.querySelector('[data-history-key="start_date"]')?.value || "",
                        end_date: row.querySelector('[data-history-key="end_date"]')?.value || "",
                        drug_scheme: row.querySelector('[data-history-key="drug_scheme"]')?.value || "",
                        line_of_therapy_number: row.querySelector('[data-history-key="line_of_therapy_number"]')?.value || "",
                        line_of_therapy_context: row.querySelector('[data-history-key="line_of_therapy_context"]')?.value || "",
                        reason_for_change: row.querySelector('[data-history-key="reason_for_change"]')?.value || "",
                        best_psa_response_pct: row.querySelector('[data-history-key="best_psa_response_pct"]')?.value || "",
                    };
                }
                const payload = {
                    sample_date: row.querySelector('[data-history-key="sample_date"]')?.value || "",
                    context: row.querySelector('[data-history-key="context"]')?.value || "otro",
                    line_of_therapy_number: row.querySelector('[data-history-key="line_of_therapy_number"]')?.value || "",
                    line_of_therapy_context: row.querySelector('[data-history-key="line_of_therapy_context"]')?.value || "",
                    source: row.querySelector('[data-history-key="source"]')?.value || "",
                };
                if (kind === "testosterone") {
                    return {
                        ...payload,
                        testosterone_value: row.querySelector('[data-history-key="testosterone_value"]')?.value || "",
                        unit: row.querySelector('[data-history-key="unit"]')?.value || "ng/dL",
                    };
                }
                return {
                    ...payload,
                    psa_value: row.querySelector('[data-history-key="psa_value"]')?.value || "",
                    assay_type: row.querySelector('[data-history-key="assay_type"]')?.value || "desconocido",
                };
            }).filter((row) => {
                if (kind === "prior_lines") {
                    return row.start_date || row.drug_scheme || row.line_of_therapy_number;
                }
                if (kind === "testosterone") {
                    return row.sample_date || row.testosterone_value || row.source || row.line_of_therapy_number || row.line_of_therapy_context;
                }
                return row.sample_date || row.psa_value || row.source || row.line_of_therapy_number || row.line_of_therapy_context;
            });
            hidden.value = JSON.stringify(rows);
            const summary = wrapper.querySelector(sel.summary);
            if (summary) {
                if (kind === "prior_lines") {
                    summary.textContent = rows.length
                        ? `${rows.length} línea(s) terapéutica(s) previa(s) lista(s) para alimentar treatments[].`
                        : "Sin líneas previas; los campos most_recent_prior_line_* seguirán siendo el origen canónico.";
                } else {
                    summary.textContent = rows.length
                        ? `${rows.length} medición(es) listas para guardarse en la serie longitudinal.`
                        : "Sin mediciones adicionales; el basal seguirá siendo el punto canónico principal.";
                }
            }
        });
    }

    function bindHistoryField(scope, kind) {
        // Faubot LXVI #63C — usa _selectorsForKind centralizado (3 kinds)
        const sel = _selectorsForKind(kind);
        const addSelector = sel.add;
        const wrapperSelector = sel.wrapper;
        const rowsSelector = sel.rows;
        const rowSelector = sel.row;
        const removeSelector = sel.remove;
        const clickBoundKey = sel.clickKey;

        scope.querySelectorAll(addSelector).forEach((button) => {
            if (button.dataset.bound === "true") {
                return;
            }
            button.dataset.bound = "true";
            button.addEventListener("click", () => {
                const wrapper = button.closest(wrapperSelector);
                const rowsContainer = wrapper?.querySelector(rowsSelector);
                if (!rowsContainer) {
                    return;
                }
                rowsContainer.insertAdjacentHTML("beforeend", renderHistoryRows(kind, [{}]));
                syncHistoryField(scope, kind);
                window.clinicalSelects?.syncAll(rowsContainer);
                bindHistoryField(scope, kind);
            });
        });

        if (scope.dataset[clickBoundKey] !== "true") {
            scope.dataset[clickBoundKey] = "true";
            scope.addEventListener("click", (event) => {
                const target = event.target;
                if (!(target instanceof HTMLElement) || !target.matches(removeSelector)) {
                    return;
                }
                const row = target.closest(rowSelector) || target.closest(".grid");
                const container = target.closest(wrapperSelector)?.querySelector(rowsSelector);
                if (!container) {
                    return;
                }
                const allRows = container.querySelectorAll(rowSelector);
                if (allRows.length <= 1) {
                    row?.querySelectorAll("input").forEach((input) => {
                        input.value = "";
                    });
                    row?.querySelectorAll("select").forEach((select) => {
                        select.selectedIndex = 0;
                    });
                } else {
                    row?.remove();
                }
                syncHistoryField(scope, kind);
            });
        }

        scope.querySelectorAll(wrapperSelector).forEach((wrapper) => {
            wrapper.querySelectorAll("input, select").forEach((input) => {
                if (input.dataset.boundChange === "true") {
                    return;
                }
                input.dataset.boundChange = "true";
                input.addEventListener("change", () => syncHistoryField(scope, kind));
                input.addEventListener("input", () => syncHistoryField(scope, kind));
            });
        });

        syncHistoryField(scope, kind);
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

    function bindAnthropometricDerivations(scope, fieldNames = {}) {
        const weightName = fieldNames.weightName || "weight_kg";
        const heightName = fieldNames.heightName || "height_cm";
        const bmiName = fieldNames.bmiName || "bmi_current";
        const sync = () => {
            const weightInput = scope.querySelector(`[name="${weightName}"]`);
            const heightInput = scope.querySelector(`[name="${heightName}"]`);
            const bmiInput = scope.querySelector(`[name="${bmiName}"]`);
            if (bmiInput instanceof HTMLInputElement) {
                bmiInput.readOnly = true;
                bmiInput.value = calculateBmi(weightInput?.value || "", heightInput?.value || "");
            }
        };
        [weightName, heightName].forEach((fieldName) => {
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

    window.ProstaNetLongitudinalCaptureHelpers = {
        parseHistoryValue,
        renderHistoryRows,
        syncHistoryField,
        bindHistoryField,
        calculateBmi,
        bindAnthropometricDerivations,
        // Faubot LXVI #63C — exponer renderer especializado prior_lines
        renderPriorLinesHistoryRows,
    };
})();
