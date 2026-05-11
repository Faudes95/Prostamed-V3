from __future__ import annotations

from html import escape
from math import ceil
from typing import Any
from urllib.parse import quote

from prostanet.shared.metastatic_profile import summarize_metastatic_profile


def _data_uri(svg: str) -> str:
    return f"data:image/svg+xml;utf8,{quote(svg)}"


def _marker_cluster(x: float, y: float, count: int, color: str = "#f97316") -> str:
    count = max(int(count or 0), 1)
    circles = []
    for index in range(min(count, 4)):
        dx = (index % 2) * 12 - 6
        dy = (index // 2) * 12 - 6
        circles.append(
            f'<circle cx="{x + dx}" cy="{y + dy}" r="6" fill="{color}" opacity="0.95"/>'
            f'<circle cx="{x + dx}" cy="{y + dy}" r="10" fill="{color}" opacity="0.18"/>'
        )
    badge = ""
    if count > 1:
        badge = (
            f'<rect x="{x + 14}" y="{y - 14}" rx="10" ry="10" width="26" height="20" fill="#082f49" opacity="0.9"/>'
            f'<text x="{x + 27}" y="{y}" font-size="11" text-anchor="middle" fill="#e0f2fe" font-weight="700">x{count}</text>'
        )
    return "".join(circles) + badge


def _card_shell(title: str, subtitle: str, body: str, footer: str = "") -> str:
    footer_svg = ""
    if footer:
        footer_svg = f'<text x="380" y="594" font-size="16" text-anchor="middle" fill="#334155">{escape(footer)}</text>'
    return f"""
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 620">
      <defs>
        <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stop-color="#f8fbff"/>
          <stop offset="100%" stop-color="#e9f2ff"/>
        </linearGradient>
        <linearGradient id="panel" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stop-color="#ffffff"/>
          <stop offset="100%" stop-color="#eef4ff"/>
        </linearGradient>
        <filter id="shadow" x="-20%" y="-20%" width="140%" height="140%">
          <feDropShadow dx="0" dy="8" stdDeviation="12" flood-color="#0f172a" flood-opacity="0.12"/>
        </filter>
      </defs>
      <rect width="760" height="620" rx="28" fill="url(#bg)"/>
      <rect x="22" y="22" width="716" height="576" rx="26" fill="url(#panel)" filter="url(#shadow)"/>
      <rect x="44" y="44" width="132" height="60" rx="14" fill="#123a69"/>
      <text x="110" y="84" font-size="36" text-anchor="middle" fill="#fff" font-weight="800">{escape(title)}</text>
      <text x="208" y="82" font-size="30" fill="#123a69" font-weight="700">{escape(subtitle)}</text>
      {body}
      {footer_svg}
    </svg>
    """


def _render_m1a(profile: dict[str, Any]) -> str:
    count = max(int(profile.get("nonregional_nodal_count") or 0), 1)
    summary = summarize_metastatic_profile(profile)
    body = f"""
      <path d="M320 162c56-62 144-62 200 0v238c-56 46-144 46-200 0z" fill="#7dd3fc" opacity="0.24"/>
      <path d="M300 184c40-56 124-72 162-18v188c-44 36-110 36-154 0z" fill="#38bdf8" opacity="0.28"/>
      <circle cx="366" cy="196" r="18" fill="#22c55e"/><circle cx="366" cy="196" r="30" fill="#22c55e" opacity="0.18"/>
      <circle cx="318" cy="248" r="18" fill="#22c55e"/><circle cx="318" cy="248" r="30" fill="#22c55e" opacity="0.18"/>
      <circle cx="494" cy="224" r="18" fill="#22c55e"/><circle cx="494" cy="224" r="30" fill="#22c55e" opacity="0.18"/>
      <circle cx="542" cy="282" r="18" fill="#22c55e"/><circle cx="542" cy="282" r="30" fill="#22c55e" opacity="0.18"/>
      <circle cx="402" cy="350" r="18" fill="#22c55e"/><circle cx="402" cy="350" r="30" fill="#22c55e" opacity="0.18"/>
      <line x1="248" y1="240" x2="298" y2="248" stroke="#64748b" stroke-width="2"/>
      <line x1="560" y1="212" x2="512" y2="220" stroke="#64748b" stroke-width="2"/>
      <line x1="426" y1="336" x2="510" y2="380" stroke="#64748b" stroke-width="2"/>
      <text x="112" y="238" font-size="20" fill="#334155">Ganglios no regionales</text>
      <text x="112" y="266" font-size="16" fill="#64748b">Conteo documentado: {count}</text>
      <rect x="86" y="404" width="220" height="72" rx="18" fill="#ecfdf5" stroke="#86efac"/>
      <text x="196" y="438" text-anchor="middle" font-size="20" fill="#166534" font-weight="700">M1a</text>
      <text x="196" y="462" text-anchor="middle" font-size="14" fill="#166534">Ganglios alejados del territorio regional</text>
    """
    return _card_shell("M1a", "Metástasis ganglionares no regionales", body, summary)


def _render_m1b(profile: dict[str, Any]) -> str:
    coords = {
        "skull": (380, 154),
        "cervical_spine": (380, 206),
        "thoracic_spine": (380, 258),
        "lumbar_spine": (380, 318),
        "ribs_thorax": (354, 248),
        "pelvis_sacrum": (380, 376),
        "humerus": (292, 258),
        "forearm": (248, 322),
        "femur": (344, 470),
        "tibia_fibula": (344, 550),
        "hand": (222, 366),
        "foot": (344, 598),
    }
    sites = profile.get("bone_sites") or []
    markers = []
    summary_rows = []
    for item in sites:
        site = item.get("site")
        if site not in coords:
            continue
        count = int(item.get("lesion_count") or 0)
        x, y = coords[site]
        markers.append(_marker_cluster(x, y, count))
        summary_rows.append(f"{item.get('label')}: {count}")
    if not markers:
        markers.append(_marker_cluster(332, 248, max(int(profile.get("bone_axial_count") or 0), 1)))
    axial = int(profile.get("bone_axial_count") or 0)
    append = int(profile.get("bone_appendicular_count") or 0)
    total = int(profile.get("metastatic_total_lesion_count") or axial + append or 1)
    summary = " · ".join(summary_rows[:4]) if summary_rows else summarize_metastatic_profile(profile)
    summary_lines = summary_rows[:3] or [summary]
    summary_svg = "".join(
        f'<text x="492" y="{308 + (index * 24)}" font-size="15" fill="#7c2d12">{escape(line)}</text>'
        for index, line in enumerate(summary_lines)
    )
    body = f"""
      <text x="108" y="158" font-size="20" fill="#123a69" font-weight="700">Carga ósea</text>
      <text x="108" y="188" font-size="15" fill="#475569">Axial: {axial}</text>
      <text x="108" y="214" font-size="15" fill="#475569">Apendicular: {append}</text>
      <text x="108" y="240" font-size="15" fill="#475569">Total: {total}</text>
      <text x="525" y="158" font-size="20" fill="#123a69" font-weight="700">Distribución</text>
      <text x="525" y="188" font-size="15" fill="#475569">El dibujo respeta el sitio y número</text>
      <text x="525" y="212" font-size="15" fill="#475569">capturados en ingreso o visita.</text>
      <circle cx="380" cy="150" r="28" fill="#dbeafe" stroke="#93c5fd" stroke-width="5"/>
      <rect x="362" y="178" width="36" height="92" rx="16" fill="#dbeafe" stroke="#93c5fd" stroke-width="5"/>
      <rect x="310" y="218" width="140" height="72" rx="32" fill="#dbeafe" stroke="#93c5fd" stroke-width="5"/>
      <rect x="350" y="268" width="60" height="118" rx="26" fill="#dbeafe" stroke="#93c5fd" stroke-width="5"/>
      <rect x="280" y="230" width="34" height="116" rx="18" transform="rotate(24 280 230)" fill="#dbeafe" stroke="#93c5fd" stroke-width="5"/>
      <rect x="454" y="230" width="34" height="116" rx="18" transform="rotate(-24 454 230)" fill="#dbeafe" stroke="#93c5fd" stroke-width="5"/>
      <rect x="334" y="382" width="34" height="128" rx="18" transform="rotate(4 334 382)" fill="#dbeafe" stroke="#93c5fd" stroke-width="5"/>
      <rect x="394" y="382" width="34" height="128" rx="18" transform="rotate(-4 394 382)" fill="#dbeafe" stroke="#93c5fd" stroke-width="5"/>
      <rect x="330" y="500" width="30" height="90" rx="16" fill="#dbeafe" stroke="#93c5fd" stroke-width="5"/>
      <rect x="400" y="500" width="30" height="90" rx="16" fill="#dbeafe" stroke="#93c5fd" stroke-width="5"/>
      {''.join(markers)}
      <rect x="470" y="248" width="226" height="112" rx="18" fill="#fff7ed" stroke="#fdba74"/>
      <text x="492" y="280" font-size="18" fill="#9a3412" font-weight="700">Sitios capturados</text>
      {summary_svg}
    """
    return _card_shell("M1b", "Metástasis ósea por sitio anatómico", body, summarize_metastatic_profile(profile))


def _render_m1c(profile: dict[str, Any]) -> str:
    coords = {
        "brain": (328, 160),
        "lung": (330, 278),
        "liver": (438, 390),
        "adrenal": (446, 284),
        "pleura": (474, 254),
        "peritoneum": (428, 468),
        "other": (564, 414),
    }
    organ_labels = {
        "brain": (250, 152, "Cerebro"),
        "lung": (250, 276, "Pulmón"),
        "liver": (526, 392, "Hígado"),
        "adrenal": (526, 286, "Suprarrenal"),
        "pleura": (526, 252, "Pleura"),
        "peritoneum": (526, 470, "Peritoneo"),
        "other": (526, 414, "Otro"),
    }
    sites = profile.get("visceral_sites") or []
    markers = []
    summary_rows = []
    for item in sites:
        site = item.get("site")
        if site not in coords:
            continue
        count = int(item.get("lesion_count") or 0)
        x, y = coords[site]
        markers.append(_marker_cluster(x, y, count, "#f43f5e"))
        summary_rows.append(f"{item.get('label')}: {count}")
    if not markers:
        markers.append(_marker_cluster(330, 278, max(int(profile.get("visceral_lesion_count") or 0), 1), "#f43f5e"))
    labels_svg = "".join(
        f'<text x="{x}" y="{y}" font-size="14" fill="#475569">{escape(label)}</text>'
        for _, (x, y, label) in organ_labels.items()
    )
    summary = " · ".join(summary_rows[:4]) if summary_rows else summarize_metastatic_profile(profile)
    body = f"""
      <ellipse cx="330" cy="160" rx="52" ry="38" fill="#dbeafe" stroke="#93c5fd" stroke-width="4"/>
      <ellipse cx="330" cy="280" rx="54" ry="72" fill="#dbeafe" stroke="#93c5fd" stroke-width="4"/>
      <ellipse cx="420" cy="392" rx="84" ry="52" fill="#fed7aa" stroke="#fb923c" stroke-width="4"/>
      <ellipse cx="426" cy="284" rx="22" ry="18" fill="#c7d2fe" stroke="#818cf8" stroke-width="4"/>
      <path d="M444 230c46 0 66 22 66 50" stroke="#93c5fd" stroke-width="16" fill="none" stroke-linecap="round"/>
      <path d="M352 438c42 18 72 30 104 40" stroke="#fbcfe8" stroke-width="18" fill="none" stroke-linecap="round"/>
      <rect x="540" y="380" width="84" height="66" rx="16" fill="#ede9fe" stroke="#a78bfa" stroke-width="4"/>
      {labels_svg}
      {''.join(markers)}
      <rect x="82" y="448" width="598" height="82" rx="18" fill="#fff1f2" stroke="#fda4af"/>
      <text x="104" y="480" font-size="18" fill="#9f1239" font-weight="700">Distribución visceral documentada</text>
      <text x="104" y="508" font-size="15" fill="#881337">{escape(summary[:92])}</text>
    """
    return _card_shell("M1c", "Metástasis viscerales por órgano", body, summarize_metastatic_profile(profile))


def _render_generic_m1(profile: dict[str, Any]) -> str:
    body = """
      <circle cx="274" cy="246" r="74" fill="#dbeafe" stroke="#60a5fa" stroke-width="8"/>
      <circle cx="404" cy="246" r="24" fill="#22c55e"/><circle cx="404" cy="246" r="40" fill="#22c55e" opacity="0.18"/>
      <circle cx="542" cy="246" r="24" fill="#f43f5e"/><circle cx="542" cy="246" r="40" fill="#f43f5e" opacity="0.18"/>
      <line x1="348" y1="246" x2="380" y2="246" stroke="#64748b" stroke-width="3"/>
      <line x1="430" y1="246" x2="514" y2="246" stroke="#64748b" stroke-width="3"/>
      <text x="214" y="356" font-size="18" fill="#123a69">Sitio distante documentado</text>
      <text x="214" y="382" font-size="15" fill="#475569">Falta subclasificación anatómica</text>
      <text x="446" y="360" font-size="18" fill="#123a69">Completar distribución</text>
      <text x="446" y="386" font-size="15" fill="#475569">para resolver M1a / M1b / M1c</text>
    """
    return _card_shell("M1", "Metástasis a distancia sin subtipo anatómico completo", body, summarize_metastatic_profile(profile))


def render_m_stage_visual(profile: dict[str, Any] | None) -> dict[str, Any]:
    profile = profile or {}
    m_stage = str(profile.get("m_substage_resolved") or "M0")
    if m_stage == "M1a":
        svg = _render_m1a(profile)
        mode = "static"
    elif m_stage == "M1b":
        svg = _render_m1b(profile)
        mode = "dynamic"
    elif m_stage == "M1c":
        svg = _render_m1c(profile)
        mode = "dynamic"
    elif m_stage == "M1":
        svg = _render_generic_m1(profile)
        mode = "static"
    else:
        return {"image_src": "", "visual_mode": "none", "summary": ""}
    return {
        "image_src": _data_uri(svg),
        "visual_mode": mode,
        "summary": summarize_metastatic_profile(profile),
    }
