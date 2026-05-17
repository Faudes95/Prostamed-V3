/**
 * EPIC 36.B-extended — Shared voice quick-capture helper for patient_profile_v2.
 *
 * Wires a mic button in each of the 4 quick-capture cards (ECOG / HRR /
 * Castration / PSMA-PET) to:
 *   1. MediaRecorder API (10s auto-stop)
 *   2. POST /api/voice/quick-capture/<field> with audio blob
 *   3. Render transcript + extraction + confirm button
 *   4. On confirm → reuse existing /api/patients/<nss>/<field>-capture
 *
 * Usage (per card):
 *   window.pm2SetupVoiceQuickCapture({
 *     buttonId: 'pm2EcogVoiceBtn',
 *     iconId: 'pm2EcogVoiceIcon',
 *     labelId: 'pm2EcogVoiceLabel',
 *     statusId: 'pm2EcogVoiceStatus',
 *     resultId: 'pm2EcogVoiceResult',
 *     field: 'ecog',                                  // path param
 *     fieldLabel: 'ECOG',                             // user-visible
 *     dictExample: 'ECOG 2 / performance status uno', // recording hint
 *     captureEndpoint: (nss) => `/api/patients/${nss}/ecog-capture`,
 *     extractValueLabel: (ext) => `ECOG ${ext.value}`, // shown on confirm btn
 *     extractIsEmpty: (ext) => ext.value === null || ext.value === undefined,
 *     extractConfidenceText: (ext) => `confianza ${(ext.confidence*100).toFixed(0)}%, patrón ${ext.source_pattern || 'n/a'}`,
 *     buildCaptureBody: (ext, transcript) => ({
 *       ecog_value: ext.value,
 *       source_type: 'voice_quick_capture_epic36',
 *       notes: `Voice: "${transcript.substring(0, 100)}"`,
 *       actor_session_id: sessionStorage.getItem('pm2_session_id') || '',
 *     }),
 *   });
 *
 * Privacy: NO audio bytes stored. Transcript goes only in notes.
 */
