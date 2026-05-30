(function () {
  "use strict";

  const STORAGE_KEY = "prostanet:first-real-launch-checklist:v2";
  const TRUE_VALUES = new Set(["1", "true", "yes", "si", "sí"]);
  const KNOWN_STEP_KEYS = [
    "launch_strip_opened",
    "classifier_opened",
    "module_classified",
    "wizard_context_preserved",
    "registration_prepared",
    "real_panel_activated",
    "actor_present",
    "ape_payload_ready",
  ];
  const MIN_VALID_PSA_HISTORY_POINTS = 2;

  function isLaunchMode() {
    const params = new URLSearchParams(window.location.search || "");
    const raw = params.get("real_world_enrollment");
    if (TRUE_VALUES.has(String(raw || "").trim().toLowerCase())) return true;
    return Boolean(
      document.querySelector("[data-real-world-launch-checklist]") ||
      document.querySelector('[data-testid="first-real-wizard-handoff-guard"]')
    );
  }

  function readState() {
    try {
      const parsed = JSON.parse(window.sessionStorage.getItem(STORAGE_KEY) || "{}");
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch (_error) {
      return {};
    }
  }

  function writeState(state) {
    try {
      window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(state || {}));
    } catch (_error) {
      return;
    }
  }

  function statusLabel(status) {
    if (status === "pass") return "Listo";
    if (status === "watch") return "Vigilar";
    if (status === "block") return "Bloqueado";
    return "Pendiente";
  }

  function render() {
    const root = document.querySelector("[data-real-world-launch-checklist]");
    if (!root) return;
    const state = readState();
    const steps = Array.from(root.querySelectorAll("[data-first-real-session-step]"));
    let passed = 0;
    steps.forEach((step) => {
      const key = step.dataset.stepKey || "";
      const entry = state[key] || {};
      const isPass = entry.status === "pass";
      if (isPass) passed += 1;
      step.classList.toggle("is-pass", isPass);
      step.dataset.stepStatus = entry.status || "pending";
      const label = step.querySelector("[data-step-status-label]");
      if (label) label.textContent = statusLabel(entry.status || "pending");
      const evidence = step.querySelector("[data-step-evidence]");
      if (evidence && !evidence.dataset.defaultEvidence) {
        evidence.dataset.defaultEvidence = evidence.textContent || "";
      }
      if (evidence && entry.evidence) evidence.textContent = entry.evidence;
      if (evidence && !entry.evidence) evidence.textContent = evidence.dataset.defaultEvidence || "";
    });
    const progress = root.querySelector("[data-first-real-session-progress]");
    if (progress) {
      progress.textContent = `${passed}/${steps.length} pasos locales`;
    }
  }

  function recordStepStatus(stepKey, status, evidence) {
    if (!stepKey || !isLaunchMode()) return;
    const state = readState();
    state[stepKey] = {
      status: status || "pending",
      evidence: String(evidence || "Paso verificado en esta sesion."),
      known_step: KNOWN_STEP_KEYS.includes(stepKey),
      updated_at: new Date().toISOString(),
    };
    writeState(state);
    render();
  }

  function recordStep(stepKey, evidence) {
    recordStepStatus(stepKey, "pass", evidence);
  }

  function resetState() {
    try {
      window.sessionStorage.removeItem(STORAGE_KEY);
    } catch (_error) {
      return;
    }
    render();
  }

  function parseRows(value) {
    if (!value) return [];
    try {
      const parsed = JSON.parse(value);
      return Array.isArray(parsed) ? parsed : [];
    } catch (_error) {
      return [];
    }
  }

  function numericPsaValue(row) {
    const raw = row?.psa_value ?? row?.value ?? row?.psa ?? row?.ape ?? "";
    const parsed = Number.parseFloat(raw);
    return Number.isFinite(parsed) && parsed >= 0 ? parsed : null;
  }

  function validPsaHistoryRows(form) {
    if (!form) return [];
    const seen = new Set();
    return Array.from(form.querySelectorAll("[data-psa-history-input], [name='psa_history'], [name='ape_history']"))
      .flatMap((input) => parseRows(input.value))
      .filter((row) => {
        const value = numericPsaValue(row);
        const sampleDate = String(row?.sample_date || row?.date || row?.collected_at || "").trim();
        if (value === null || !sampleDate) return false;
        const key = `${sampleDate}|${value}`;
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      });
  }

  function hasPsaHistorySeries(form) {
    return validPsaHistoryRows(form).length >= MIN_VALID_PSA_HISTORY_POINTS;
  }

  function auditWizardRegistrationState() {
    const form = document.getElementById("registrationForm");
    if (!form || !isLaunchMode()) return;
    const phase = document.getElementById("registrationPhase");
    if (phase && !phase.classList.contains("hidden")) {
      recordStep("registration_prepared", "Registro longitudinal visible desde el wizard V2.");
    }
    const panel = form.querySelector("[data-real-world-enrollment-panel]");
    const toggle = panel?.querySelector("[data-real-world-toggle]");
    const actor = panel?.querySelector("[data-real-world-actor]");
    if (toggle?.checked) {
      recordStep("real_panel_activated", "Paciente real activado manualmente; consentimiento humano requerido.");
    }
    if (actor && !actor.disabled && String(actor.value || "").trim()) {
      recordStep("actor_present", "Actor clinico presente antes de finalizar.");
    }
    const validPsaRows = validPsaHistoryRows(form);
    if (validPsaRows.length >= MIN_VALID_PSA_HISTORY_POINTS) {
      recordStep("ape_payload_ready", "Historia APE local lista en el payload longitudinal.");
    } else if (phase && !phase.classList.contains("hidden")) {
      recordStepStatus(
        "ape_payload_ready",
        "watch",
        `Faltan ${MIN_VALID_PSA_HISTORY_POINTS - validPsaRows.length} medicion(es) APE con fecha para cerrar historia longitudinal.`
      );
    }
  }

  function bindClinicalHub() {
    const checklist = document.querySelector("[data-real-world-launch-checklist]");
    if (!checklist || !isLaunchMode()) return;
    recordStep("launch_strip_opened", "Clinical Hub V2 abierto en modo primer real.");
    if ((window.location.hash || "") === "#pm2OfficialClassifier") {
      recordStep("classifier_opened", "Clasificador oficial V2 visible en el launch strip.");
    }
    checklist.querySelector("[data-first-real-launch-reset]")?.addEventListener("click", resetState);
    render();
  }

  function bindWizard() {
    if (!document.querySelector('[data-testid="first-real-wizard-handoff-guard"]') || !isLaunchMode()) return;
    recordStep("wizard_context_preserved", "Wizard V2 abierto con real_world_enrollment=1.");
    const form = document.getElementById("registrationForm");
    if (form) {
      form.addEventListener("input", auditWizardRegistrationState);
      form.addEventListener("change", auditWizardRegistrationState);
    }
    const phase = document.getElementById("registrationPhase");
    if (phase) {
      const observer = new MutationObserver(auditWizardRegistrationState);
      observer.observe(phase, { attributes: true, attributeFilter: ["class"] });
    }
    auditWizardRegistrationState();
  }

  document.addEventListener("DOMContentLoaded", () => {
    bindClinicalHub();
    bindWizard();
  });

  window.ProstaNetFirstRealLaunchChecklist = {
    recordStep,
    recordStepStatus,
    render,
    resetState,
    auditWizardRegistrationState,
    validPsaHistoryRows,
    hasPsaHistorySeries,
    storageKey: STORAGE_KEY,
  };
})();
