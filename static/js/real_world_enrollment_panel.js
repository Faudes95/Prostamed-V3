(function () {
    function syncPanel(panel) {
        if (!panel) return;
        const toggle = panel.querySelector("[data-real-world-toggle]");
        const actorInput = panel.querySelector("[data-real-world-actor]");
        const consentFlag = panel.querySelector("[data-real-world-consent-flag]");
        const status = panel.querySelector("[data-real-world-status]");
        const enabled = Boolean(toggle?.checked);
        if (consentFlag) {
            consentFlag.value = enabled ? "1" : "0";
        }
        if (actorInput) {
            actorInput.disabled = !enabled;
            actorInput.required = enabled;
            if (!enabled) {
                actorInput.value = "";
            }
        }
        panel.dataset.realWorldEnabled = enabled ? "1" : "0";
        if (status) {
            status.textContent = enabled
                ? "Modo real: requiere firma, actor clínico y quedará incluido en la compuerta real-only."
                : "Modo QA/sintético: no contará para evidencia hospitalaria.";
            status.className = enabled
                ? "rounded-2xl border border-emerald-400/30 bg-emerald-500/10 p-3 text-xs text-emerald-100"
                : "rounded-2xl border border-slate-800 bg-slate-950/60 p-3 text-xs text-slate-300";
        }
    }

    function bindPanel(panel) {
        if (!panel || panel.dataset.bound === "true") return;
        panel.dataset.bound = "true";
        panel.querySelector("[data-real-world-toggle]")?.addEventListener("change", () => syncPanel(panel));
        syncPanel(panel);
    }

    function syncForm(form) {
        form?.querySelectorAll("[data-real-world-enrollment-panel]").forEach(syncPanel);
    }

    function bindAll(root = document) {
        root.querySelectorAll("[data-real-world-enrollment-panel]").forEach(bindPanel);
    }

    document.addEventListener("DOMContentLoaded", () => bindAll());

    window.ProstaNetRealWorldEnrollment = {
        bindAll,
        syncForm,
    };
})();