(function() {
  if (window.pm2SetupVoiceQuickCapture) return; // idempotent

  function _showError(statusEl, msg) {
    if (!statusEl) return;
    statusEl.textContent = msg;
    statusEl.style.color = '#ef4444';
  }

  window.pm2SetupVoiceQuickCapture = function(config) {
    const voiceBtn = document.getElementById(config.buttonId);
    if (!voiceBtn) return; // card not rendered (gated off) → no-op
    const voiceIcon = document.getElementById(config.iconId);
    const voiceLabel = document.getElementById(config.labelId);
    const voiceStatus = document.getElementById(config.statusId);
    const voiceResult = document.getElementById(config.resultId);

    let mediaRecorder = null;
    let audioChunks = [];
    let mediaStream = null;

    async function startRecording() {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        _showError(voiceStatus, '✗ Tu navegador no soporta MediaRecorder/getUserMedia.');
        return;
      }
      try {
        mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      } catch (err) {
        _showError(voiceStatus, '✗ Permiso de micrófono denegado: ' + err.message);
        return;
      }
      audioChunks = [];
      try {
        mediaRecorder = new MediaRecorder(mediaStream, { mimeType: 'audio/webm' });
      } catch (e) {
        mediaRecorder = new MediaRecorder(mediaStream);
      }
      mediaRecorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) audioChunks.push(e.data);
      };
      mediaRecorder.onstop = async () => {
        if (voiceIcon) voiceIcon.textContent = '⏳';
        if (voiceLabel) voiceLabel.textContent = 'Transcribiendo...';
        if (voiceStatus) {
          voiceStatus.textContent = 'Whisper STT (es) + intent extraction';
          voiceStatus.style.color = '#a855f7';
        }
        const blob = new Blob(audioChunks, { type: 'audio/webm' });
        const form = new FormData();
        form.append('audio', blob, `${config.field}_dictation.webm`);
        form.append('patient_ref', voiceBtn.dataset.patientNss);
        try {
          const resp = await fetch(`/api/voice/quick-capture/${config.field}`, {
            method: 'POST', body: form
          });
          const data = await resp.json();
          await renderExtraction(data);
        } catch (err) {
          _showError(voiceStatus, '✗ STT falló: ' + err.message);
        } finally {
          if (voiceIcon) voiceIcon.textContent = '🎤';
          if (voiceLabel) voiceLabel.textContent = `Dictar ${config.fieldLabel}`;
          voiceBtn.dataset.recording = 'false';
          if (mediaStream) {
            mediaStream.getTracks().forEach(t => t.stop());
            mediaStream = null;
          }
        }
      };
      mediaRecorder.start();
      voiceBtn.dataset.recording = 'true';
      if (voiceIcon) voiceIcon.textContent = '⏺';
      if (voiceLabel) voiceLabel.textContent = 'Parar y transcribir';
      if (voiceStatus) {
        voiceStatus.textContent = `🔴 Grabando · di "${config.dictExample}"`;
        voiceStatus.style.color = '#ef4444';
      }
      // Auto-stop at 10s
      setTimeout(() => {
        if (mediaRecorder && mediaRecorder.state === 'recording') {
          mediaRecorder.stop();
        }
      }, 10000);
    }

    async function renderExtraction(data) {
      if (!voiceResult) return;
      voiceResult.style.display = 'block';
      if (!data || !data.success) {
        voiceResult.innerHTML = `<strong style="color:#ef4444">Falló:</strong> ${(data && data.error) || 'unknown'}` +
          ((data && data.hint) ? `<br><span style="color:#94a3b8">${data.hint}</span>` : '');
        return;
      }
      const ext = data.extraction || {};
      const transcript = data.transcript || '(vacío)';
      if (config.extractIsEmpty(ext)) {
        voiceResult.innerHTML = `<strong>Transcripción:</strong> "${transcript}"<br>` +
          `<span style="color:#fbbf24">⚠ No detecté un valor ${config.fieldLabel} en el dictado. Intenta de nuevo o usa los botones manuales.</span>`;
        return;
      }
      const valueLabel = config.extractValueLabel(ext);
      const confidenceText = config.extractConfidenceText(ext);
      const confirmId = `${config.buttonId}_confirm`;
      voiceResult.innerHTML =
        `<strong>Transcripción:</strong> "${transcript}"<br>` +
        `<strong style="color:#86efac">✓ Detecté ${valueLabel}</strong> ` +
        `<span style="color:#94a3b8">(${confidenceText})</span><br>` +
        `<button type="button" id="${confirmId}" ` +
        `style="margin-top:6px; padding:6px 14px; background:rgba(16,185,129,.15); border:1px solid #10b981; color:#86efac; border-radius:6px; cursor:pointer; font-size:.75rem; font-weight:600;">` +
        `✓ Aplicar ${valueLabel}</button>`;
      const confirmBtn = document.getElementById(confirmId);
      confirmBtn.addEventListener('click', async () => {
        const nss = data.patient_ref || voiceBtn.dataset.patientNss;
        confirmBtn.disabled = true;
        confirmBtn.textContent = 'Guardando...';
        try {
          const body = config.buildCaptureBody(ext, transcript);
          const resp = await fetch(config.captureEndpoint(nss), {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(body),
          });
          const r = await resp.json();
          if (r.success) {
            confirmBtn.textContent = `✓ ${valueLabel} guardado. Refrescando…`;
            setTimeout(() => location.reload(), 1500);
          } else {
            confirmBtn.textContent = '✗ Error: ' + (r.error || 'unknown');
            confirmBtn.disabled = false;
          }
        } catch (err) {
          confirmBtn.textContent = '✗ ' + err.message;
          confirmBtn.disabled = false;
        }
      });
    }

    voiceBtn.addEventListener('click', () => {
      if (voiceBtn.dataset.recording === 'true') {
        if (mediaRecorder && mediaRecorder.state === 'recording') {
          mediaRecorder.stop();
        }
      } else {
        startRecording();
      }
    });
  };
})();
