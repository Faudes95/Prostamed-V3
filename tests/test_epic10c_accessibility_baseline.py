# IEC 62304 §5.7 (System testing)
"""Tests EPIC 10C — Accessibility baseline (WCAG 2.1 AA static checks).

Audita las páginas HTML clave del CDE Auditable contra reglas WCAG 2.1 AA
**estáticas** (parseables del DOM sin browser): lang attribute, title
no vacío, alt text en images, label association en inputs, jerarquía
de headings, links/buttons descriptivos.

No usa Lighthouse ni axe-core (deps externos). Usa stdlib `html.parser`
para parsear el HTML servido vía Flask test client. Cubre el 80% de las
violaciones críticas WCAG sin requerir Chrome headless.

Reglas WCAG cubiertas:
  - 3.1.1 Language of Page    → <html lang="es"> presente
  - 2.4.2 Page Titled          → <title> ≥ 5 chars
  - 1.1.1 Non-text Content     → cada <img> con alt
  - 1.3.1 Info and Relationships → <input> con <label for=> o aria-label
  - 2.4.6 Headings and Labels  → al menos 1 <h1>, no headings vacíos
  - 2.4.4 Link Purpose         → <a> con texto/aria-label no vacío
  - 4.1.2 Name, Role, Value    → <button> con texto/aria-label

NO cubierto (requiere browser):
  - 1.4.3 Contrast (Minimum) — necesita render visual
  - 2.4.7 Focus Visible — necesita interacción
  - 1.4.10 Reflow — necesita responsive testing
"""
from __future__ import annotations

from html.parser import HTMLParser
from typing import Any

import pytest


# Páginas a auditar (paths + label descriptivo).
WCAG_TARGET_PAGES = [
    ("/clinical-hub", "Centro clínico"),
    ("/patient_intake", "Intake progresivo"),
    ("/dashboard", "Dashboard ejecutivo"),
]


