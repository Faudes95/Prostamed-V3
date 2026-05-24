"""Sprint 4 — Clinical Hub UX refinement (ui-ux-pro-max QR §1-§2).

FIX UX-1: .pm2-btn min-height 36px → 44px (Apple HIG / Material 48dp / WCAG 2.5.5)
FIX UX-2: Cortana transcript textarea con <label> visible + aria-label + data-testid
          (anti-pattern placeholder-only resuelto)

FAUBOT CXL — 2026-05-24.
"""
from __future__ import annotations


# ─────────────────────────────────────────────────────────────────────
# FIX UX-1 — pm2-btn min-height 44px (touch target compliance)
# ─────────────────────────────────────────────────────────────────────


def test_sprint4_uxA_pm2_btn_min_height_44px():
    """CSS .pm2-btn debe declarar min-height: 44px (era 36px)."""
    from pathlib import Path
    css = Path(__file__).parent.parent / "static" / "css" / "prostamed_v2.css"
    content = css.read_text(encoding="utf-8")
    # Encontrar el bloque .pm2-btn
    btn_idx = content.find(".pm2-btn {")
    assert btn_idx > -1
    btn_block = content[btn_idx:btn_idx + 800]
    # Debe contener min-height: 44px (no 36)
    assert "min-height: 44px" in btn_block, (
        "FIX UX-1: .pm2-btn debe tener min-height: 44px para touch target"
    )
    assert "min-height: 36px" not in btn_block, (
        "FIX UX-1: min-height: 36px aún presente — falta actualizar"
    )


def test_sprint4_uxA_css_has_wcag_touch_target_comment():
    """CSS comment debe documentar el por qué (WCAG / Apple HIG / Material)."""
    from pathlib import Path
    css = Path(__file__).parent.parent / "static" / "css" / "prostamed_v2.css"
    content = css.read_text(encoding="utf-8")
    btn_idx = content.find(".pm2-btn {")
    btn_block = content[btn_idx:btn_idx + 800]
    # Documentación del fix con referencia normativa
    assert any(ref in btn_block for ref in (
        "Apple HIG", "Material", "WCAG", "44pt", "touch target"
    )), "CSS comment debe citar estándar (Apple HIG / Material / WCAG)"


# ─────────────────────────────────────────────────────────────────────
# FIX UX-2 — Cortana textarea label + aria-label + testid
# ─────────────────────────────────────────────────────────────────────


def test_sprint4_uxB_cortana_textarea_has_label_for_attribute():
    """Template clinical hub debe tener <label for='pm2-voice-transcript-input'>."""
    from pathlib import Path
    template = (
        Path(__file__).parent.parent
        / "templates" / "demos" / "stage_clinical_center_v2_redesign.html"
    )
    content = template.read_text(encoding="utf-8")
    assert 'for="pm2-voice-transcript-input"' in content, (
        "FIX UX-2: textarea debe tener <label for='pm2-voice-transcript-input'>"
    )
    assert 'id="pm2-voice-transcript-input"' in content, (
        "FIX UX-2: textarea debe tener id='pm2-voice-transcript-input'"
    )


def test_sprint4_uxB_cortana_textarea_has_aria_label():
    """Textarea debe tener aria-label descriptivo (no placeholder-only)."""
    from pathlib import Path
    template = (
        Path(__file__).parent.parent
        / "templates" / "demos" / "stage_clinical_center_v2_redesign.html"
    )
    content = template.read_text(encoding="utf-8")
    # aria-label específico al transcript
    cortana_idx = content.find('id="pm2-voice-transcript-input"')
    assert cortana_idx > -1
    # Look around the textarea (~500 chars before+after) for aria-label
    surrounding = content[max(0, cortana_idx - 500):cortana_idx + 500]
    assert "aria-label=" in surrounding, (
        "FIX UX-2: textarea debe tener aria-label además de label visible"
    )
    assert "Cortana" in surrounding or "transcript" in surrounding.lower()


def test_sprint4_uxB_cortana_textarea_has_data_testid():
    """data-testid='cortana-transcript-textarea' para automated UI tests."""
    from pathlib import Path
    template = (
        Path(__file__).parent.parent
        / "templates" / "demos" / "stage_clinical_center_v2_redesign.html"
    )
    content = template.read_text(encoding="utf-8")
    assert 'data-testid="cortana-transcript-textarea"' in content, (
        "FIX UX-2: testid 'cortana-transcript-textarea' falta"
    )


def test_sprint4_uxB_cortana_label_visible_text():
    """Label visible debe contener texto descriptivo (no solo decoración)."""
    from pathlib import Path
    template = (
        Path(__file__).parent.parent
        / "templates" / "demos" / "stage_clinical_center_v2_redesign.html"
    )
    content = template.read_text(encoding="utf-8")
    # Buscar el <label for="pm2-voice-transcript-input">
    label_idx = content.find('for="pm2-voice-transcript-input"')
    if label_idx > -1:
        # Look at next 200 chars to find label text content
        label_section = content[label_idx:label_idx + 400]
        assert "Transcript" in label_section, (
            "Label visible debe mencionar 'Transcript' como descriptor del field"
        )


# ─────────────────────────────────────────────────────────────────────
# Integration — UX score improvement
# ─────────────────────────────────────────────────────────────────────


def test_sprint4_integration_no_placeholder_only_inputs_in_classifier():
    """Source-level: ningún textarea/input del classifier debe ser
    placeholder-only (sin label/aria-label)."""
    from pathlib import Path
    template = (
        Path(__file__).parent.parent
        / "templates" / "demos" / "stage_clinical_center_v2_redesign.html"
    )
    content = template.read_text(encoding="utf-8")
    # Smoke: el textarea principal (Cortana) ya tiene label + aria-label.
    # Window amplio para capturar el <label for=...> que precede al textarea.
    cortana_idx = content.find('id="pm2-voice-transcript-input"')
    if cortana_idx > -1:
        # Window: -800/+800 chars (el label puede estar más arriba)
        surrounding = content[max(0, cortana_idx - 800):cortana_idx + 800]
        # Debe haber label for= O aria-label cerca
        has_label = 'for="pm2-voice-transcript-input"' in surrounding
        has_aria = "aria-label=" in surrounding
        assert has_label or has_aria, (
            f"Cortana textarea principal sin label ni aria-label. "
            f"Window snippet: {surrounding[:300]!r}"
        )
