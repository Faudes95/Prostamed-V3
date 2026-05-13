/* ─────────────────────────────────────────────────────────────────────────
 * ProstaMed Clinical Intelligence v2 — JS interactivity layer
 * Faubot 2026-04-26 LXXVII (#67D demo)
 *
 * Vanilla JS singleton. No framework. Compatible con Jinja2 + Tailwind CDN.
 * Provee: drawer state machine, drill-down lateral panel, Chart.js builders
 * (timeline 4-capas, sparklines, heatmap), keyboard nav, focus trap,
 * lazy bento via IntersectionObserver, content-visibility virtualization.
 *
 * Uso: window.PM2.openDrawer('audit') / PM2.showDrillDown({...})
 * ───────────────────────────────────────────────────────────────────────── */

(function (global) {
    "use strict";

    const PM2 = {
        version: "2026-04-26 LXXVII",
        state: {
            activeDrawer: null,
            activeDrillDown: null,
            activeStage: null,
            charts: new Map(),
            focusReturnTo: null,
        },
    };

    // ── Helpers ──────────────────────────────────────────────────────────────
    PM2.formatPsa = (v) => {
        if (v == null || isNaN(v)) return "—";
        return Number(v).toFixed(v < 1 ? 2 : 1);
    };

    PM2.formatDate = (iso) => {
        if (!iso) return "—";
        const d = new Date(iso);
        if (isNaN(d.getTime())) return iso;
        return d.toLocaleDateString("es-MX", { year: "numeric", month: "short", day: "2-digit" });
    };

    PM2.formatMonths = (m) => {
        if (m == null || isNaN(m)) return "—";
        if (m < 1) return `${Math.round(m * 30)}d`;
        if (m < 12) return `${m.toFixed(1)} m`;
        return `${(m / 12).toFixed(1)} a`;
    };

    PM2.severityColor = (sev) => {
        const map = {
            critical: "#dc2626", hard_block: "#dc2626",
            warning: "#f59e0b", soft_warning: "#f59e0b",
            info: "#06b6d4", informational: "#06b6d4",
            success: "#10b981", neutral: "#64748b",
        };
        return map[sev] || "#64748b";
    };

    PM2.regimenColor = (cls) => {
        const map = {
            ADT: "#1a6fc4",
            ARPI: "#06b6d4",
            TAXANE: "#6366f1",
            PARP: "#a855f7",
            LUTETIUM: "#8b5cf6",
            BONE_TARGETED: "#ec4899",
            IO: "#10b981",
            OBSERVATION: "#64748b",
        };
        return map[cls] || "#64748b";
    };

    // ── Focus trap utility ───────────────────────────────────────────────────
    const FOCUSABLE_SELECTOR = [
        "a[href]", "button:not([disabled])", "textarea:not([disabled])",
        "input:not([disabled])", "select:not([disabled])", "[tabindex]:not([tabindex='-1'])"
    ].join(",");

    PM2.trapFocus = (container) => {
        const focusable = container.querySelectorAll(FOCUSABLE_SELECTOR);
        if (focusable.length === 0) return () => {};
        const first = focusable[0];
        const last = focusable[focusable.length - 1];

        const handler = (e) => {
            if (e.key !== "Tab") return;
            if (e.shiftKey && document.activeElement === first) {
                e.preventDefault();
                last.focus();
            } else if (!e.shiftKey && document.activeElement === last) {
                e.preventDefault();
                first.focus();
            }
        };
        container.addEventListener("keydown", handler);
        return () => container.removeEventListener("keydown", handler);
    };

    // ── Drawer (audit) ───────────────────────────────────────────────────────
    PM2.openDrawer = (drawerId) => {
        const drawer = document.getElementById(drawerId);
        const backdrop = document.getElementById(`${drawerId}-backdrop`);
        if (!drawer) return;

        PM2.state.focusReturnTo = document.activeElement;
        drawer.classList.add("is-open");
        if (backdrop) backdrop.classList.add("is-open");
        drawer.setAttribute("aria-hidden", "false");
        PM2.state.activeDrawer = drawerId;

        // Trap focus
        const release = PM2.trapFocus(drawer);
        drawer._focusRelease = release;
        const firstFocusable = drawer.querySelector(FOCUSABLE_SELECTOR);
        firstFocusable?.focus();

        document.body.style.overflow = "hidden";
    };

    PM2.closeDrawer = () => {
        const drawerId = PM2.state.activeDrawer;
        if (!drawerId) return;
        const drawer = document.getElementById(drawerId);
        const backdrop = document.getElementById(`${drawerId}-backdrop`);
        if (!drawer) return;

        drawer.classList.remove("is-open");
        if (backdrop) backdrop.classList.remove("is-open");
        drawer.setAttribute("aria-hidden", "true");
        if (drawer._focusRelease) drawer._focusRelease();
        PM2.state.focusReturnTo?.focus();
        PM2.state.activeDrawer = null;
        document.body.style.overflow = "";
    };

    // ── Drawer tabs ──────────────────────────────────────────────────────────
    PM2.bindDrawerTabs = (drawerId) => {
        const drawer = document.getElementById(drawerId);
        if (!drawer) return;
        const tabs = drawer.querySelectorAll(".pm2-drawer-tab");
        const panels = drawer.querySelectorAll(".pm2-drawer-tab-panel");

        tabs.forEach((tab) => {
            tab.addEventListener("click", () => {
                const target = tab.dataset.tab;
                tabs.forEach((t) => {
                    t.classList.toggle("is-active", t === tab);
                    t.setAttribute("aria-selected", t === tab ? "true" : "false");
                });
                panels.forEach((p) => {
                    p.classList.toggle("is-active", p.dataset.panel === target);
                });
            });
        });
    };

    // ── Drill-down lateral panel ────────────────────────────────────────────
    PM2.showDrillDown = ({ context, title, html }) => {
        const panel = document.getElementById("pm2-drilldown");
        if (!panel) return;
        const ctxEl = panel.querySelector("[data-drilldown-context]");
        const titleEl = panel.querySelector("[data-drilldown-title]");
        const bodyEl = panel.querySelector("[data-drilldown-body]");
        if (ctxEl) ctxEl.textContent = context || "";
        if (titleEl) titleEl.textContent = title || "";
        if (bodyEl) bodyEl.innerHTML = html || "";
        PM2.state.focusReturnTo = document.activeElement;
        panel.classList.add("is-open");
        panel.setAttribute("aria-hidden", "false");
        PM2.state.activeDrillDown = true;
        const closeBtn = panel.querySelector("[data-drilldown-close]");
        closeBtn?.focus();
    };

    PM2.hideDrillDown = () => {
        const panel = document.getElementById("pm2-drilldown");
        if (!panel) return;
        panel.classList.remove("is-open");
        panel.setAttribute("aria-hidden", "true");
        PM2.state.activeDrillDown = false;
        PM2.state.focusReturnTo?.focus();
    };

    // ── Global ESC binding ──────────────────────────────────────────────────
    PM2.bindEscClose = () => {
        document.addEventListener("keydown", (e) => {
            if (e.key !== "Escape") return;
            if (PM2.state.activeDrillDown) PM2.hideDrillDown();
            else if (PM2.state.activeDrawer) PM2.closeDrawer();
        });
    };

    // ── Backdrop click closes drawer ───────────────────────────────────────
    PM2.bindBackdropClose = () => {
        document.querySelectorAll(".pm2-drawer-backdrop").forEach((bd) => {
            bd.addEventListener("click", () => PM2.closeDrawer());
        });
    };

    // ── Stage rail navigator ───────────────────────────────────────────────
    PM2.bindStageRail = () => {
        const rail = document.querySelector("[data-stage-rail]");
        if (!rail) return;
        const pills = rail.querySelectorAll(".pm2-stage-rail-pill");
        const canvases = document.querySelectorAll("[data-stage-canvas]");
        const placeholder = document.querySelector("[data-stage-placeholder]");

        const activate = (stage) => {
            if (placeholder) placeholder.hidden = true;
            pills.forEach((p) => p.classList.toggle("is-active", p.dataset.stage === stage));
            pills.forEach((p) => p.setAttribute("aria-selected", p.dataset.stage === stage ? "true" : "false"));
            canvases.forEach((c) => {
                if (c.dataset.stageCanvas === stage) {
                    c.style.display = "";
                    c.style.animation = "none";
                    void c.offsetWidth;
                    c.style.animation = "";
                } else {
                    c.style.display = "none";
                }
            });
            PM2.state.activeStage = stage;
            // Persist via URL hash
            history.replaceState(null, "", `#${stage}`);
        };

        pills.forEach((pill) => {
            pill.addEventListener("click", (e) => {
                e.preventDefault();
                activate(pill.dataset.stage);
                pill.focus();
            });
            pill.addEventListener("keydown", (e) => {
                const idx = Array.from(pills).indexOf(pill);
                if (e.key === "ArrowDown") {
                    e.preventDefault();
                    pills[(idx + 1) % pills.length].focus();
                    pills[(idx + 1) % pills.length].click();
                } else if (e.key === "ArrowUp") {
                    e.preventDefault();
                    pills[(idx - 1 + pills.length) % pills.length].focus();
                    pills[(idx - 1 + pills.length) % pills.length].click();
                } else if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    activate(pill.dataset.stage);
                }
            });
        });

        // Honour URL hash on load
        const initial = window.location.hash?.slice(1);
        if (initial && rail.querySelector(`[data-stage="${initial}"]`)) {
            activate(initial);
        } else {
            pills.forEach((p) => {
                p.classList.remove("is-active");
                p.setAttribute("aria-selected", "false");
            });
            canvases.forEach((c) => {
                c.style.display = "none";
            });
            if (placeholder) placeholder.hidden = false;
        }
    };

    // ── Alert filter chips ─────────────────────────────────────────────────
    PM2.bindAlertFilters = (containerSelector) => {
        const container = document.querySelector(containerSelector);
        if (!container) return;
        const chips = container.querySelectorAll(".pm2-filter-chip");
        const cards = container.querySelectorAll(".pm2-alert-card");
        let active = "all";

        chips.forEach((chip) => {
            chip.addEventListener("click", () => {
                active = chip.dataset.filter;
                chips.forEach((c) => c.classList.toggle("is-active", c === chip));
                cards.forEach((card) => {
                    const matches = active === "all"
                        || card.dataset.severity === active
                        || card.dataset.category === active;
                    card.style.display = matches ? "" : "none";
                });
            });
        });
    };

    // ── Lazy bento + sparkline init via IntersectionObserver ─────────────
    // Fallback eager init: si el elemento NO entra en viewport en los primeros
    // 600ms (típico en demos densos donde todo está fuera de fold inicial),
    // se inicializa anyway. Garantiza que charts aparezcan sin scroll.
    PM2.observeLazy = () => {
        const initEl = (el) => {
            if (el.dataset.loaded === "true") return;
            el.dataset.loaded = "true";
            const initFn = el.dataset.init;
            if (initFn && typeof PM2[initFn] === "function") {
                try { PM2[initFn](el); } catch (err) { console.warn("[PM2] init err", initFn, err); }
            }
        };

        const targets = document.querySelectorAll("[data-init]");

        if (!("IntersectionObserver" in window)) {
            targets.forEach(initEl);
            return;
        }

        const observer = new IntersectionObserver((entries) => {
            entries.forEach((entry) => {
                if (entry.isIntersecting) {
                    initEl(entry.target);
                    observer.unobserve(entry.target);
                }
            });
        }, { rootMargin: "200px" });

        targets.forEach((el) => observer.observe(el));

        // Eager fallback: cualquier elemento que no haya cargado en 600ms
        // (porque está fuera de viewport y el usuario no scrollea) se inicia.
        setTimeout(() => {
            targets.forEach((el) => {
                if (el.dataset.loaded !== "true") {
                    initEl(el);
                    observer.unobserve(el);
                }
            });
        }, 600);
    };

    // ── Chart.js helpers ───────────────────────────────────────────────────
    PM2.chartCommon = () => ({
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 320, easing: "easeOutCubic" },
        plugins: {
            legend: { display: false },
            tooltip: {
                backgroundColor: "rgba(2, 6, 23, 0.95)",
                borderColor: "rgba(6, 182, 212, 0.4)",
                borderWidth: 1,
                titleColor: "#f0fbff",
                bodyColor: "#cbd5e1",
                padding: 10,
                cornerRadius: 8,
                titleFont: { family: "Avenir Next, system-ui", size: 12, weight: "700" },
                bodyFont: { family: "Avenir Next, system-ui", size: 12 },
            },
        },
        scales: {
            x: {
                grid: { color: "rgba(30, 41, 59, 0.5)", borderColor: "rgba(30, 41, 59, 0.7)" },
                ticks: { color: "#94a3b8", font: { family: "Avenir Next, system-ui", size: 10 } },
            },
            y: {
                grid: { color: "rgba(30, 41, 59, 0.4)", borderColor: "rgba(30, 41, 59, 0.7)" },
                ticks: { color: "#94a3b8", font: { family: "Avenir Next, system-ui", size: 10 } },
            },
        },
    });

    // Combined PSA Timeline (4 capas: PSA + forecast per-line + cohort + events)
    PM2.buildTimelineChart = (canvasEl) => {
        if (!canvasEl || !window.Chart) return;
        const data = JSON.parse(canvasEl.dataset.payload || "{}");
        const ctx = canvasEl.getContext("2d");

        const psaPoints = (data.psa_points || []).map((p) => ({ x: p.date, y: p.value, line: p.line, label: p.label }));
        const forecastByLine = data.forecast_per_line || {};
        const cohortP25 = (data.cohort_p25 || []).map((p) => ({ x: p.date, y: p.value }));
        const cohortP75 = (data.cohort_p75 || []).map((p) => ({ x: p.date, y: p.value }));
        const cohortMedian = (data.cohort_median || []).map((p) => ({ x: p.date, y: p.value }));
        const treatmentBands = data.treatment_bands || [];
        const events = data.events || [];
        const thresholds = data.thresholds || [];

        // Build datasets
        const datasets = [];

        // Cohort P75 (top boundary, no fill)
        if (cohortP75.length) {
            datasets.push({
                label: "Cohorte P75",
                data: cohortP75,
                borderColor: "rgba(148, 163, 184, 0.4)",
                borderWidth: 1,
                borderDash: [3, 3],
                pointRadius: 0,
                fill: "+1",
                backgroundColor: "rgba(148, 163, 184, 0.07)",
                tension: 0.25,
            });
        }
        if (cohortP25.length) {
            datasets.push({
                label: "Cohorte P25",
                data: cohortP25,
                borderColor: "rgba(148, 163, 184, 0.4)",
                borderWidth: 1,
                borderDash: [3, 3],
                pointRadius: 0,
                fill: false,
                tension: 0.25,
            });
        }
        if (cohortMedian.length) {
            datasets.push({
                label: "Cohorte mediana",
                data: cohortMedian,
                borderColor: "rgba(148, 163, 184, 0.85)",
                borderWidth: 1.5,
                borderDash: [6, 4],
                pointRadius: 0,
                fill: false,
                tension: 0.25,
            });
        }

        // PSA real measurements (per line color)
        datasets.push({
            label: "PSA paciente",
            data: psaPoints,
            borderColor: "#06b6d4",
            borderWidth: 2.5,
            backgroundColor: "rgba(6, 182, 212, 0.12)",
            pointRadius: 4,
            pointBackgroundColor: psaPoints.map((p) => PM2.regimenColor((p.line && p.line.cls) || "ADT")),
            pointBorderColor: "#020617",
            pointBorderWidth: 1.5,
            pointHoverRadius: 6,
            tension: 0.2,
            fill: false,
        });

        // Per-line forecast (dashed)
        Object.entries(forecastByLine).forEach(([lineNum, fcast]) => {
            datasets.push({
                label: `Forecast L${lineNum}`,
                data: (fcast.points || []).map((p) => ({ x: p.date, y: p.value })),
                borderColor: PM2.regimenColor(fcast.regimen_class),
                borderWidth: 2,
                borderDash: [5, 4],
                pointRadius: 0,
                fill: false,
                tension: 0.3,
            });
        });

        // Annotations (treatment bands as boxes + events as lines + thresholds)
        const annotations = {};
        treatmentBands.forEach((band, i) => {
            annotations[`band_${i}`] = {
                type: "box",
                xMin: band.start_date,
                xMax: band.end_date,
                yMin: 0,
                yMax: 0.05,
                yScaleID: "y",
                xScaleID: "x",
                backgroundColor: PM2.regimenColor(band.regimen_class) + "55",
                borderColor: PM2.regimenColor(band.regimen_class),
                borderWidth: 1,
                label: {
                    content: band.label,
                    display: true,
                    position: "start",
                    color: "#f0fbff",
                    font: { size: 9, weight: "600" },
                    backgroundColor: "rgba(2,6,23,0.7)",
                    padding: 3,
                },
            };
        });
        events.forEach((ev, i) => {
            annotations[`event_${i}`] = {
                type: "line",
                xMin: ev.date, xMax: ev.date,
                borderColor: PM2.severityColor(ev.severity),
                borderWidth: 1.5,
                borderDash: [2, 4],
                label: {
                    content: ev.label,
                    display: true,
                    position: "start",
                    color: PM2.severityColor(ev.severity),
                    font: { size: 9, weight: "700" },
                    backgroundColor: "rgba(2,6,23,0.85)",
                    padding: 3,
                },
            };
        });
        thresholds.forEach((th, i) => {
            annotations[`th_${i}`] = {
                type: "line",
                yMin: th.value, yMax: th.value,
                borderColor: PM2.severityColor(th.severity),
                borderWidth: 1.2,
                borderDash: [4, 6],
                label: {
                    content: th.label,
                    display: true,
                    position: "end",
                    color: PM2.severityColor(th.severity),
                    font: { size: 9, weight: "600" },
                    backgroundColor: "rgba(2,6,23,0.85)",
                    padding: 3,
                },
            };
        });

        const opts = PM2.chartCommon();
        opts.scales.x.type = "time";
        opts.scales.x.time = { unit: "month", displayFormats: { month: "MMM yy" } };
        opts.scales.y.title = { display: true, text: "PSA (ng/mL)", color: "#cbd5e1", font: { size: 11 } };
        opts.plugins.annotation = { annotations };
        opts.plugins.legend = {
            display: false,
        };
        opts.plugins.tooltip.callbacks = {
            label: (ctx) => `${ctx.dataset.label}: ${PM2.formatPsa(ctx.parsed.y)} ng/mL`,
        };
        opts.onClick = (e, elements) => {
            if (!elements || !elements.length) return;
            const el = elements[0];
            const ds = canvasEl._chart?.data.datasets[el.datasetIndex];
            if (!ds) return;
            const point = ds.data[el.index];
            PM2.showDrillDown({
                context: "PUNTO PSA",
                title: `${PM2.formatDate(point.x)} · ${PM2.formatPsa(point.y)} ng/mL`,
                html: `<p class="pm2-card-subtitle">Click en banda de tratamiento o marcador clínico para ver kinetics granulares por línea de terapia.</p>`,
            });
        };

        const chart = new Chart(ctx, {
            type: "line",
            data: { datasets },
            options: opts,
        });
        canvasEl._chart = chart;
        PM2.state.charts.set(canvasEl.id, chart);
    };

    // KPI sparkline mini
    PM2.buildKpiSparkline = (canvasEl) => {
        if (!canvasEl || !window.Chart) return;
        const data = JSON.parse(canvasEl.dataset.payload || "[]");
        const ctx = canvasEl.getContext("2d");
        const trend = canvasEl.dataset.trend || "info";
        const colorMap = { up: "#dc2626", down: "#10b981", flat: "#64748b", info: "#06b6d4" };
        const color = colorMap[trend] || "#06b6d4";

        new Chart(ctx, {
            type: "line",
            data: {
                labels: data.map((_, i) => i),
                datasets: [{
                    data, borderColor: color, borderWidth: 1.5,
                    fill: true, backgroundColor: color + "22",
                    pointRadius: 0, tension: 0.3,
                }],
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                plugins: { legend: { display: false }, tooltip: { enabled: false } },
                scales: { x: { display: false }, y: { display: false } },
                animation: { duration: 0 },
            },
        });
    };

    // Donut (cohort distribution)
    PM2.buildDonut = (canvasEl) => {
        if (!canvasEl || !window.Chart) return;
        const data = JSON.parse(canvasEl.dataset.payload || "{}");
        const ctx = canvasEl.getContext("2d");
        new Chart(ctx, {
            type: "doughnut",
            data: {
                labels: data.labels,
                datasets: [{
                    data: data.values,
                    backgroundColor: data.colors,
                    borderColor: "#020617",
                    borderWidth: 2,
                    hoverOffset: 8,
                }],
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                cutout: "62%",
                plugins: {
                    legend: {
                        display: true, position: "right",
                        labels: { color: "#cbd5e1", font: { family: "Avenir Next, system-ui", size: 11 }, boxWidth: 12, boxHeight: 12, padding: 10 },
                    },
                    tooltip: {
                        backgroundColor: "rgba(2, 6, 23, 0.95)",
                        borderColor: "rgba(6, 182, 212, 0.4)", borderWidth: 1,
                        titleColor: "#f0fbff", bodyColor: "#cbd5e1",
                        callbacks: { label: (ctx) => `${ctx.label}: ${ctx.parsed} pacientes` },
                    },
                },
            },
        });
    };

    // Bar chart (Gleason histogram, ECOG, etc.)
    PM2.buildBar = (canvasEl) => {
        if (!canvasEl || !window.Chart) return;
        const data = JSON.parse(canvasEl.dataset.payload || "{}");
        const ctx = canvasEl.getContext("2d");
        const opts = PM2.chartCommon();
        new Chart(ctx, {
            type: "bar",
            data: {
                labels: data.labels,
                datasets: [{
                    data: data.values,
                    backgroundColor: data.colors || data.values.map(() => "rgba(6, 182, 212, 0.55)"),
                    borderColor: data.colors || data.values.map(() => "#06b6d4"),
                    borderWidth: 1,
                    borderRadius: 4,
                }],
            },
            options: opts,
        });
    };

    // PSA Kinetics Heatmap (custom canvas, no Chart.js)
    PM2.buildHeatmap = (containerEl) => {
        const data = JSON.parse(containerEl.dataset.payload || "{}");
        const patients = data.patients || [];
        const timebins = data.timebins || [];
        if (!patients.length || !timebins.length) return;

        const cell = 16, gap = 2;
        const padX = 80, padY = 24;
        const w = padX + timebins.length * (cell + gap);
        const h = padY + patients.length * (cell + gap);

        const canvas = document.createElement("canvas");
        canvas.width = w * (window.devicePixelRatio || 1);
        canvas.height = h * (window.devicePixelRatio || 1);
        canvas.style.width = w + "px";
        canvas.style.height = h + "px";
        canvas.setAttribute("aria-label", "PSA velocity heatmap por paciente");
        const ctx = canvas.getContext("2d");
        ctx.scale(window.devicePixelRatio || 1, window.devicePixelRatio || 1);
        ctx.font = "10px 'Avenir Next', system-ui";
        ctx.fillStyle = "#94a3b8";

        // X axis labels (months)
        timebins.forEach((m, i) => {
            const x = padX + i * (cell + gap) + cell / 2;
            ctx.textAlign = "center";
            ctx.fillText(m, x, 14);
        });

        // Cells
        patients.forEach((row, ri) => {
            ctx.textAlign = "right";
            ctx.fillStyle = "#cbd5e1";
            ctx.fillText(row.id, padX - 6, padY + ri * (cell + gap) + cell - 4);
            row.values.forEach((v, ci) => {
                const color = PM2.heatColor(v);
                ctx.fillStyle = color;
                ctx.fillRect(padX + ci * (cell + gap), padY + ri * (cell + gap), cell, cell);
            });
        });

        containerEl.innerHTML = "";
        containerEl.appendChild(canvas);
    };

    PM2.heatColor = (v) => {
        if (v == null) return "#1e293b";
        // v = PSA velocity; -1 = down (good), 0 = flat, +1+ = up (bad)
        if (v < -0.3) return "#10b981";       // green
        if (v < 0) return "#34d399";          // light green
        if (v < 0.2) return "#64748b";        // neutral gray
        if (v < 0.5) return "#fbbf24";        // amber
        if (v < 1) return "#f59e0b";          // orange
        if (v < 2) return "#ef4444";          // red
        return "#dc2626";                     // dark red
    };

    // ── Intake form: live staging classifier preview + presets ───────────────
    PM2.bindIntakeForm = () => {
        const form = document.querySelector("[data-intake-form]");
        if (!form) return;

        const update = () => {
            const fd = new FormData(form);
            const data = {};
            for (const [k, v] of fd.entries()) {
                if (data[k] !== undefined) {
                    data[k] = [].concat(data[k], v);
                } else {
                    data[k] = v;
                }
            }
            // Also collect unchecked checkboxes as false
            form.querySelectorAll("input[type=checkbox]").forEach((cb) => {
                if (!data[cb.name]) data[cb.name] = cb.checked;
            });

            const result = PM2.classifyStage(data);
            PM2.renderStagingPreview(result, data);
            PM2.applyConditionalFields(data);
            PM2.updateProgressRail(data);
        };

        // Bind to all inputs
        form.querySelectorAll("input, select, textarea").forEach((el) => {
            el.addEventListener("input", update);
            el.addEventListener("change", update);
        });

        // Bind preset cards
        document.querySelectorAll("[data-preset]").forEach((card) => {
            card.addEventListener("click", () => {
                const preset = card.dataset.preset;
                PM2.applyPreset(preset, form);
                update();
            });
        });

        // Initial render
        update();
    };

    // Heuristic stage classifier — mirrors prostanet/domains/state_classifier
    PM2.classifyStage = (d) => {
        const knowsCancer = d.known_cancer_diagnosis;
        if (!knowsCancer || knowsCancer === "no") {
            return { stage: "diagnostic", label: "Diagnóstico", sub: "Sin biopsia confirmada · workup", color: "var(--stage-diagnostic)" };
        }
        if (knowsCancer === "suspected_no_biopsy") {
            return { stage: "diagnostic", label: "Screening", sub: "Sospecha · pre-biopsia", color: "var(--stage-diagnostic)" };
        }

        const isCRPC = d.systemic_progression_context === "confirmed_crpc"
                    || (d.castrate_testosterone_status === "confirmed" && d.progression_pattern && d.progression_pattern !== "");
        const hasMets = d.metastatic_disease_known === "yes"
                     || d.conventional_imaging_status === "M1";

        if (isCRPC) {
            if (hasMets) return { stage: "m1crpc", label: "m1CRPC", sub: "Castración resistente metastásico", color: "var(--stage-m1crpc)" };
            if (d.conventional_imaging_status === "M0") return { stage: "m0crpc", label: "m0CRPC", sub: "CRPC sin mets convencionales", color: "var(--stage-m0crpc)" };
            return { stage: "m1crpc", label: "CRPC · staging gap", sub: "Falta M-staging (PSMA-PET indicado)", color: "var(--stage-m1crpc)" };
        }

        if (hasMets) {
            // Determine HV vs LV (CHAARTED criteria)
            const boneCount = parseInt(d.bone_lesion_count || "0", 10);
            const hasVisceral = !!d.mets_visceral && d.mets_visceral !== "false";
            const hasApendicular = d.bone_apendicular_present === "yes";
            const isHV = (boneCount >= 4 && hasApendicular) || hasVisceral;
            const isMetachronous = d.metachronous_metastasis === "metachronous";
            const isOligo = d.oligometastatic_status && d.oligometastatic_status.startsWith("yes");

            if (isOligo && isMetachronous) {
                return { stage: "mcspc", label: "mCSPC oligo metacrónico", sub: "Trigger MDT/SBRT (STAMPEDE M1|RT)", color: "var(--stage-mcspc)" };
            }
            if (isHV) {
                return { stage: "mcspc", label: isMetachronous ? "mCSPC HV metacrónico" : "mCSPC alto volumen", sub: "CHAARTED HV · doublete/triplete", color: "var(--stage-mcspc)" };
            }
            return { stage: "mcspc", label: "mCSPC bajo volumen", sub: "STAMPEDE arm H · ARPI + ADT", color: "var(--stage-mcspc)" };
        }

        // Post-local
        const hasPriorRP = d.prior_prostatectomy === "yes";
        const hasPriorRT = d.prior_radiation && d.prior_radiation.startsWith("yes");
        const hasBCR = d.bcr_detected && d.bcr_detected.startsWith("yes");

        if (hasBCR) {
            return { stage: "localized", label: "BCR / recurrencia", sub: hasPriorRP ? "Post-RP · salvage workup" : "Post-RT · salvage workup", color: "var(--stage-localized)" };
        }
        if (hasPriorRP) return { stage: "localized", label: "Post-prostatectomía", sub: "Vigilancia · sin BCR", color: "var(--stage-localized)" };
        if (hasPriorRT) return { stage: "localized", label: "Post-radioterapia", sub: "Vigilancia · sin recurrencia", color: "var(--stage-localized)" };

        // Localized initial — apply NCCN risk
        const psa = parseFloat(d.psa_baseline || "0");
        const gp = parseInt(d.gleason_primary || "0", 10);
        const gs = parseInt(d.gleason_secondary || "0", 10);
        const isup = parseInt(d.isup_grade || "0", 10);
        const tstage = (d.clinical_tstage || "").toUpperCase();
        const pctCores = (d.num_cores_positive && d.total_cores)
            ? (parseInt(d.num_cores_positive, 10) / parseInt(d.total_cores, 10) * 100)
            : null;

        if (psa > 0 || gp > 0 || tstage) {
            // Very high
            if (tstage === "T3B" || tstage === "T4" || isup === 5 || (gp === 5 && gs >= 4)) {
                return { stage: "localized", label: "Localizado · MUY ALTO riesgo", sub: "NCCN very high · multimodalidad", color: "#dc2626" };
            }
            if (tstage === "T3A" || isup === 4 || psa > 20) {
                return { stage: "localized", label: "Localizado · ALTO riesgo", sub: "NCCN high · RT+ADT 18-36m o RP", color: "#f43f5e" };
            }
            const irFactors = (psa >= 10 && psa <= 20 ? 1 : 0) + (isup === 2 || isup === 3 ? 1 : 0) + (tstage === "T2B" || tstage === "T2C" ? 1 : 0);
            if (irFactors >= 1) {
                const unfav = (isup === 3) || (irFactors >= 2) || (pctCores != null && pctCores >= 50);
                return {
                    stage: "localized",
                    label: unfav ? "Localizado · INTERMEDIO desfavorable" : "Localizado · INTERMEDIO favorable",
                    sub: unfav ? "RP o RT+ADT corto" : "AS / RP / RT mono",
                    color: "#f59e0b"
                };
            }
            return { stage: "localized", label: "Localizado · BAJO riesgo", sub: "AS recomendado (NCCN PROS-3)", color: "#10b981" };
        }

        return { stage: "diagnostic", label: "Sin clasificar", sub: "Captura datos para clasificar", color: "var(--clinical-neutral)" };
    };

    PM2.renderStagingPreview = (result, data) => {
        const stageEl = document.querySelector("[data-staging-stage]");
        const subEl = document.querySelector("[data-staging-sub]");
        const pillEl = document.querySelector("[data-staging-pill]");
        if (stageEl) stageEl.textContent = result.label;
        if (subEl) subEl.textContent = result.sub;
        if (pillEl) {
            pillEl.dataset.stage = result.stage;
            pillEl.textContent = result.stage.toUpperCase();
        }

        // Critical fields completeness
        const critical = [
            { key: "psa_baseline", label: "PSA basal" },
            { key: "gleason_primary", label: "Gleason 1°" },
            { key: "isup_grade", label: "ISUP" },
            { key: "clinical_tstage", label: "cT stage" },
            { key: "ecog_score", label: "ECOG" },
            { key: "charlson_score", label: "Charlson" },
            { key: "life_expectancy_estimate", label: "Expectativa vida" },
            { key: "germline_testing_performed", label: "Germinal" },
            { key: "family_history_cancer", label: "Hist familiar" },
        ];
        const list = document.querySelector("[data-critical-list]");
        if (list) {
            list.innerHTML = critical.map((f) => {
                const v = data[f.key];
                const present = v && v !== "" && v !== "no" && v !== "none" && v !== "unknown" && v !== "not_tested";
                const status = present ? "ok" : "missing";
                const display = present ? (Array.isArray(v) ? v.length + " sel" : String(v).slice(0, 18)) : "—";
                return `<div class="pm2-intake-rail-row" data-status="${status}">
                    <div class="pm2-intake-rail-row-label">${f.label}</div>
                    <div class="pm2-intake-rail-row-value">${display}</div>
                </div>`;
            }).join("");
        }

        // Completeness
        const filled = critical.filter((f) => {
            const v = data[f.key];
            return v && v !== "" && v !== "no" && v !== "none" && v !== "unknown" && v !== "not_tested";
        }).length;
        const total = critical.length;
        const pct = Math.round((filled / total) * 100);
        const fillEl = document.querySelector("[data-completeness-fill]");
        const pctEl = document.querySelector("[data-completeness-pct]");
        const statusEl = document.querySelector("[data-actionbar-status]");
        if (fillEl) fillEl.style.width = pct + "%";
        if (pctEl) pctEl.textContent = pct + "%";
        if (statusEl) statusEl.textContent = `${filled}/${total} campos críticos · clasificación: ${result.label}`;
    };

    PM2.applyConditionalFields = (data) => {
        document.querySelectorAll("[data-conditional]").forEach((el) => {
            const cond = el.dataset.conditional;
            // Simple parser: "field_name == value" or "field_name" (truthy) or "field_name != value"
            const match = cond.match(/^(\w+)\s*(==|!=)\s*(\w+)$/);
            let visible = false;
            if (match) {
                const [, field, op, val] = match;
                const fv = data[field];
                const sv = String(fv || "").toLowerCase();
                visible = (op === "==") ? (sv === val.toLowerCase()) : (sv !== val.toLowerCase());
            } else {
                // Truthy
                visible = !!data[cond] && data[cond] !== "no" && data[cond] !== "none";
            }
            el.style.display = visible ? "" : "none";
        });
    };

    PM2.updateProgressRail = (data) => {
        document.querySelectorAll(".pm2-intake-progress-step").forEach((step) => {
            const stageKey = step.dataset.stage;
            const fields = document.querySelectorAll(`[data-stage-section="${stageKey}"] [name]`);
            const filled = Array.from(fields).filter((f) => {
                const v = data[f.name];
                if (f.type === "checkbox") return v === true;
                return v && v !== "" && v !== "none" && v !== "no";
            }).length;
            const total = fields.length;
            step.classList.toggle("is-complete", total > 0 && filled === total);
            const meta = step.querySelector(".pm2-intake-progress-meta");
            if (meta) meta.textContent = `${filled}/${total}`;
        });
    };

    PM2.applyPreset = (presetId, form) => {
        const presets = {
            preset_localized_int: {
                given_name: "Carlos", family_name: "López Martínez", date_of_birth: "1960-05-12",
                biological_sex: "male", race_ethnicity: "hispanic_latino",
                known_cancer_diagnosis: "yes", diagnosis_date: "2026-03-15", diagnosis_method: "mri_fusion_biopsy",
                prior_prostatectomy: "no", prior_radiation: "no",
                gleason_primary: "3", gleason_secondary: "4", isup_grade: "2",
                num_cores_positive: "4", total_cores: "12", max_core_involvement_pct: "35",
                perineural_invasion: "no", percent_pattern_4: "20",
                clinical_tstage: "T2a", clinical_nstage: "N0", clinical_mstage: "M0",
                mpmri_performed: "yes_pre_bx", pi_rads_score: "4",
                psa_baseline: "8.4", testosterone_baseline: "420",
                hemoglobin_baseline: "14.2", alkaline_phosphatase: "78",
                metastatic_disease_known: "no",
                germline_testing_performed: "no", family_history_cancer: "none",
                ecog_score: "0", charlson_score: "1", life_expectancy_estimate: "more_10y",
            },
            preset_mcspc_hv: {
                given_name: "Miguel Ángel", family_name: "Ramírez Soto", date_of_birth: "1953-09-22",
                biological_sex: "male", race_ethnicity: "hispanic_latino",
                known_cancer_diagnosis: "yes", diagnosis_date: "2026-04-02", diagnosis_method: "trus_biopsy",
                prior_prostatectomy: "no", prior_radiation: "no",
                gleason_primary: "5", gleason_secondary: "4", isup_grade: "5",
                num_cores_positive: "10", total_cores: "12", max_core_involvement_pct: "85",
                perineural_invasion: "yes", intraductal_carcinoma: "yes",
                clinical_tstage: "T3b", clinical_nstage: "N1", clinical_mstage: "M1c",
                psma_pet_performed: "ga68", psma_suv_max: "28",
                psa_baseline: "145.2", alkaline_phosphatase: "385", ldh_baseline: "298",
                hemoglobin_baseline: "11.4", testosterone_baseline: "385",
                metastatic_disease_known: "yes", mets_bone: "on", mets_visceral: "on",
                bone_lesion_count: "8", bone_apendicular_present: "yes",
                visceral_sites: "liver", metachronous_metastasis: "synchronous",
                bpi_pain_score: "5", imaging_method_used: "psma",
                germline_testing_performed: "yes_panel", germline_pathogenic_variant: "none",
                family_history_cancer: "prostate_relative",
                ecog_score: "1", charlson_score: "2", life_expectancy_estimate: "5_to_10y",
            },
            preset_m1crpc_brca: {
                given_name: "Roberto Antonio", family_name: "García Hernández", date_of_birth: "1958-11-04",
                biological_sex: "male", race_ethnicity: "hispanic_latino",
                known_cancer_diagnosis: "yes", diagnosis_date: "2022-03-14", diagnosis_method: "rp_specimen",
                prior_prostatectomy: "yes", prior_radiation: "no",
                bcr_detected: "yes_first",
                gleason_primary: "4", gleason_secondary: "5", isup_grade: "5",
                num_cores_positive: "8", total_cores: "12", max_core_involvement_pct: "75",
                perineural_invasion: "yes",
                clinical_tstage: "T3a", clinical_nstage: "N1", clinical_mstage: "M1b",
                psma_pet_performed: "f18", psma_suv_max: "32",
                psa_baseline: "12.4", testosterone_baseline: "12",
                alkaline_phosphatase: "245", hemoglobin_baseline: "11.8", ldh_baseline: "210",
                metastatic_disease_known: "yes", mets_bone: "on",
                bone_lesion_count: "6", bone_apendicular_present: "yes",
                metachronous_metastasis: "metachronous", first_mets_diagnosis_date: "2024-08-20",
                bpi_pain_score: "4", imaging_method_used: "both",
                current_adt_context: "medical_continuous", adt_start_date: "2024-09-01",
                castrate_testosterone_status: "confirmed",
                systemic_progression_context: "confirmed_crpc",
                progression_pattern: "mixed", conventional_imaging_status: "M1",
                prior_lines_count: "2", prior_taxane: "docetaxel",
                germline_testing_performed: "yes_panel", germline_pathogenic_variant: "brca2",
                hrr_status: "hrr_positive",
                family_history_cancer: "breast_ovarian",
                ecog_score: "1", charlson_score: "3", life_expectancy_estimate: "5_to_10y",
            },
        };
        const data = presets[presetId];
        if (!data) return;
        // Reset all fields first to avoid stale values from previous preset
        form.querySelectorAll("input, select, textarea").forEach((el) => {
            if (el.type === "checkbox" || el.type === "radio") el.checked = false;
            else el.value = "";
        });
        // Apply preset values
        Object.entries(data).forEach(([k, v]) => {
            const el = form.querySelector(`[name="${k}"]`);
            if (!el) return;
            if (el.type === "checkbox") {
                el.checked = (v === "on" || v === true);
            } else {
                el.value = v;
            }
        });
    };

    // ── Init on DOMContentLoaded ────────────────────────────────────────────
    PM2.init = () => {
        PM2.bindEscClose();
        PM2.bindBackdropClose();
        PM2.observeLazy();

        // Bind drawer tabs
        document.querySelectorAll("[data-drawer-tabs]").forEach((d) => {
            PM2.bindDrawerTabs(d.id);
        });

        // Bind audit FAB
        document.querySelectorAll("[data-fab-target]").forEach((btn) => {
            btn.addEventListener("click", () => PM2.openDrawer(btn.dataset.fabTarget));
        });

        // Bind drawer close buttons
        document.querySelectorAll("[data-drawer-close]").forEach((btn) => {
            btn.addEventListener("click", () => PM2.closeDrawer());
        });

        // Bind drilldown close
        document.querySelectorAll("[data-drilldown-close]").forEach((btn) => {
            btn.addEventListener("click", () => PM2.hideDrillDown());
        });

        // Bind stage rail
        PM2.bindStageRail();

        // Bind alert filters
        document.querySelectorAll("[data-alert-filters]").forEach((el) => {
            PM2.bindAlertFilters(`#${el.id}`);
        });

        // Bind generic drilldown triggers (on bento cards)
        document.querySelectorAll("[data-drilldown-trigger]").forEach((el) => {
            el.addEventListener("click", (e) => {
                e.stopPropagation();
                const ctx = el.dataset.drilldownContext || "DETALLE";
                const title = el.dataset.drilldownTitle || "Drill-down";
                const html = el.querySelector("[data-drilldown-content]")?.innerHTML
                    || `<p class="pm2-card-subtitle">Sin contenido detallado disponible.</p>`;
                PM2.showDrillDown({ context: ctx, title, html });
            });
        });

        // Auto-set card index for stagger animation
        document.querySelectorAll(".pm2-bento").forEach((bento) => {
            bento.querySelectorAll(".pm2-bento-card").forEach((card, i) => {
                card.style.setProperty("--card-index", i);
            });
        });

        // Bind intake form (only present on intake demo)
        PM2.bindIntakeForm();
    };

    // Expose
    global.PM2 = PM2;

    // Auto-init
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", PM2.init);
    } else {
        PM2.init();
    }
})(window);
