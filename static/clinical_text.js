(function (global) {
    const safeRules = [
        [/\bNone ng\/mL\b/g, "No disponible"],
        [/\bNone\b/g, "No disponible"],
        [/\binsufficient_data\b/g, "Datos insuficientes"],
        [/\bIncomplete\b/g, "Incompleto"],
        [/\bactionable\b/g, "Accionable"],
        [/\bnot_applicable\b/g, "No aplica"],
        [/\bcurrent_db\b/g, "base actual"],
        [/\bisolated_temp_db\b/g, "base temporal aislada"],
    ];

    function humanize(value) {
        if (typeof value !== "string") {
            return value;
        }
        let text = value;
        for (const [pattern, replacement] of safeRules) {
            text = text.replace(pattern, replacement);
        }
        return text.replace(/\s{2,}/g, " ").trim();
    }

    function normalizeAttribute(element, attribute) {
        const raw = element.getAttribute(attribute);
        if (!raw) {
            return;
        }
        const normalized = humanize(raw);
        if (normalized !== raw) {
            element.setAttribute(attribute, normalized);
        }
    }

    function normalizeDocument(root = document.body) {
        if (!root) {
            return;
        }

        const walker = document.createTreeWalker(
            root,
            NodeFilter.SHOW_TEXT,
            {
                acceptNode(node) {
                    if (!node.nodeValue || !node.nodeValue.trim()) {
                        return NodeFilter.FILTER_REJECT;
                    }
                    const parent = node.parentElement;
                    if (!parent || ["SCRIPT", "STYLE", "NOSCRIPT", "TEXTAREA"].includes(parent.tagName)) {
                        return NodeFilter.FILTER_REJECT;
                    }
                    return NodeFilter.FILTER_ACCEPT;
                },
            },
        );

        const nodes = [];
        while (walker.nextNode()) {
            nodes.push(walker.currentNode);
        }
        for (const node of nodes) {
            const normalized = humanize(node.nodeValue);
            if (normalized !== node.nodeValue) {
                node.nodeValue = normalized;
            }
        }

        root.querySelectorAll("option").forEach((option) => {
            option.textContent = humanize(option.textContent);
        });
        root.querySelectorAll("optgroup[label]").forEach((element) => normalizeAttribute(element, "label"));
        root.querySelectorAll("[placeholder]").forEach((element) => normalizeAttribute(element, "placeholder"));
        root.querySelectorAll("[title]").forEach((element) => normalizeAttribute(element, "title"));
    }

    global.clinicalPresentation = {
        humanize,
        normalizeDocument,
    };
})(window);