class _AccessibilityAuditParser(HTMLParser):
    """Parser stdlib que extrae los datos relevantes para auditoría WCAG."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.html_lang: str | None = None
        self.title_text: str = ""
        self.in_title: bool = False
        self.images: list[dict[str, Any]] = []
        self.inputs: list[dict[str, Any]] = []
        self.labels_with_for: set[str] = set()
        self.label_aria_describedby_ids: set[str] = set()
        self.aria_labelledby_ids: set[str] = set()
        self.headings: list[tuple[int, str]] = []  # (level, text)
        self.in_heading: int | None = None
        self.current_heading_text: str = ""
        self.links: list[dict[str, Any]] = []
        self.in_link: bool = False
        self.current_link_text: str = ""
        self.current_link_attrs: dict[str, str] = {}
        self.buttons: list[dict[str, Any]] = []
        self.in_button: bool = False
        self.current_button_text: str = ""
        self.current_button_attrs: dict[str, str] = {}
        self.skip_link_present: bool = False
        self._body_first_anchor_checked: bool = False

    def handle_starttag(self, tag, attrs):
        attr_dict = {k: (v or "") for k, v in attrs}
        if tag == "html":
            self.html_lang = attr_dict.get("lang")
        elif tag == "title":
            self.in_title = True
        elif tag == "img":
            self.images.append({
                "alt": attr_dict.get("alt"),
                "src": attr_dict.get("src", ""),
                "role": attr_dict.get("role", ""),
                "aria_hidden": attr_dict.get("aria-hidden", ""),
            })
        elif tag == "input":
            itype = attr_dict.get("type", "text").lower()
            if itype not in {"hidden", "submit", "button", "reset", "image"}:
                self.inputs.append({
                    "id": attr_dict.get("id", ""),
                    "name": attr_dict.get("name", ""),
                    "type": itype,
                    "aria_label": attr_dict.get("aria-label", ""),
                    "aria_labelledby": attr_dict.get("aria-labelledby", ""),
                    "placeholder": attr_dict.get("placeholder", ""),
                })
        elif tag == "label":
            for_attr = attr_dict.get("for")
            if for_attr:
                self.labels_with_for.add(for_attr)
        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.in_heading = int(tag[1])
            self.current_heading_text = ""
        elif tag == "a":
            self.in_link = True
            self.current_link_text = ""
            self.current_link_attrs = dict(attr_dict)
            href = attr_dict.get("href", "")
            if href.startswith("#") and not self._body_first_anchor_checked:
                # Posible skip link al inicio del body
                target = href.lstrip("#")
                if target in {"main", "content", "main-content"}:
                    self.skip_link_present = True
            self._body_first_anchor_checked = True
        elif tag == "button":
            self.in_button = True
            self.current_button_text = ""
            self.current_button_attrs = dict(attr_dict)
        # Track aria-labelledby targets para validar references
        ref = attr_dict.get("aria-labelledby")
        if ref:
            for token in ref.split():
                self.aria_labelledby_ids.add(token)

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            if self.in_heading is not None:
                self.headings.append((self.in_heading, self.current_heading_text.strip()))
            self.in_heading = None
            self.current_heading_text = ""
        elif tag == "a":
            if self.in_link:
                self.links.append({
                    **self.current_link_attrs,
                    "text": self.current_link_text.strip(),
                })
            self.in_link = False
            self.current_link_text = ""
            self.current_link_attrs = {}
        elif tag == "button":
            if self.in_button:
                self.buttons.append({
                    **self.current_button_attrs,
                    "text": self.current_button_text.strip(),
                })
            self.in_button = False
            self.current_button_text = ""
            self.current_button_attrs = {}

    def handle_data(self, data):
        if self.in_title:
            self.title_text += data
        if self.in_heading is not None:
            self.current_heading_text += data
        if self.in_link:
            self.current_link_text += data
        if self.in_button:
            self.current_button_text += data


def _audit_html(html: str) -> dict[str, Any]:
    """Ejecuta los checks WCAG 2.1 AA estáticos sobre un HTML string."""
    parser = _AccessibilityAuditParser()
    parser.feed(html)

    violations: list[str] = []

    # WCAG 3.1.1 — Language of Page
    if not parser.html_lang or len(parser.html_lang.strip()) < 2:
        violations.append(f"WCAG_3_1_1: <html lang> ausente o inválido (lang={parser.html_lang!r})")

    # WCAG 2.4.2 — Page Titled
    title = parser.title_text.strip()
    if len(title) < 5:
        violations.append(f"WCAG_2_4_2: <title> demasiado corto ({len(title)} chars): {title!r}")

    # WCAG 1.1.1 — Non-text Content (cada img necesita alt o aria-hidden)
    imgs_missing_alt = [
        img for img in parser.images
        if img["alt"] is None and img["aria_hidden"].lower() != "true" and img["role"].lower() != "presentation"
    ]
    if imgs_missing_alt:
        violations.append(
            f"WCAG_1_1_1: {len(imgs_missing_alt)} <img> sin alt ni aria-hidden. "
            f"Primeros 3 src: {[i['src'][:80] for i in imgs_missing_alt[:3]]}"
        )

    # WCAG 1.3.1 — Info and Relationships (inputs con label)
    inputs_unlabeled = []
    for inp in parser.inputs:
        has_label_for = inp["id"] and inp["id"] in parser.labels_with_for
        has_aria_label = bool(inp["aria_label"].strip())
        has_aria_labelledby = bool(inp["aria_labelledby"].strip())
        if not (has_label_for or has_aria_label or has_aria_labelledby):
            inputs_unlabeled.append(inp)
    if inputs_unlabeled:
        violations.append(
            f"WCAG_1_3_1: {len(inputs_unlabeled)} <input> sin label, aria-label ni "
            f"aria-labelledby. Primeros 3 name/id: "
            f"{[(i['name'] or i['id'])[:40] for i in inputs_unlabeled[:3]]}"
        )

    # WCAG 2.4.6 — Headings and Labels
    h1_count = sum(1 for level, _ in parser.headings if level == 1)
    if h1_count == 0:
        violations.append("WCAG_2_4_6: la página NO tiene <h1>. Cada página debe declarar al menos un H1.")
    elif h1_count > 1:
        violations.append(f"WCAG_2_4_6: la página tiene {h1_count} <h1>. Recomendado: exactamente 1.")
    empty_headings = [(lvl, txt) for lvl, txt in parser.headings if not txt]
    if empty_headings:
        violations.append(f"WCAG_2_4_6: {len(empty_headings)} headings con texto vacío.")

    # WCAG 2.4.4 — Link Purpose (cada <a> con texto o aria-label)
    links_empty = []
    for link in parser.links:
        has_text = bool(link.get("text", "").strip())
        has_aria = bool((link.get("aria-label") or "").strip())
        # Skip enlaces decorativos / icon-only que tengan aria-label
        if not has_text and not has_aria:
            href = link.get("href", "")
            # Anclas vacías son sospechosas pero comunes en SPAs — flagear solo si href != ""
            if href and href != "#":
                links_empty.append({"href": href[:80]})
    if links_empty:
        violations.append(
            f"WCAG_2_4_4: {len(links_empty)} <a> sin texto ni aria-label. "
            f"Primeros 3 href: {[l['href'] for l in links_empty[:3]]}"
        )

    # WCAG 4.1.2 — Name, Role, Value (cada <button> con texto o aria-label)
    buttons_empty = []
    for btn in parser.buttons:
        has_text = bool(btn.get("text", "").strip())
        has_aria = bool((btn.get("aria-label") or "").strip())
        if not has_text and not has_aria:
            buttons_empty.append({"type": btn.get("type", ""), "id": btn.get("id", "")})
    if buttons_empty:
        violations.append(
            f"WCAG_4_1_2: {len(buttons_empty)} <button> sin texto ni aria-label."
        )

    return {
        "violations": violations,
        "summary": {
            "html_lang": parser.html_lang,
            "title": title,
            "title_length": len(title),
            "images_total": len(parser.images),
            "images_missing_alt": len(imgs_missing_alt),
            "inputs_total": len(parser.inputs),
            "inputs_unlabeled": len(inputs_unlabeled),
            "headings_total": len(parser.headings),
            "h1_count": h1_count,
            "links_total": len(parser.links),
            "links_empty": len(links_empty),
            "buttons_total": len(parser.buttons),
            "buttons_empty": len(buttons_empty),
            "skip_link_present": parser.skip_link_present,
        },
    }


@pytest.mark.parametrize("path,label", WCAG_TARGET_PAGES)
def test_epic10c_page_responds_with_html(app_client, path, label):
    """Smoke: cada página WCAG target debe retornar HTML válido (200/3xx + tag <html>)."""
    client, _ = app_client
    response = client.get(path)
    assert response.status_code < 500, (
        f"{path} ({label}): status {response.status_code}. WCAG audit imposible."
    )
    html = response.get_data(as_text=True)
    assert "<html" in html.lower(), f"{path}: response no contiene <html> tag."


@pytest.mark.parametrize("path,label", WCAG_TARGET_PAGES)
def test_epic10c_page_has_html_lang(app_client, path, label):
    """WCAG 3.1.1 — <html lang> debe estar presente y ser código de lenguaje válido."""
    client, _ = app_client
    response = client.get(path, follow_redirects=True)
    audit = _audit_html(response.get_data(as_text=True))
    summary = audit["summary"]
    assert summary["html_lang"], (
        f"{path} ({label}): <html lang> ausente. WCAG 3.1.1 viola."
    )
    assert len(summary["html_lang"]) >= 2, (
        f"{path} ({label}): <html lang> demasiado corto: {summary['html_lang']!r}"
    )


@pytest.mark.parametrize("path,label", WCAG_TARGET_PAGES)
def test_epic10c_page_has_descriptive_title(app_client, path, label):
    """WCAG 2.4.2 — <title> debe estar presente y ≥ 5 chars."""
    client, _ = app_client
    response = client.get(path, follow_redirects=True)
    audit = _audit_html(response.get_data(as_text=True))
    summary = audit["summary"]
    assert summary["title_length"] >= 5, (
        f"{path} ({label}): <title> demasiado corto ({summary['title_length']} chars). "
        f"Encontrado: {summary['title']!r}"
    )


@pytest.mark.parametrize("path,label", WCAG_TARGET_PAGES)
def test_epic10c_page_has_exactly_one_h1_landmark(app_client, path, label):
    """WCAG 2.4.6 — cada página debe declarar exactamente UN <h1>.

    Pre-EPIC 10C+: clinical-hub/patient_intake tenían 7 H1s (loop sobre
    7 stage canvases en stage_clinical_center_v2_redesign.html). Fixed por
    EPIC 10C+ multi-H1 promoción de los 7 H1 de stage headers a H2 +
    declaración de UN H1 global sr-only "Centro Clínico · ProstaMed".

    Múltiples H1 confunde screen readers (no hay landmark único) y
    daña la jerarquía outline del documento. WCAG 2.4.6 recomienda
    exactamente 1 H1 por página HTML.
    """
    client, _ = app_client
    response = client.get(path, follow_redirects=True)
    audit = _audit_html(response.get_data(as_text=True))
    summary = audit["summary"]
    assert summary["h1_count"] == 1, (
        f"{path} ({label}): se esperaba exactamente 1 <h1>, encontrado "
        f"{summary['h1_count']}. Headings totales: {summary['headings_total']}. "
        "Múltiples H1 rompen jerarquía outline para screen readers."
    )


@pytest.mark.parametrize("path,label", WCAG_TARGET_PAGES)
def test_epic10c_page_all_images_have_alt(app_client, path, label):
    """WCAG 1.1.1 — cada <img> debe tener alt (puede ser vacío para decorativos)."""
    client, _ = app_client
    response = client.get(path, follow_redirects=True)
    audit = _audit_html(response.get_data(as_text=True))
    summary = audit["summary"]
    assert summary["images_missing_alt"] == 0, (
        f"{path} ({label}): {summary['images_missing_alt']} de {summary['images_total']} "
        "imágenes sin alt ni aria-hidden."
    )


@pytest.mark.parametrize("path,label", WCAG_TARGET_PAGES)
def test_epic10c_page_buttons_have_accessible_name(app_client, path, label):
    """WCAG 4.1.2 — cada <button> debe tener texto o aria-label."""
    client, _ = app_client
    response = client.get(path, follow_redirects=True)
    audit = _audit_html(response.get_data(as_text=True))
    summary = audit["summary"]
    assert summary["buttons_empty"] == 0, (
        f"{path} ({label}): {summary['buttons_empty']} de {summary['buttons_total']} "
        "buttons sin nombre accesible."
    )


def test_epic10c_accessibility_summary_table(app_client):
    """Summary table — diagnóstico no-bloqueante de todas las páginas."""
    client, _ = app_client
    rows = []
    for path, label in WCAG_TARGET_PAGES:
        response = client.get(path, follow_redirects=True)
        audit = _audit_html(response.get_data(as_text=True))
        rows.append((label, path, audit["summary"], len(audit["violations"])))
    print("\nEPIC 10C accessibility baseline:")
    for label, path, summary, n_viol in rows:
        print(
            f"  {label[:30]:<30s}  H1={summary['h1_count']}  "
            f"imgs_no_alt={summary['images_missing_alt']}/{summary['images_total']}  "
            f"inputs_unlabeled={summary['inputs_unlabeled']}/{summary['inputs_total']}  "
            f"buttons_empty={summary['buttons_empty']}/{summary['buttons_total']}  "
            f"violations={n_viol}"
        )
    assert len(rows) == len(WCAG_TARGET_PAGES)
