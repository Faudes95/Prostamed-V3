(function (global) {
    const MOBILE_BREAKPOINT = 640;
    const SEARCH_THRESHOLD = 10;
    const INSTANCES = new WeakMap();
    let portalRoot = null;
    let backdrop = null;
    let panelMount = null;
    let openInstance = null;
    let uid = 0;

    function isMobileViewport() {
        return global.innerWidth <= MOBILE_BREAKPOINT;
    }

    function ensurePortal() {
        if (portalRoot) {
            return;
        }

        portalRoot = document.createElement("div");
        portalRoot.className = "pn-select-portal";
        portalRoot.hidden = true;

        backdrop = document.createElement("button");
        backdrop.type = "button";
        backdrop.className = "pn-select-backdrop";
        backdrop.setAttribute("aria-label", "Cerrar lista desplegable");
        backdrop.addEventListener("click", () => {
            openInstance?.close({ restoreFocus: false });
        });

        panelMount = document.createElement("div");
        panelMount.className = "pn-select-panel-mount";

        portalRoot.appendChild(backdrop);
        portalRoot.appendChild(panelMount);
        document.body.appendChild(portalRoot);

        document.addEventListener("pointerdown", (event) => {
            if (!openInstance) {
                return;
            }
            const target = event.target;
            if (
                openInstance.shell.contains(target) ||
                (openInstance.menu && openInstance.menu.contains(target))
            ) {
                return;
            }
            openInstance.close({ restoreFocus: false });
        }, true);

        document.addEventListener("keydown", (event) => {
            if (event.key === "Escape" && openInstance) {
                event.preventDefault();
                openInstance.close();
            }
        });

        global.addEventListener("resize", () => {
            openInstance?.positionMenu();
        });

        global.addEventListener("scroll", () => {
            openInstance?.positionMenu();
        }, true);
    }

    function isEnhanceable(select) {
        return (
            select instanceof HTMLSelectElement &&
            !select.multiple &&
            select.dataset.pnSelectEnhance !== "off"
        );
    }

    function getVariant(select) {
        return select.dataset.pnSelectVariant || (select.classList.contains("text-xs") ? "compact" : "default");
    }

    function getSearchMode(select) {
        return select.dataset.pnSelectSearch || "auto";
    }

    function shouldEnableSearch(select, options) {
        const mode = getSearchMode(select);
        if (mode === "on") {
            return true;
        }
        if (mode === "off") {
            return false;
        }
        return options.length > SEARCH_THRESHOLD;
    }

    function getLabelForOption(option) {
        return (option?.textContent || "").replace(/\s+/g, " ").trim();
    }

    function resolveInstances(selectOrName) {
        if (!selectOrName) {
            return [];
        }
        if (typeof selectOrName === "string") {
            return Array.from(document.querySelectorAll(`select[name="${selectOrName}"]`))
                .map((select) => INSTANCES.get(select))
                .filter(Boolean);
        }
        if (selectOrName instanceof HTMLSelectElement) {
            const instance = INSTANCES.get(selectOrName);
            return instance ? [instance] : [];
        }
        if (selectOrName instanceof Element) {
            const nestedSelects = selectOrName.matches("select")
                ? [selectOrName]
                : Array.from(selectOrName.querySelectorAll("select"));
            return nestedSelects.map((select) => INSTANCES.get(select)).filter(Boolean);
        }
        return [];
    }

    class ClinicalSelect {
        constructor(select) {
            this.select = select;
            this.id = `pn-select-${++uid}`;
            this.searchQuery = "";
            this.optionButtons = [];
            this.filteredOptions = [];
            this.activeIndex = select.selectedIndex >= 0 ? select.selectedIndex : 0;

            this.build();
            this.bind();
            this.observe();
            this.sync();
        }

        build() {
            const shell = document.createElement("div");
            shell.className = "pn-select-shell";
            shell.dataset.variant = getVariant(this.select);
            shell.dataset.disabled = String(!!this.select.disabled);
            shell.dataset.open = "false";

            const trigger = document.createElement("button");
            trigger.type = "button";
            trigger.className = "pn-select-trigger";
            trigger.setAttribute("role", "combobox");
            trigger.setAttribute("aria-haspopup", "listbox");
            trigger.setAttribute("aria-expanded", "false");
            trigger.setAttribute("aria-labelledby", `${this.id}-label`);
            trigger.disabled = this.select.disabled;

            const value = document.createElement("span");
            value.className = "pn-select-value";
            value.id = `${this.id}-label`;

            const caret = document.createElement("span");
            caret.className = "pn-select-caret";
            caret.setAttribute("aria-hidden", "true");
            caret.innerHTML = `
                <svg viewBox="0 0 20 20" fill="currentColor">
                    <path fill-rule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.512a.75.75 0 01-1.08 0L5.21 8.27a.75.75 0 01.02-1.06z" clip-rule="evenodd"></path>
                </svg>
            `;

            this.select.parentNode.insertBefore(shell, this.select);
            shell.appendChild(this.select);
            shell.appendChild(trigger);
            trigger.appendChild(value);
            trigger.appendChild(caret);

            this.select.classList.add("pn-select-native");
            this.select.setAttribute("tabindex", "-1");
            this.select.setAttribute("aria-hidden", "true");
            this.select.dataset.pnSelectEnhanced = "true";

            this.shell = shell;
            this.trigger = trigger;
            this.valueNode = value;
            this.caretNode = caret;
        }

        bind() {
            this.trigger.addEventListener("click", () => {
                if (this.select.disabled) {
                    return;
                }
                this.toggle();
            });

            this.trigger.addEventListener("keydown", (event) => {
                if (this.select.disabled) {
                    return;
                }
                if (event.key === "ArrowDown") {
                    event.preventDefault();
                    if (!this.isOpen()) {
                        this.open();
                    }
                    this.moveActive(1);
                    return;
                }
                if (event.key === "ArrowUp") {
                    event.preventDefault();
                    if (!this.isOpen()) {
                        this.open();
                    }
                    this.moveActive(-1);
                    return;
                }
                if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    if (this.isOpen()) {
                        this.selectOption(this.activeIndex);
                    } else {
                        this.open();
                    }
                }
            });

            this.select.addEventListener("change", () => {
                this.sync({ preserveSearch: true });
            });
        }

        observe() {
            this.observer = new MutationObserver(() => {
                this.sync({ preserveSearch: true });
            });
            this.observer.observe(this.select, {
                attributes: true,
                attributeFilter: ["disabled", "class", "data-pn-select-variant", "data-pn-select-search"],
                childList: true,
                subtree: true,
            });
        }

        isOpen() {
            return openInstance === this;
        }

        getOptions() {
            return Array.from(this.select.options).map((option, index) => ({
                index,
                value: option.value,
                label: getLabelForOption(option),
                disabled: option.disabled,
                selected: option.selected,
            }));
        }

        sync({ preserveSearch = false } = {}) {
            this.options = this.getOptions();
            this.variant = getVariant(this.select);
            this.searchEnabled = shouldEnableSearch(this.select, this.options);
            this.shell.dataset.variant = this.variant;
            this.shell.dataset.disabled = String(!!this.select.disabled);
            this.trigger.disabled = this.select.disabled;

            if (this.select.selectedIndex >= 0) {
                this.activeIndex = this.select.selectedIndex;
            }

            const selectedOption = this.options[this.select.selectedIndex] || this.options[0];
            this.valueNode.textContent = selectedOption ? selectedOption.label : "Seleccionar";
            this.valueNode.title = this.valueNode.textContent;

            if (this.isOpen()) {
                this.renderMenu({ preserveSearch });
                this.positionMenu();
            }
        }

        toggle() {
            if (this.isOpen()) {
                this.close();
                return;
            }
            this.open();
        }

        open() {
            if (this.select.disabled) {
                return;
            }
            ensurePortal();
            if (openInstance && openInstance !== this) {
                openInstance.close({ restoreFocus: false });
            }
            openInstance = this;
            this.shell.dataset.open = "true";
            this.trigger.setAttribute("aria-expanded", "true");
            this.renderMenu();
            this.positionMenu();
            portalRoot.hidden = false;

            requestAnimationFrame(() => {
                if (this.searchInput) {
                    this.searchInput.focus({ preventScroll: true });
                    this.searchInput.select();
                } else if (this.menu) {
                    this.menu.focus({ preventScroll: true });
                }
            });
        }

        close({ restoreFocus = true } = {}) {
            if (!this.isOpen()) {
                return;
            }
            openInstance = null;
            this.shell.dataset.open = "false";
            this.trigger.setAttribute("aria-expanded", "false");
            this.trigger.removeAttribute("aria-controls");
            this.trigger.removeAttribute("aria-activedescendant");
            this.searchQuery = "";
            this.optionButtons = [];
            this.filteredOptions = [];
            this.menu = null;
            this.searchInput = null;
            if (panelMount) {
                panelMount.innerHTML = "";
            }
            if (portalRoot) {
                portalRoot.hidden = true;
                portalRoot.dataset.mobile = "false";
            }
            if (restoreFocus) {
                this.trigger.focus({ preventScroll: true });
            }
        }

        renderMenu({ preserveSearch = false } = {}) {
            ensurePortal();
            if (!preserveSearch) {
                this.searchQuery = "";
            }

            const normalizedQuery = this.searchQuery.trim().toLowerCase();
            this.filteredOptions = this.options.filter((option) => {
                if (!normalizedQuery) {
                    return true;
                }
                return option.label.toLowerCase().includes(normalizedQuery);
            });

            if (!this.filteredOptions.some((option) => option.index === this.activeIndex)) {
                const selected = this.filteredOptions.find((option) => option.selected && !option.disabled);
                const firstEnabled = this.filteredOptions.find((option) => !option.disabled);
                this.activeIndex = (selected || firstEnabled || this.filteredOptions[0] || {}).index ?? this.activeIndex;
            }

            const menu = document.createElement("div");
            menu.className = "pn-select-menu";
            menu.dataset.variant = this.variant;
            menu.dataset.mobile = String(isMobileViewport());
            menu.id = `${this.id}-listbox`;
            menu.setAttribute("role", "listbox");
            menu.setAttribute("tabindex", "-1");
            menu.addEventListener("keydown", (event) => this.handleOpenKeydown(event));

            if (this.searchEnabled) {
                const search = document.createElement("div");
                search.className = "pn-select-search-shell";

                const input = document.createElement("input");
                input.type = "text";
                input.className = "pn-select-search";
                input.placeholder = "Buscar opción...";
                input.value = this.searchQuery;
                input.setAttribute("aria-label", "Buscar opción");
                input.addEventListener("input", (event) => {
                    this.searchQuery = event.target.value;
                    this.renderMenu({ preserveSearch: true });
                    this.positionMenu();
                });
                input.addEventListener("keydown", (event) => this.handleOpenKeydown(event));

                search.appendChild(input);
                menu.appendChild(search);
                this.searchInput = input;
            } else {
                this.searchInput = null;
            }

            if (isMobileViewport()) {
                const handle = document.createElement("div");
                handle.className = "pn-select-sheet-handle";
                handle.setAttribute("aria-hidden", "true");
                menu.appendChild(handle);
            }

            const list = document.createElement("div");
            list.className = "pn-select-list";

            if (!this.filteredOptions.length) {
                const empty = document.createElement("div");
                empty.className = "pn-select-empty";
                empty.textContent = "Sin coincidencias";
                list.appendChild(empty);
            } else {
                this.optionButtons = this.filteredOptions.map((option) => {
                    const button = document.createElement("button");
                    button.type = "button";
                    button.className = "pn-select-option";
                    button.id = `${this.id}-option-${option.index}`;
                    button.dataset.index = String(option.index);
                    button.setAttribute("role", "option");
                    button.setAttribute("aria-selected", String(option.selected));
                    button.disabled = option.disabled;
                    button.addEventListener("mouseenter", () => {
                        if (!option.disabled) {
                            this.activeIndex = option.index;
                            this.updateOptionStates();
                        }
                    });
                    button.addEventListener("click", () => {
                        this.selectOption(option.index);
                    });

                    const label = document.createElement("span");
                    label.className = "pn-select-option-label";
                    label.textContent = option.label;

                    const check = document.createElement("span");
                    check.className = "pn-select-check";
                    check.setAttribute("aria-hidden", "true");
                    check.innerHTML = `
                        <svg viewBox="0 0 20 20" fill="currentColor">
                            <path fill-rule="evenodd" d="M16.704 5.29a1 1 0 010 1.42l-7.25 7.25a1 1 0 01-1.415 0L3.296 9.216a1 1 0 111.415-1.414l4.035 4.035 6.543-6.546a1 1 0 011.415 0z" clip-rule="evenodd"></path>
                        </svg>
                    `;

                    button.appendChild(label);
                    button.appendChild(check);
                    list.appendChild(button);
                    return button;
                });
            }

            menu.appendChild(list);
            panelMount.innerHTML = "";
            panelMount.appendChild(menu);
            portalRoot.hidden = false;
            portalRoot.dataset.mobile = String(isMobileViewport());
            this.menu = menu;
            this.list = list;
            this.trigger.setAttribute("aria-controls", menu.id);
            this.updateOptionStates();
        }

        updateOptionStates() {
            if (!this.optionButtons.length) {
                this.trigger.removeAttribute("aria-activedescendant");
                return;
            }
            this.optionButtons.forEach((button) => {
                const optionIndex = Number(button.dataset.index);
                const option = this.options[optionIndex];
                const isSelected = !!option?.selected;
                const isActive = optionIndex === this.activeIndex;
                button.dataset.selected = String(isSelected);
                button.dataset.active = String(isActive);
                button.setAttribute("aria-selected", String(isSelected));
                if (isActive) {
                    this.trigger.setAttribute("aria-activedescendant", button.id);
                    button.scrollIntoView({ block: "nearest" });
                }
            });
        }

        positionMenu() {
            if (!this.menu) {
                return;
            }

            const mobile = isMobileViewport();
            this.menu.dataset.mobile = String(mobile);
            portalRoot.dataset.mobile = String(mobile);

            if (mobile) {
                this.menu.style.left = "12px";
                this.menu.style.right = "12px";
                this.menu.style.bottom = "12px";
                this.menu.style.top = "auto";
                this.menu.style.width = "auto";
                this.menu.style.maxHeight = `${Math.min(global.innerHeight * 0.72, 520)}px`;
                return;
            }

            const rect = this.trigger.getBoundingClientRect();
            const margin = 12;
            const gap = 8;
            const maxHeight = Math.min(360, global.innerHeight - margin * 2);

            this.menu.style.left = "0px";
            this.menu.style.top = "0px";
            this.menu.style.bottom = "auto";
            this.menu.style.width = `${rect.width}px`;
            this.menu.style.maxHeight = `${maxHeight}px`;
            this.menu.style.visibility = "hidden";

            const menuHeight = Math.min(this.menu.scrollHeight, maxHeight);
            const shouldOpenUp =
                global.innerHeight - rect.bottom < menuHeight + gap + margin &&
                rect.top > menuHeight + gap;
            const top = shouldOpenUp
                ? Math.max(margin, rect.top - menuHeight - gap)
                : Math.min(global.innerHeight - menuHeight - margin, rect.bottom + gap);
            const left = Math.min(
                Math.max(margin, rect.left),
                Math.max(margin, global.innerWidth - rect.width - margin),
            );

            this.menu.style.left = `${left}px`;
            this.menu.style.top = `${top}px`;
            this.menu.style.visibility = "visible";
        }

        moveActive(step) {
            if (!this.filteredOptions.length) {
                return;
            }
            const enabled = this.filteredOptions.filter((option) => !option.disabled);
            if (!enabled.length) {
                return;
            }
            const currentPos = enabled.findIndex((option) => option.index === this.activeIndex);
            const basePos = currentPos === -1 ? 0 : currentPos;
            const nextPos = (basePos + step + enabled.length) % enabled.length;
            this.activeIndex = enabled[nextPos].index;
            this.updateOptionStates();
        }

        moveToBoundary(direction) {
            const enabled = this.filteredOptions.filter((option) => !option.disabled);
            if (!enabled.length) {
                return;
            }
            this.activeIndex = direction === "start" ? enabled[0].index : enabled[enabled.length - 1].index;
            this.updateOptionStates();
        }

        selectOption(index) {
            const option = this.select.options[index];
            if (!option || option.disabled) {
                return;
            }
            this.select.selectedIndex = index;
            this.select.value = option.value;
            this.sync({ preserveSearch: true });
            this.select.dispatchEvent(new Event("input", { bubbles: true }));
            this.select.dispatchEvent(new Event("change", { bubbles: true }));
            this.close();
        }

        handleOpenKeydown(event) {
            if (event.key === "ArrowDown") {
                event.preventDefault();
                this.moveActive(1);
                return;
            }
            if (event.key === "ArrowUp") {
                event.preventDefault();
                this.moveActive(-1);
                return;
            }
            if (event.key === "Home") {
                event.preventDefault();
                this.moveToBoundary("start");
                return;
            }
            if (event.key === "End") {
                event.preventDefault();
                this.moveToBoundary("end");
                return;
            }
            if (event.key === "Enter" || (event.key === " " && event.target !== this.searchInput)) {
                event.preventDefault();
                this.selectOption(this.activeIndex);
            }
        }
    }

    function collectSelects(root = document) {
        if (!root) {
            return [];
        }
        if (root instanceof HTMLSelectElement) {
            return [root];
        }
        const scope = root.querySelectorAll ? root : document;
        return Array.from(scope.querySelectorAll("select"));
    }

    function enhance(root = document) {
        collectSelects(root).forEach((select) => {
            if (!isEnhanceable(select) || INSTANCES.has(select)) {
                return;
            }
            INSTANCES.set(select, new ClinicalSelect(select));
        });
    }

    function syncField(selectOrName) {
        resolveInstances(selectOrName).forEach((instance) => instance.sync({ preserveSearch: true }));
    }

    function syncAll(root = document) {
        enhance(root);
        resolveInstances(root).forEach((instance) => instance.sync({ preserveSearch: true }));
    }

    global.clinicalSelects = {
        enhance,
        syncField,
        syncAll,
    };
})(window);
