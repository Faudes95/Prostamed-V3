(function () {
    function escapeHtml(value) {
        return String(value ?? "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    class ProstaNetConsentFlow {
        constructor(config = {}) {
            this.config = config;
            this.modal = document.getElementById("consentModal");
            this.versionTitle = document.getElementById("consentVersionTitle");
            this.versionCode = document.getElementById("consentVersionCode");
            this.textContainer = document.getElementById("consentTextContainer");
            this.signerNameInput = document.getElementById("consentSignerName");
            this.acceptedInput = document.getElementById("consentAccepted");
            this.statusText = document.getElementById("consentStatusText");
            this.submitButton = document.getElementById("consentSubmitButton");
            this.clearButton = document.getElementById("consentClearSignature");
            this.cancelButton = document.getElementById("consentCancelButton");
            this.cancelTopButton = document.getElementById("consentCancelTop");
            this.canvas = document.getElementById("consentSignatureCanvas");
            this.ctx = this.canvas ? this.canvas.getContext("2d") : null;
            this.drawing = false;
            this.hasSignature = false;
            this.currentDraftId = null;
            this.currentPayload = null;
            this.redirectUrl = null;
            this.sourceContext = "wizard";
            this._bind();
            this._resetCanvas();
        }

        _bind() {
            if (!this.canvas) return;
            const start = (event) => {
                this.drawing = true;
                this.ctx.beginPath();
                const point = this._point(event);
                this.ctx.moveTo(point.x, point.y);
            };
            const move = (event) => {
                if (!this.drawing) return;
                const point = this._point(event);
                this.ctx.lineTo(point.x, point.y);
                this.ctx.stroke();
                this.hasSignature = true;
            };
            const end = () => {
                this.drawing = false;
            };
            this.canvas.addEventListener("mousedown", start);
            this.canvas.addEventListener("mousemove", move);
            window.addEventListener("mouseup", end);
            this.canvas.addEventListener("touchstart", (event) => {
                event.preventDefault();
                start(event.touches[0]);
            }, { passive: false });
            this.canvas.addEventListener("touchmove", (event) => {
                event.preventDefault();
                move(event.touches[0]);
            }, { passive: false });
            window.addEventListener("touchend", end);
            this.clearButton?.addEventListener("click", () => this._resetCanvas());
            this.cancelButton?.addEventListener("click", () => this.close());
            this.cancelTopButton?.addEventListener("click", () => this.close());
            this.submitButton?.addEventListener("click", () => this._submit());
        }

        _point(event) {
            const rect = this.canvas.getBoundingClientRect();
            const scaleX = this.canvas.width / rect.width;
            const scaleY = this.canvas.height / rect.height;
            return {
                x: (event.clientX - rect.left) * scaleX,
                y: (event.clientY - rect.top) * scaleY,
            };
        }

        _resetCanvas() {
            if (!this.ctx || !this.canvas) return;
            this.ctx.fillStyle = "#020617";
            this.ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
            this.ctx.strokeStyle = "#22d3ee";
            this.ctx.lineWidth = 2.5;
            this.ctx.lineCap = "round";
            this.ctx.lineJoin = "round";
            this.hasSignature = false;
        }

        _setStatus(message, tone = "neutral") {
            if (this.statusText) {
                this.statusText.textContent = message;
                this.statusText.className = `mt-2 text-sm ${tone === "error" ? "text-rose-300" : tone === "success" ? "text-emerald-300" : "text-slate-300"}`;
            }
            if (typeof this.config.onStatus === "function") {
                this.config.onStatus(message, tone);
            }
        }

        _setBusy(isBusy, buttonText = "Firmar y abrir expediente") {
            if (this.submitButton) {
                this.submitButton.disabled = isBusy;
                this.submitButton.textContent = isBusy ? buttonText : "Firmar y abrir expediente";
            }
            if (typeof this.config.onBusy === "function") {
                this.config.onBusy(isBusy, buttonText);
            }
        }

        async open({ payload, sourceContext = "wizard", redirectUrl }) {
            this.currentPayload = payload;
            this.redirectUrl = redirectUrl;
            this.sourceContext = sourceContext;
            this._resetCanvas();
            this.acceptedInput.checked = false;
            this.signerNameInput.value = payload.full_name || "";
            this._setBusy(false);
            this._setStatus("Preparando consentimiento informado…");
            const response = await fetch("/api/research/consent/draft", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ payload, source_context: sourceContext }),
            });
            const data = await response.json();
            if (!data.success) {
                throw new Error(data.error || "No fue posible preparar el consentimiento.");
            }
            this.currentDraftId = data.draft_id;
            const version = data.consent_version || {};
            this.versionTitle.textContent = version.title || "Consentimiento institucional";
            this.versionCode.textContent = version.version_code || "v2026.1";
            this.textContainer.innerHTML = escapeHtml(version.consent_text || "").replace(/\n/g, "<br>");
            this.modal.classList.remove("hidden");
            this.modal.classList.add("flex");
            this._setStatus("Revise el texto, confirme la aceptación y firme para abrir el expediente.");
        }

        close() {
            this.modal?.classList.add("hidden");
            this.modal?.classList.remove("flex");
            this._setBusy(false);
        }

        async _submit() {
            try {
                if (!this.currentDraftId) {
                    throw new Error("No existe un borrador de consentimiento activo.");
                }
                if (!this.acceptedInput.checked) {
                    throw new Error("Debe aceptar el consentimiento para continuar.");
                }
                if (!this.hasSignature) {
                    throw new Error("La firma electrónica es obligatoria.");
                }
                const signerName = (this.signerNameInput.value || "").trim();
                if (!signerName) {
                    throw new Error("Se requiere el nombre del paciente para registrar la firma.");
                }
                this._setBusy(true, "Firmando consentimiento…");
                this._setStatus("Guardando firma electrónica…");
                const signRes = await fetch(`/api/research/consent/draft/${this.currentDraftId}/sign`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        signer_name: signerName,
                        signature_data_url: this.canvas.toDataURL("image/png"),
                        accepted: true,
                        audit_metadata: {
                            source_context: this.sourceContext,
                            locale_time: new Date().toISOString(),
                        },
                    }),
                }).then((r) => r.json());
                if (!signRes.success) {
                    throw new Error(signRes.error || "No fue posible guardar la firma.");
                }
                this._setBusy(true, "Abriendo expediente…");
                this._setStatus("Finalizando consentimiento y creando expediente…");
                const finalizeRes = await fetch(`/api/research/consent/draft/${this.currentDraftId}/finalize`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({}),
                }).then((r) => r.json());
                if (!finalizeRes.success) {
                    throw new Error(finalizeRes.error || "No fue posible abrir el expediente.");
                }
                this._setStatus("Consentimiento firmado y expediente abierto.", "success");
                const destination = this.redirectUrl || (this.currentPayload?.nss ? `/patient_profile/${encodeURIComponent(this.currentPayload.nss)}` : "/patients");
                window.location.href = destination;
            } catch (error) {
                this._setBusy(false);
                this._setStatus(error.message || "No fue posible completar el consentimiento.", "error");
            }
        }
    }

    window.ProstaNetConsentFlow = ProstaNetConsentFlow;
})();
