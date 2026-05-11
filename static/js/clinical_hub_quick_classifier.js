/* Clinical Hub quick classifier.
 *
 * Official hub capture flow; clinical truth remains in the current
 * StateClassifierService behind /api/state-classifier.
 */
(function () {
  "use strict";

  const root =
    document.getElementById("pm2OfficialClassifier") ||
    document.getElementById("pm2LegacyClassifier");
  const configNode =
    document.getElementById("pm2OfficialClassifierConfig") ||
    document.getElementById("pm2LegacyClassifierConfig");
  if (!root || !configNode) return;

  let config = {};
  try {
    config = JSON.parse(configNode.textContent || "{}");
  } catch (error) {
    console.warn("No se pudo leer la configuración del clasificador oficial.", error);
    return;
  }

  const form = root.querySelector("[data-legacy-classifier-form]");
  const stepsContainer = root.querySelector("[data-legacy-classifier-steps]");
  const statusEl = root.querySelector("[data-legacy-classifier-status]");
  const resultEl = root.querySelector("[data-legacy-classifier-result]");
  const diagnosisEl = root.querySelector("[data-legacy-diagnosis-preview]");
  const stageHintEl = root.querySelector("[data-legacy-stage-hint]");
  const classifyButton = root.querySelector("[data-legacy-classify-now]");
  const resetButton = root.querySelector("[data-legacy-classifier-reset]");

  const state = {
    debounce: null,
    lastPayload: {},
    lastResult: null,
    userTouched: false,
  };

  function escapeHtml(value) {
    if (value === null || value === undefined) return "";
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function fieldValue(name) {
    const target = form.querySelector(`[name="${CSS.escape(name)}"]`);
    return target && !target.disabled ? String(target.value || "") : "";
  }

  function matchesVisibility(rule) {
    if (!rule) return true;
    return Object.entries(rule).every(([name, expected]) => {
      const allowed = Array.isArray(expected) ? expected.map(String) : [String(expected)];
      return allowed.includes(fieldValue(name));
    });
  }

  function optionValue(option) {
    if (option && typeof option === "object") return String(option.value ?? option.label ?? "");
    return String(option ?? "");
  }

  function optionLabel(option) {
    if (option && typeof option === "object") return String(option.label ?? option.value ?? "");
    const raw = String(option ?? "");
    if (raw === "1") return "Sí";
    if (raw === "0") return "No";
    if (!raw) return "Seleccionar";
    return raw;
  }

  function normalizedOptions(field) {
    const optionItems = Array.isArray(field.options) ? field.options : [];
    const displayItems = Array.isArray(field.display_options) ? field.display_options : [];
    let rawOptions = [];
    if (optionItems.length && typeof optionItems[0] === "object") {
      rawOptions = optionItems;
    } else if (displayItems.length) {
      rawOptions = displayItems;
    } else {
      rawOptions = optionItems;
    }
    if (!rawOptions.length && field.field_type === "select") {
      return [{ value: "", label: "Seleccionar" }];
    }
    return rawOptions;
  }

  function createField(field) {
    const wrapper = document.createElement("div");
    wrapper.className = "pm2-legacy-field";
    wrapper.dataset.fieldName = field.name;
    if (field.visible_when) wrapper.dataset.visibleWhen = JSON.stringify(field.visible_when);

    const label = document.createElement("label");
    label.className = "pm2-legacy-field-label";
    label.htmlFor = `legacy-${field.name}`;
    label.textContent = field.label || field.name;
    if (field.required) {
      const marker = document.createElement("span");
      marker.className = "pm2-legacy-required";
      marker.textContent = " *";
      label.appendChild(marker);
    }
    wrapper.appendChild(label);

    const type = String(field.field_type || field.type || "text").toLowerCase();
    let input;
    if (type === "select") {
      input = document.createElement("select");
      input.className = "pm2-legacy-input";
      normalizedOptions(field).forEach((option) => {
        const optionEl = document.createElement("option");
        optionEl.value = optionValue(option);
        optionEl.textContent = optionLabel(option);
        input.appendChild(optionEl);
      });
    } else {
      input = document.createElement("input");
      input.className = "pm2-legacy-input";
      input.type = type === "number" ? "number" : type === "date" ? "date" : "text";
      if (input.type === "number") input.step = "any";
    }
    input.id = `legacy-${field.name}`;
    input.name = field.name;
    input.value = String(config.initial_state?.[field.name] ?? field.default ?? "");
    if (field.required) input.required = true;
    wrapper.appendChild(input);

    if (field.unit || field.help_text) {
      const help = document.createElement("p");
      help.className = "pm2-legacy-help";
      help.textContent = [field.unit ? `Unidad: ${field.unit}` : "", field.help_text || ""]
        .filter(Boolean)
        .join(" · ");
      wrapper.appendChild(help);
    }

    return wrapper;
  }

  function renderSteps() {
    if (!stepsContainer || !form) return;
    stepsContainer.innerHTML = "";
    (config.steps || []).forEach((step) => {
      const section = document.createElement("section");
      section.className = "pm2-legacy-step";
      section.dataset.stepKey = step.key;
      if (step.visible_when) section.dataset.visibleWhen = JSON.stringify(step.visible_when);

      const header = document.createElement("header");
      header.className = "pm2-legacy-step-header";
      header.innerHTML = `
        <span class="pm2-legacy-step-number">${escapeHtml(step.number)}</span>
        <div>
          <h3>${escapeHtml(step.label)}</h3>
          <p>${escapeHtml(step.summary || "")}</p>
        </div>
      `;
      section.appendChild(header);

      const grid = document.createElement("div");
      grid.className = "pm2-legacy-fields-grid";
      (step.fields || []).forEach((field) => grid.appendChild(createField(field)));
      section.appendChild(grid);
      stepsContainer.appendChild(section);
    });
    updateVisibility();
  }

  function updateVisibility() {
    root.querySelectorAll("[data-visible-when]").forEach((el) => {
      let rule = null;
      try {
        rule = JSON.parse(el.dataset.visibleWhen || "{}");
      } catch (_error) {
        rule = null;
      }
      const visible = matchesVisibility(rule);
      el.hidden = !visible;
      el.querySelectorAll("input, select, textarea").forEach((input) => {
        input.disabled = !visible;
      });
    });
  }

  function numberValue(value) {
    const parsed = Number.parseFloat(value);
    return Number.isFinite(parsed) ? parsed : 0;
  }

  function positiveInt(value) {
    const parsed = Number.parseInt(value, 10);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
  }

  function buildEntry(site, count) {
    if (!site || positiveInt(count) <= 0) return null;
    return { site_key: site, site, lesion_count: positiveInt(count), source: "clinical_hub_official_classifier" };
  }

  function normalizePayload(rawPayload) {
    const payload = { ...rawPayload };
    const known = payload.known_cancer_diagnosis === "1";
    const priorLocal = payload.prior_local_therapy || "none";

    payload.prior_prostatectomy = priorLocal === "prostatectomy" ? "1" : "0";
    payload.prior_radiation = ["radiation", "brachytherapy"].includes(priorLocal) ? "1" : "0";

    if (!known) {
      Object.assign(payload, {
        prior_local_therapy: "none",
        prior_prostatectomy: "0",
        prior_radiation: "0",
        bcr_detected: "0",
        bcr2: "0",
        metastatic_disease_known: "0",
        metastasis_site: "M0",
        current_adt_context: "none",
        systemic_progression_context: "none",
        castrate_testosterone_status: "unknown",
        progression_pattern: "biochemical_only",
        conventional_imaging_status: "not_restaged",
      });
    }

    if (!["prostatectomy", "radiation", "brachytherapy"].includes(priorLocal)) {
      payload.bcr_detected = "0";
      payload.bcr2 = "0";
    }
    if (payload.bcr_detected === "1") {
      payload.bcr_confirmed = "1";
      payload.bcr = {
        bcr_detected: "1",
        bcr_psa: payload.bcr_psa || payload.psa_postop || payload.psa_current || "",
        bcr_date: payload.bcr_date || "",
      };
    }
    if (priorLocal === "radiation" || priorLocal === "brachytherapy") {
      payload.phoenix_delta = payload.phoenix_delta || "";
    }

    const metastaticKnown = known && payload.metastatic_disease_known === "1";
    let nodalPresent = metastaticKnown && (payload.nonregional_nodal_metastasis_present === "1" || payload.metastasis_site === "M1a");
    let bonePresent = metastaticKnown && (payload.bone_metastasis_present === "1" || payload.metastasis_site === "M1b");
    let visceralPresent = metastaticKnown && (payload.visceral_metastasis_present === "1" || payload.metastasis_site === "M1c");

    const nodalCount = nodalPresent ? positiveInt(payload.nonregional_nodal_count) : 0;
    const boneAxialCount = bonePresent ? positiveInt(payload.bone_axial_count) : 0;
    const boneAppendicularCount = bonePresent ? positiveInt(payload.bone_appendicular_count) : 0;
    const visceralCount = visceralPresent ? positiveInt(payload.visceral_lesion_count) : 0;
    const totalMetastatic = nodalCount + boneAxialCount + boneAppendicularCount + visceralCount;

    if (!metastaticKnown) {
      nodalPresent = false;
      bonePresent = false;
      visceralPresent = false;
      Object.assign(payload, {
        metastasis_site: "M0",
        metastasis_count: "0",
        metastatic_total_lesion_count: "0",
        nonregional_nodal_metastasis_present: "0",
        nonregional_nodal_count: "0",
        bone_metastasis_present: "0",
        bone_axial_count: "0",
        bone_appendicular_count: "0",
        visceral_metastasis_present: "0",
        visceral_lesion_count: "0",
        metachronous_metastasis: "0",
        nonregional_nodal_site_entries: [],
        bone_site_entries: [],
        visceral_site_entries: [],
      });
    } else {
      payload.nonregional_nodal_metastasis_present = nodalPresent ? "1" : "0";
      payload.bone_metastasis_present = bonePresent ? "1" : "0";
      payload.visceral_metastasis_present = visceralPresent ? "1" : "0";
      payload.nonregional_nodal_count = String(nodalCount);
      payload.bone_axial_count = String(boneAxialCount);
      payload.bone_appendicular_count = String(boneAppendicularCount);
      payload.visceral_lesion_count = String(visceralCount);
      payload.metastatic_total_lesion_count = String(totalMetastatic);
      payload.metastasis_count = String(totalMetastatic);
      payload.metastasis_site = visceralPresent ? "M1c" : bonePresent ? "M1b" : nodalPresent ? "M1a" : "M0";
      payload.nonregional_nodal_site_entries = [
        buildEntry(payload.nonregional_nodal_site, nodalCount),
      ].filter(Boolean);
      payload.bone_site_entries = [
        buildEntry(payload.bone_axial_site, boneAxialCount),
        buildEntry(payload.bone_appendicular_site, boneAppendicularCount),
      ].filter(Boolean);
      payload.visceral_site_entries = [
        buildEntry(payload.visceral_site, visceralCount),
      ].filter(Boolean);
    }

    payload.audit_source = "clinical_hub_official_classifier";
    return payload;
  }

  function collectPayload() {
    const data = Object.fromEntries(new FormData(form).entries());
    return normalizePayload(data);
  }

  function validationError(payload) {
    if (payload.known_cancer_diagnosis !== "1") return "";
    if (payload.metastatic_disease_known !== "1") return "";
    const hasNodal = payload.nonregional_nodal_metastasis_present === "1";
    const hasBone = payload.bone_metastasis_present === "1";
    const hasVisceral = payload.visceral_metastasis_present === "1";
    if (!hasNodal && !hasBone && !hasVisceral) {
      return "Falta composición metastásica documentada: seleccione ganglios no regionales, hueso o víscera.";
    }
    if (hasNodal && positiveInt(payload.nonregional_nodal_count) <= 0) {
      return "Falta distribución ganglionar no regional: capture al menos una lesión.";
    }
    if (hasBone && positiveInt(payload.bone_axial_count) + positiveInt(payload.bone_appendicular_count) <= 0) {
      return "Falta distribución ósea documentada: capture lesiones axiales o apendiculares.";
    }
    if (hasVisceral && positiveInt(payload.visceral_lesion_count) <= 0) {
      return "Falta distribución visceral documentada: capture al menos una lesión visceral.";
    }
    return "";
  }

  function stageKeyForState(stateName) {
    const stateText = String(stateName || "");
    if (["diagnostic_workup", "post_negative_biopsy_followup", "screening"].includes(stateText)) return "diagnostic";
    if (["localized_initial", "focal_therapy", "post_prostatectomy", "post_radiotherapy_followup", "recurrence_bcr", "post_radiotherapy_or_local_salvage"].includes(stateText)) return "localized";
    if (stateText.startsWith("mcspc") || stateText === "adt_progression_verification") return "mcspc";
    if (stateText === "m0_crpc") return "m0crpc";
    if (stateText === "m1_crpc") return "m1crpc";
    if (stateText === "survivorship_and_toxicity_followup") return "palliative";
    return "diagnostic";
  }

  function focusStage(stateName) {
    const stageKey = stageKeyForState(stateName);
    const railButton = document.querySelector(`.pm2-stage-rail-pill[data-stage="${CSS.escape(stageKey)}"]`);
    if (railButton) railButton.click();
    if (stageHintEl) {
      stageHintEl.textContent = `Dominio visible: ${stageKey.toUpperCase()}`;
      stageHintEl.hidden = false;
    }
  }

  function clearStageFocus() {
    const placeholder = document.querySelector("[data-stage-placeholder]");
    document.querySelectorAll(".pm2-stage-rail-pill").forEach((pill) => {
      pill.classList.remove("is-active");
      pill.setAttribute("aria-selected", "false");
    });
    document.querySelectorAll("[data-stage-canvas]").forEach((canvas) => {
      canvas.style.display = "none";
    });
    if (placeholder) placeholder.hidden = false;
    if (window.PM2?.state) window.PM2.state.activeStage = null;
  }

  function renderPending(message) {
    if (!resultEl) return;
    resultEl.hidden = false;
    resultEl.classList.remove("is-success");
    resultEl.innerHTML = `
      <div class="pm2-legacy-result-eyebrow">Clasificación pendiente</div>
      <h3>Datos incompletos</h3>
      <p>${escapeHtml(message)}</p>
    `;
  }

  function renderResult(data, payload) {
    const stateName = data.state || data.disease_state || "diagnostic_workup";
    const label = data.state_label || stateName.replace(/_/g, " ");
    const derived = data.derived_metastatic_context || {};
    const derivedMeta = derived.metastasis_count
      ? `<dl class="pm2-legacy-result-grid">
          <div><dt>Lesiones</dt><dd>${escapeHtml(derived.metastasis_count)}</dd></div>
          <div><dt>Volumen</dt><dd>${escapeHtml(derived.volume_disease || "pendiente")}</dd></div>
          <div><dt>cM</dt><dd>${escapeHtml(derived.m_substage_resolved || payload.metastasis_site || "M0")}</dd></div>
        </dl>`
      : "";
    const gate = data.progression_gate_active
      ? `<div class="pm2-legacy-gate">${escapeHtml(data.progression_gate_reason || "Debe verificarse castración y reestadificación convencional.")}</div>`
      : "";

    resultEl.hidden = false;
    resultEl.classList.add("is-success");
    resultEl.innerHTML = `
      <div class="pm2-legacy-result-eyebrow">Módulo sugerido</div>
      <h3>${escapeHtml(label)}</h3>
      <p>${escapeHtml(data.classification_reason || "El módulo fue seleccionado por el clasificador clínico.")}</p>
      ${derivedMeta}
      ${gate}
      <a class="pm2-btn pm2-btn--primary" href="/wizard/${encodeURIComponent(stateName)}?prefill_source=clinical_hub" data-legacy-wizard-link>
        Abrir asistente correcto
      </a>
    `;
    try {
      window.sessionStorage.setItem(`prostanet:clinical-hub-prefill:${stateName}`, JSON.stringify(payload));
    } catch (error) {
      console.warn("No se pudo persistir el prefill del hub.", error);
    }
    focusStage(stateName);
  }

  function renderDiagnosisPreview(data) {
    if (!diagnosisEl) return;
    const gate = data.clinical_gate || {};
    const missing = gate.missing_fields || data.official_diagnosis_context?.official_diagnosis_missing_fields || [];
    diagnosisEl.hidden = false;
    diagnosisEl.innerHTML = `
      <div class="pm2-legacy-diagnosis-label">Diagnóstico formal</div>
      <div class="pm2-legacy-diagnosis-text">${escapeHtml(data.official_diagnosis || "Diagnóstico pendiente de completar")}</div>
      ${missing.length ? `<div class="pm2-legacy-diagnosis-missing">Faltan: ${missing.map(escapeHtml).join(", ")}</div>` : ""}
    `;
  }

  async function postJson(url, payload) {
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok || data.success === false) {
      throw new Error(data.error || `HTTP ${response.status}`);
    }
    return data;
  }

  async function classifyNow() {
    updateVisibility();
    const payload = collectPayload();
    state.lastPayload = payload;
    const error = validationError(payload);
    if (error) {
      if (statusEl) statusEl.textContent = "";
      renderPending(error);
      return;
    }

    if (statusEl) statusEl.textContent = "Clasificando...";
    try {
      const data = await postJson(config.endpoints?.classify || "/api/state-classifier", payload);
      state.lastResult = data;
      renderResult(data, payload);
      if (payload.known_cancer_diagnosis === "1") {
        try {
          const diagnosisData = await postJson(config.endpoints?.diagnosis_preview || "/api/official-diagnosis/preview", payload);
          renderDiagnosisPreview(diagnosisData);
        } catch (error) {
          if (diagnosisEl) {
            diagnosisEl.hidden = false;
            diagnosisEl.innerHTML = `<div class="pm2-legacy-diagnosis-missing">${escapeHtml(error.message)}</div>`;
          }
        }
      } else if (diagnosisEl) {
        diagnosisEl.hidden = true;
        diagnosisEl.innerHTML = "";
      }
    } catch (error) {
      renderPending(error.message);
    } finally {
      if (statusEl) statusEl.textContent = "";
    }
  }

  function scheduleClassification() {
    state.userTouched = true;
    updateVisibility();
    window.clearTimeout(state.debounce);
    state.debounce = window.setTimeout(classifyNow, 320);
  }

  function resetClassifier() {
    form.reset();
    root.querySelectorAll("input, select").forEach((input) => {
      const name = input.name;
      if (Object.prototype.hasOwnProperty.call(config.initial_state || {}, name)) {
        input.value = String(config.initial_state[name]);
      }
    });
    state.lastPayload = {};
    state.lastResult = null;
    if (resultEl) {
      resultEl.hidden = false;
      resultEl.classList.remove("is-success");
      resultEl.innerHTML = `
        <div class="pm2-legacy-result-eyebrow">Listo para clasificar</div>
        <h3>Defina el escenario real</h3>
        <p>Complete los pasos visibles y el sistema abrirá el asistente correcto.</p>
      `;
    }
    if (diagnosisEl) {
      diagnosisEl.hidden = true;
      diagnosisEl.innerHTML = "";
    }
    if (stageHintEl) stageHintEl.hidden = true;
    clearStageFocus();
    updateVisibility();
  }

  renderSteps();
  resetClassifier();

  form.addEventListener("input", scheduleClassification);
  form.addEventListener("change", scheduleClassification);
  classifyButton?.addEventListener("click", classifyNow);
  resetButton?.addEventListener("click", resetClassifier);

  window.ProstaMedHubOfficialClassifier = {
    collectPayload,
    normalizePayload,
    validationError,
    classifyNow,
    state,
  };
  window.ProstaMedHubLegacyClassifier = window.ProstaMedHubOfficialClassifier;
})();
