(function () {
  const panels = Array.from(document.querySelectorAll('[data-pm2-voice-os]'));
  if (!panels.length) return;

  const toast = (level, message) => {
    if (window.pm2Toast) window.pm2Toast(level, message);
    else console[level === 'error' ? 'error' : 'log'](message);
  };

  const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  })[ch]);

  async function api(panel, path, options) {
    const res = await fetch(path, {
      method: options?.method || 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: options?.body ? JSON.stringify(options.body) : undefined,
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok || body.success === false) {
      throw new Error(body.error || `HTTP ${res.status}`);
    }
    return body;
  }

  function setStatus(panel, label, tone) {
    const status = panel.querySelector('[data-voice-status]');
    if (!status) return;
    status.textContent = label;
    status.dataset.tone = tone || 'idle';
    panel.dataset.voiceState = tone || 'idle';
  }

  function currentSession(panel) {
    return panel.dataset.voiceSessionKey || '';
  }

  function isIntakePanel(panel) {
    return panel.dataset.voiceMode === 'intake' || !panel.dataset.patientRef;
  }

  function encounterBase(panel, sessionKey) {
    if (isIntakePanel(panel)) {
      const base = '/api/clinical-hub/voice/encounters';
      return sessionKey ? `${base}/${encodeURIComponent(sessionKey)}` : base;
    }
    const patientRef = panel.dataset.patientRef;
    const base = `/api/patients/${encodeURIComponent(patientRef)}/voice/encounters`;
    return sessionKey ? `${base}/${encodeURIComponent(sessionKey)}` : base;
  }

  function setSession(panel, sessionKey) {
    panel.dataset.voiceSessionKey = sessionKey || '';
    const node = panel.querySelector('[data-voice-session-key]');
    if (node) node.textContent = sessionKey || 'sin sesión';
  }

  function autoApplyEnabled(panel) {
    return isIntakePanel(panel) && panel.dataset.voiceAutoApply !== 'false';
  }

  function appendTranscript(panel, body) {
    const transcriptEl = panel.querySelector('[data-voice-transcript]');
    if (!transcriptEl) return;
    const delta = String(body.transcript_delta || '').trim();
    const current = transcriptEl.value.trim();
    if (delta) {
      if (!current.includes(delta)) {
        transcriptEl.value = [current, delta].filter(Boolean).join('\n');
      }
      return;
    }
    if (body.transcript_full && String(body.transcript_full).length > current.length) {
      transcriptEl.value = body.transcript_full;
    }
  }

  function setRecordingControls(panel, recording) {
    panel.dataset.voiceRecording = recording ? 'true' : 'false';
    panel.querySelectorAll('[data-voice-action]').forEach((button) => {
      const action = button.dataset.voiceAction;
      const blocked = recording && ['create', 'consent', 'record', 'review', 'apply', 'discard'].includes(action);
      button.disabled = blocked;
      if (action === 'stop') button.disabled = !recording;
    });
  }

  function setButtonLabel(button, label) {
    if (!button) return;
    const icon = button.querySelector('svg');
    button.textContent = '';
    if (icon) button.appendChild(icon);
    button.appendChild(document.createTextNode(label));
  }

  function renderVoiceLog(panel) {
    const host = panel.querySelector('[data-voice-change-log]');
    if (!host) return;
    const history = panel._voiceApplyHistory || [];
    if (!history.length) {
      host.innerHTML = '<div class="pm2-voice-empty">Sin cambios aplicados por voz.</div>';
      return;
    }
    host.innerHTML = history.slice(-8).reverse().map((entry) => `
      <div class="pm2-voice-change">
        <strong>${escapeHtml(entry.field_name)}</strong>
        <span>${escapeHtml(entry.previous_value || 'vacío')} → ${escapeHtml(entry.new_value)}</span>
      </div>
    `).join('');
  }

  function emitApply(panel, body, source) {
    if (!isIntakePanel(panel) || !body.fields || !Object.keys(body.fields).length) return;
    panel.dispatchEvent(new CustomEvent('prostanet:voice-intake-apply', {
      bubbles: true,
      detail: {
        fields: body.fields || {},
        provenance: body.provenance || { source: 'clinical_hub_voice_intake_live' },
        session: body.session || {},
        candidates: body.candidates || [],
        conflicts: body.conflicts || [],
        source: source || 'voice_live',
      },
    }));
  }

  function renderCandidates(panel, candidates) {
    const host = panel.querySelector('[data-voice-candidates]');
    if (!host) return;
    if (!candidates || !candidates.length) {
      host.innerHTML = '<div class="pm2-voice-empty">Sin candidatos clínicos detectados. Revise el texto o dicte valores explícitos.</div>';
      return;
    }
    host.innerHTML = candidates.map((candidate) => `
      <label class="pm2-voice-candidate">
        <input type="checkbox" checked data-voice-candidate-key="${escapeHtml(candidate.candidate_key)}">
        <span>
          <strong>${escapeHtml(candidate.value_display || candidate.field_name)}</strong>
          <em>${escapeHtml(candidate.field_name)} · confianza ${(Number(candidate.confidence || 0) * 100).toFixed(0)}%</em>
          <small>${escapeHtml(candidate.evidence_excerpt || '')}</small>
        </span>
      </label>
    `).join('');
  }

  function renderCandidatesMessage(panel, message) {
    const host = panel.querySelector('[data-voice-candidates]');
    if (!host) return;
    host.innerHTML = `<div class="pm2-voice-empty">${escapeHtml(message)}</div>`;
  }

  function isAutodriveCommand(text) {
    const normalized = String(text || '').toLowerCase();
    return [
      'decision hoy',
      'decisión hoy',
      'que debo hacer hoy',
      'qué debo hacer hoy',
      'por que',
      'por qué',
      'dato falta',
      'datos faltan',
      'bloqueo dominante',
      'riesgo evita',
      'donde capturarlo',
      'dónde capturarlo',
      'prepara nota de decision',
      'prepara nota de decisión',
      'abre captura de testosterona',
      'captura de testosterona',
    ].some((token) => normalized.includes(token));
  }

  function isAutonomousImprovementCommand(text) {
    const normalized = String(text || '').toLowerCase();
    return [
      'objetivo final',
      'progreso hacia prostamed',
      'automejora',
      'auto mejora',
      'brecha clinica',
      'brecha clínica',
      'mejora toca hoy',
      'que mejora toca',
      'qué mejora toca',
      'que falta para alcanzar',
      'qué falta para alcanzar',
      'por que este pr mejora',
      'por qué este pr mejora',
      'evidencia respalda este cambio',
      'camino al objetivo final',
      'patient twin',
      'gemelo clinico',
      'gemelo clínico',
      'ia entrenable',
      'ai readiness',
      'dataset',
    ].some((token) => normalized.includes(token));
  }

  function renderAutonomousImprovementResult(panel, body) {
    const host = panel.querySelector('[data-voice-candidates]');
    if (!host) return;
    const loop = body.cortana_loop_interface || (body.phase === '10A_cortana_loop_interface' ? body : null);
    const continuous = body.continuous_shadow_operation || (body.phase === 'continuous_shadow_operation' ? body : null);
    if (continuous) {
      const summary = continuous.summary || {};
      const cycle = continuous.cycle_packet || {};
      const auth = continuous.human_authorization_request || {};
      host.innerHTML = `
        <div class="pm2-voice-candidate">
          <span>
            <strong>CONTINUOUS SHADOW · ${escapeHtml(summary.mode || 'shadow')}</strong>
            <em>${escapeHtml(summary.continuous_status || 'awaiting_human_authorization')} · ${escapeHtml(summary.cycle_gate || 'human_authorization_required')}</em>
            <small>${escapeHtml(summary.selected_gap_title || 'Sin brecha accionable')}</small>
            <small>Cambio mínimo: ${escapeHtml(cycle.minimal_change || 'propuesta pendiente')}</small>
            <small>Riesgo evitado: ${escapeHtml(cycle.risk_avoided || 'sin acción automática')}</small>
            <small>Autorización: ${escapeHtml(auth.authorization_state || 'pending_human_authorization')}</small>
            <a class="pm2-btn pm2-btn--ghost" style="margin-top:8px;text-decoration:none;display:inline-flex" href="/loop-monitor#pm2ContinuousShadowOperation">Abrir ciclo shadow</a>
          </span>
        </div>
      `;
      setStatus(panel, 'Continuous Shadow consultado · sin escritura', 'ok');
      toast('success', 'Cortana consultó el ciclo shadow continuo');
      return;
    }
    if (loop) {
      const summary = loop.summary || {};
      const response = loop.resolved_response || {};
      host.innerHTML = `
        <div class="pm2-voice-candidate">
          <span>
            <strong>CORTANA LOOP · ${escapeHtml(summary.mode || 'shadow')}</strong>
            <em>${escapeHtml(summary.cortana_loop_status || 'consultative')} · ${escapeHtml(summary.clinical_goal_pct ?? 0)}% objetivo clínico</em>
            <small>${escapeHtml(response.title || 'Automejora clínica')}</small>
            <small>${escapeHtml(response.answer || 'Cortana puede consultar el loop, pero no ejecutar cambios.')}</small>
            <small>Riesgo evitado: ${escapeHtml(response.risk_avoided || 'sin acción automática')}</small>
            <small>Fuentes: ${escapeHtml((response.source_bundles || []).join(' · ') || 'loop monitor')}</small>
            <a class="pm2-btn pm2-btn--ghost" style="margin-top:8px;text-decoration:none;display:inline-flex" href="${escapeHtml(response.cta || '/loop-monitor#pm2CortanaLoopInterface')}">Abrir evidencia</a>
          </span>
        </div>
      `;
      setStatus(panel, 'Cortana Loop consultada · sin escritura', 'ok');
      toast('success', 'Cortana consultó Automejora en shadow mode');
      return;
    }
    const mission = body.mission_control || body || {};
    const summary = mission.summary || {};
    const metrics = mission.metrics || [];
    const safety = mission.safety || {};
    const metricHtml = metrics.slice(0, 6).map((metric) => `
      <small>${escapeHtml(metric.label || metric.key)}: ${escapeHtml(metric.value ?? 0)}%</small>
    `).join('');
    host.innerHTML = `
      <div class="pm2-voice-candidate">
        <span>
          <strong>AUTOMEJORA CLÍNICA · ${escapeHtml(summary.mode || 'shadow')}</strong>
          <em>${escapeHtml(summary.status || 'shadow')} · ${escapeHtml(summary.overall_pct ?? 0)}% hacia el objetivo final</em>
          <small>Brecha prioritaria: ${escapeHtml(summary.top_gap_title || 'Sin brecha activa')}</small>
          <small>Candidatos: ${escapeHtml(summary.candidate_count ?? 0)} · revisión humana requerida</small>
          <small>Seguridad: auto-merge ${safety.auto_merge_enabled ? 'encendido' : 'apagado'} · sin escritura clínica automática</small>
          ${metricHtml}
          <a class="pm2-btn pm2-btn--ghost" style="margin-top:8px;text-decoration:none;display:inline-flex" href="/loop-monitor">Abrir Loop Monitor</a>
        </span>
      </div>
    `;
    setStatus(panel, 'Automejora consultada · sin escritura', 'ok');
    toast('success', 'Automejora respondió en shadow mode');
  }

  async function handleAutonomousImprovementCommand(panel, transcript) {
    if (!isAutonomousImprovementCommand(transcript)) return false;
    setStatus(panel, 'consultando Automejora Clínica', 'busy');
    const text = String(transcript || '').toLowerCase();
    const endpoint = /ciclo shadow|continuous shadow|brecha prioritaria|autorizar/.test(text)
      ? '/api/autonomous-improvement/continuous-shadow-operation'
      : `/api/autonomous-improvement/cortana-loop-interface?query=${encodeURIComponent(transcript || '')}`;
    let res = await fetch(endpoint);
    if (!res.ok) res = await fetch('/api/autonomous-improvement/mission-control');
    const body = await res.json().catch(() => ({}));
    if (!res.ok || body.success === false) throw new Error(body.error || `HTTP ${res.status}`);
    renderAutonomousImprovementResult(panel, body);
    return true;
  }

  function renderAutodriveResult(panel, body, commandText) {
    const host = panel.querySelector('[data-voice-candidates]');
    if (!host) return;
    const fusion = body.decision_today || body;
    const decision = fusion.decision_today || {};
    const action = fusion.next_safe_action || {};
    const cta = action.cta || {};
    const missingItems = fusion.unified_missing_fields || [];
    const missing = missingItems
      .slice(0, 5)
      .map((item) => item.label || item.field || String(item))
      .join(' · ') || 'Sin dato faltante dominante';
    host.innerHTML = `
      <div class="pm2-voice-candidate">
        <span>
          <strong>DECISIÓN HOY · ${escapeHtml(fusion.decision_state || decision.status || 'not_actionable')}</strong>
          <em>${escapeHtml(decision.label || 'Fusion Kernel')} · ${escapeHtml(fusion.state_label || '')}</em>
          <small>${escapeHtml(decision.title || action.title || 'Sin decision hoy')}</small>
          <small>${escapeHtml(fusion.clinical_rationale || decision.rationale || action.reason || '')}</small>
          <small>Dato requerido: ${escapeHtml(missing)}</small>
          <small>Riesgo evitado: ${escapeHtml(decision.risk_avoided || action.risk_avoided || '—')}</small>
          ${cta.href ? `<a class="pm2-btn pm2-btn--ghost" style="margin-top:8px;text-decoration:none;display:inline-flex" href="${escapeHtml(cta.href)}">${escapeHtml(cta.label || 'Abrir accion')}</a>` : ''}
        </span>
      </div>
    `;
    setStatus(panel, 'Decisión Hoy consultada · sin escritura', 'ok');
    toast('success', 'Decisión Hoy respondió sin escribir al expediente');
    if (String(commandText || '').toLowerCase().includes('abre captura de testosterona')) {
      const patientRef = panel.dataset.patientRef;
      if (patientRef) {
        window.location.href = `/longitudinal-capture/${encodeURIComponent(patientRef)}?decision_lane=crpc_confirmation_readiness&decision_field=testosterone`;
      }
    }
  }

  async function handleAutodriveCommand(panel, transcript) {
    const patientRef = panel.dataset.patientRef;
    if (!patientRef || !isAutodriveCommand(transcript)) return false;
    setStatus(panel, 'consultando Decisión Hoy', 'busy');
    let res = await fetch(`/api/patients/${encodeURIComponent(patientRef)}/decision-today`);
    // Compatibility fallback: /api/patients/${encodeURIComponent(patientRef)}/autodrive
    if (!res.ok) res = await fetch(`/api/patients/${encodeURIComponent(patientRef)}/autodrive`);
    const body = await res.json().catch(() => ({}));
    if (!res.ok || body.success === false) throw new Error(body.error || `HTTP ${res.status}`);
    renderAutodriveResult(panel, body, transcript);
    return true;
  }

  async function createEncounter(panel) {
    setStatus(panel, 'creando sesión local', 'busy');
    const body = await api(panel, encounterBase(panel), {
      body: { ui_surface: panel.dataset.surface || 'patient_profile_v2' },
    });
    setSession(panel, body.session?.session_key || body.session?.session_id);
    setStatus(panel, 'sin consentimiento verbal', 'warn');
    toast('success', 'Sesión de voz creada');
  }

  async function consentEncounter(panel) {
    if (!currentSession(panel)) await createEncounter(panel);
    const spoken = panel.querySelector('[data-voice-consent-text]')?.value || '';
    setStatus(panel, 'registrando consentimiento', 'busy');
    const body = await api(panel, `${encounterBase(panel, currentSession(panel))}/consent`, {
      body: { spoken_text: spoken, signer_name: 'Consentimiento verbal' },
    });
    setSession(panel, body.session?.session_key || body.session?.session_id || currentSession(panel));
    panel.dataset.voiceConsented = 'true';
    setStatus(panel, 'consentido · listo para transcript', 'ok');
    toast('success', 'Consentimiento verbal registrado');
  }

  async function reviewEncounter(panel) {
    const transcript = panel.querySelector('[data-voice-transcript]')?.value || '';
    if (!transcript.trim()) {
      toast('warn', 'Agrega transcript o dicta una nota clínica antes de extraer');
      return;
    }
    if (await handleAutonomousImprovementCommand(panel, transcript)) return;
    if (await handleAutodriveCommand(panel, transcript)) return;
    if (!currentSession(panel)) await createEncounter(panel);
    setStatus(panel, 'extrayendo candidatos', 'busy');
    const body = await api(panel, `${encounterBase(panel, currentSession(panel))}/review`, {
      body: { transcript_text: transcript, append: false },
    });
    renderCandidates(panel, body.candidates || []);
    setStatus(panel, 'revisión médica pendiente', 'warn');
    if (autoApplyEnabled(panel) && body.fields && Object.keys(body.fields).length) {
      emitApply(panel, body, 'voice_review_auto_apply');
      setStatus(panel, 'aplicado al clasificador', 'ok');
    }
    toast('success', `${(body.candidates || []).length} candidatos listos para revisión`);
  }

  async function sendAudio(panel, blob, options = {}) {
    const sessionKey = currentSession(panel);
    if (!sessionKey) {
      toast('warn', 'Primero crea una sesión de voz');
      return;
    }
    const form = new FormData();
    const mime = blob.type || 'audio/webm';
    const ext = mime.includes('wav') ? 'wav' : mime.includes('mp4') ? 'm4a' : mime.includes('ogg') ? 'ogg' : 'webm';
    form.append('audio', blob, `voice.${ext}`);
    form.append('mime_type', mime);
    const shouldTranscribe = options.transcribe !== false;
    form.append('transcribe', shouldTranscribe ? 'true' : 'false');
    form.append('chunk_index', String(options.chunkIndex ?? ''));
    form.append('final', options.final ? 'true' : 'false');
    form.append('auto_apply', options.autoApply ? 'true' : 'false');
    setStatus(panel, options.final ? 'transcribiendo audio final' : 'recibiendo audio', 'busy');
    const res = await fetch(`${encounterBase(panel, sessionKey)}/audio`, {
      method: 'POST',
      body: form,
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok || body.success === false) throw new Error(body.error || `HTTP ${res.status}`);
    appendTranscript(panel, body);
    renderCandidates(panel, body.candidates || []);
    const st = body.audio?.transcription_status || 'audio_stored';
    if (st === 'not_requested') {
      if (panel.dataset.voiceRecording === 'true') {
        setStatus(panel, 'grabando · audio protegido', 'busy');
        renderCandidatesMessage(panel, 'Grabando. Los candidatos aparecerán después de transcribir el audio final.');
      } else {
        setStatus(panel, 'audio cifrado recibido', 'warn');
      }
    } else if (st === 'requires_local_stt_sidecar_not_found') {
      // EPIC 24d/24e — sidecar venv missing
      setStatus(panel, 'STT no configurado · contactar admin', 'error');
      toast('error',
        'STT local no configurado. El audio se cifró pero no se transcribió. ' +
        'Pide al administrador instalar el módulo de voz (.venv-voice311 con faster-whisper).');
    } else if (st === 'requires_local_stt_disabled') {
      setStatus(panel, 'STT deshabilitado por admin', 'error');
      toast('error',
        'STT local desactivado por configuración (VOICE_STT_DISABLE). ' +
        'Pide al administrador habilitarlo si necesitas dictado por voz.');
    } else if (st === 'requires_local_stt_other' || st === 'requires_local_stt') {
      // EPIC 24e — legacy + unknown blocker
      const detail = body.audio?.stt_diagnose?.blockers?.[0] || '';
      setStatus(panel, 'audio cifrado · STT local pendiente', 'warn');
      toast('warn',
        'Audio cifrado guardado. ' +
        (detail ? `Diagnóstico: ${detail.slice(0, 100)}` :
          'Instala faster-whisper para transcribir localmente.'));
    } else if (st === 'partial_audio_buffering') {
      setStatus(panel, 'buffer parcial · esperando más audio', 'warn');
    } else if (st === 'empty_transcript') {
      setStatus(panel, 'audio recibido · sin voz detectable', 'warn');
    } else if (st === 'transcribed') {
      if (autoApplyEnabled(panel) && body.fields && Object.keys(body.fields).length) {
        emitApply(panel, body, options.final ? 'voice_final_auto_apply' : 'voice_chunk_auto_apply');
        setStatus(panel, 'voz aplicada al clasificador', 'ok');
      } else {
        setStatus(panel, 'audio transcrito · revisión pendiente', 'warn');
      }
      toast('success', `${(body.candidates || []).length} candidatos desde voz`);
    } else if (st === 'stt_error') {
      const detail = body.audio?.stt_status_detail || 'decode_failed';
      setStatus(panel, `error real de STT · ${detail}`, 'error');
      toast('error', 'El audio fue recibido, pero el STT local no pudo transcribirlo.');
    } else {
      setStatus(panel, st, 'warn');
      toast('info', `Audio guardado: ${st}`);
    }
  }

  async function startRecording(panel) {
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      toast('warn', 'Este navegador no permite grabación local. Usa transcript manual.');
      return;
    }
    if (!currentSession(panel)) await createEncounter(panel);
    if (panel.dataset.voiceConsented !== 'true') {
      toast('warn', 'Registra el consentimiento verbal antes de grabar.');
      return;
    }
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const options = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
      ? { mimeType: 'audio/webm;codecs=opus' }
      : {};
    const recorder = new MediaRecorder(stream, options);
    panel._voiceChunks = [];
    panel._voiceStream = stream;
    panel._voiceRecorder = recorder;
    recorder.ondataavailable = (event) => {
      if (event.data && event.data.size > 0) panel._voiceChunks.push(event.data);
    };
    recorder.onerror = () => {
      setStatus(panel, 'error de grabación local', 'error');
    };
    recorder.onstop = async () => {
      try {
        await (panel._voiceSendQueue || Promise.resolve());
        const blob = new Blob(panel._voiceChunks || [], { type: recorder.mimeType || 'audio/webm' });
        if (blob.size > 0) {
          await sendAudio(panel, blob, {
            chunkIndex: panel._voiceChunkIndex || 0,
            final: true,
            transcribe: true,
            autoApply: autoApplyEnabled(panel),
          });
        }
      } catch (err) {
        setStatus(panel, err.message || 'audio error', 'error');
        toast('error', err.message || String(err));
      } finally {
        (panel._voiceStream?.getTracks?.() || []).forEach((track) => track.stop());
        panel._voiceRecorder = null;
        panel._voiceStream = null;
        panel._voiceChunks = [];
        panel._voiceStopping = false;
        setRecordingControls(panel, false);
      }
    };
    panel._voiceChunkIndex = 0;
    panel._voiceSendQueue = Promise.resolve();
    panel._voiceStopping = false;
    recorder.start();
    setRecordingControls(panel, true);
    setStatus(panel, 'grabando', 'busy');
    renderCandidatesMessage(panel, 'Grabando. Hable con frases clínicas explícitas; Cortana transcribirá y propondrá candidatos al detener.');
    toast('info', 'Grabación local iniciada');
  }

  function stopRecording(panel) {
    const recorder = panel._voiceRecorder;
    if (!recorder || recorder.state === 'inactive') {
      toast('warn', 'No hay grabación activa');
      return;
    }
    setStatus(panel, 'deteniendo · preparando transcripción', 'busy');
    panel._voiceStopping = true;
    recorder.stop();
  }

  async function commitEncounter(panel) {
    const sessionKey = currentSession(panel);
    if (!sessionKey) {
      toast('warn', 'Primero crea una sesión de voz');
      return;
    }
    const patientRef = panel.dataset.patientRef;
    const accepted = Array.from(panel.querySelectorAll('[data-voice-candidate-key]:checked'))
      .map((el) => el.dataset.voiceCandidateKey)
      .filter(Boolean);
    if (!accepted.length) {
      toast('warn', 'Selecciona al menos un candidato revisado');
      return;
    }
    setStatus(panel, 'firmando y escribiendo expediente', 'busy');
    const body = await api(panel, `${encounterBase(panel, sessionKey)}/commit`, {
      body: { accepted_candidate_keys: accepted, verified_by: 'clinico' },
    });
    setStatus(panel, 'firmado · expediente actualizado', 'ok');
    toast('success', `Cortana escribió ${accepted.length} campos revisados`);
    try {
      localStorage.setItem('pm2_capture_event', JSON.stringify({ nss: patientRef, kind: 'voice', ts: Date.now(), decision_changed: !!body.recompute }));
    } catch (err) { /* ignore */ }
    setTimeout(() => window.location.reload(), 1200);
  }

  async function applyIntakeEncounter(panel) {
    const sessionKey = currentSession(panel);
    if (!sessionKey) {
      toast('warn', 'Primero crea una sesión de voz');
      return;
    }
    const accepted = Array.from(panel.querySelectorAll('[data-voice-candidate-key]:checked'))
      .map((el) => el.dataset.voiceCandidateKey)
      .filter(Boolean);
    if (!accepted.length) {
      toast('warn', 'Selecciona al menos un candidato revisado');
      return;
    }
    setStatus(panel, 'aplicando al clasificador', 'busy');
    const body = await api(panel, `${encounterBase(panel, sessionKey)}/apply`, {
      body: { accepted_candidate_keys: accepted },
    });
    panel.dispatchEvent(new CustomEvent('prostanet:voice-intake-apply', {
      bubbles: true,
      detail: {
        fields: body.fields || {},
        provenance: body.provenance || {},
        session: body.session || {},
        candidates: body.candidates || [],
        conflicts: body.conflicts || [],
        source: 'voice_manual_apply',
      },
    }));
    setStatus(panel, 'aplicado al clasificador', 'ok');
    toast('success', `${Object.keys(body.fields || {}).length} campos aplicados al clasificador`);
  }

  function toggleAutoApply(panel) {
    const enabled = autoApplyEnabled(panel);
    panel.dataset.voiceAutoApply = enabled ? 'false' : 'true';
    const button = panel.querySelector('[data-voice-action="toggle-auto"]');
    setButtonLabel(button, enabled ? 'Reanudar auto-aplicación' : 'Pausar auto-aplicación');
    setStatus(panel, enabled ? 'auto-aplicación pausada' : 'auto-aplicación activa', enabled ? 'warn' : 'ok');
  }

  function undoLastVoiceChange(panel) {
    panel.dispatchEvent(new CustomEvent('prostanet:voice-intake-undo', { bubbles: true }));
  }

  function reviewVoiceChanges(panel) {
    renderVoiceLog(panel);
    const host = panel.querySelector('[data-voice-change-log]');
    if (host) host.hidden = !host.hidden;
  }

  async function discardEncounter(panel) {
    const sessionKey = currentSession(panel);
    if (!sessionKey) return;
    setStatus(panel, 'descartando sesión', 'busy');
    await api(panel, `${encounterBase(panel, sessionKey)}/discard`, {
      body: { reason: 'discarded_from_ui' },
    });
    setSession(panel, '');
    panel.dataset.voiceConsented = 'false';
    renderCandidates(panel, []);
    setStatus(panel, 'descartado', 'idle');
    toast('info', 'Sesión de voz descartada');
  }

  panels.forEach((panel) => {
    setRecordingControls(panel, false);
    panel.addEventListener('click', async (event) => {
      const button = event.target.closest('[data-voice-action]');
      if (!button) return;
      event.preventDefault();
      const action = button.dataset.voiceAction;
      const transientAction = !['record', 'stop'].includes(action);
      if (transientAction) button.disabled = true;
      try {
        if (action === 'create') await createEncounter(panel);
        if (action === 'consent') await consentEncounter(panel);
        if (action === 'record') await startRecording(panel);
        if (action === 'stop') stopRecording(panel);
        if (action === 'review') await reviewEncounter(panel);
        if (action === 'commit') await commitEncounter(panel);
        if (action === 'apply') await applyIntakeEncounter(panel);
        if (action === 'toggle-auto') toggleAutoApply(panel);
        if (action === 'undo') undoLastVoiceChange(panel);
        if (action === 'review-changes') reviewVoiceChanges(panel);
        if (action === 'discard') await discardEncounter(panel);
      } catch (err) {
        setStatus(panel, err.message || 'error', 'error');
        toast('error', err.message || String(err));
      } finally {
        if (transientAction) button.disabled = false;
        if (panel.dataset.voiceRecording === 'true') setRecordingControls(panel, true);
      }
    });
  });
  document.addEventListener('prostanet:voice-intake-applied', (event) => {
    const panel = panels.find((item) => isIntakePanel(item));
    if (!panel) return;
    panel._voiceApplyHistory = event.detail?.history || panel._voiceApplyHistory || [];
    renderVoiceLog(panel);
  });
})();
