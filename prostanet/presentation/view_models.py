from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class NavItem:
    label: str
    href: str
    active: bool = False


@dataclass(frozen=True)
class PageAction:
    label: str
    href: str | None = None
    variant: str = "secondary"
    icon: str | None = None


@dataclass(frozen=True)
class AccentProfile:
    primary_bg_class: str = "bg-cyan-500"
    primary_hover_class: str = "hover:bg-cyan-400"
    primary_text_class: str = "text-cyan-300"
    primary_border_class: str = "border-cyan-500/30"
    primary_soft_class: str = "bg-cyan-500/10"


@dataclass(frozen=True)
class PageChrome:
    title: str
    subtitle: str
    page_key: str
    kicker: str = "ProstaMed 2026"
    nav_items: tuple[NavItem, ...] = field(default_factory=tuple)
    header_actions: tuple[PageAction, ...] = field(default_factory=tuple)
    primary_action: PageAction | None = None
    content_width_class: str = "max-w-7xl"
    density: str = "comfortable"
    show_page_header: bool = True
    footer_text: str = "ProstaMed 2026 · Salud · Diagnóstico · Precisión"
    requires_charts: bool = False
    accent_profile: AccentProfile = field(default_factory=AccentProfile)
    # Faubot LXXX #67E — v2 shell flag: cuando True, base_clinical.html omite
    # top_nav legacy + footer y deja que el contenido provea su propio
    # pm2-app-shell con sidebar v2 (resuelve el bug de UI mezclada legacy+v2).
    uses_v2_shell: bool = False


DEFAULT_NAV = (
    ("clinical_hub", "Centro clínico", "/clinical-hub"),
    ("patients", "Pacientes", "/patients"),
    ("dashboard", "Tablero clínico", "/dashboard"),
)


def build_page_chrome(
    page_key: str,
    title: str,
    subtitle: str,
    *,
    kicker: str = "ProstaMed 2026",
    show_page_header: bool = True,
    requires_charts: bool = False,
    content_width_class: str = "max-w-7xl",
    density: str = "comfortable",
    header_actions: list[PageAction] | tuple[PageAction, ...] | None = None,
    primary_action: PageAction | None = None,
    accent_profile: AccentProfile | None = None,
    uses_v2_shell: bool = False,
) -> PageChrome:
    nav_items = tuple(
        NavItem(label=label, href=href, active=(key == page_key))
        for key, label, href in DEFAULT_NAV
    )
    if primary_action is None:
        primary_action = PageAction(
            label="Nuevo caso clínico",
            href="/clinical-hub#pm2OfficialClassifier",
            variant="primary",
            icon="+",
        )
    return PageChrome(
        title=title,
        subtitle=subtitle,
        page_key=page_key,
        kicker=kicker,
        nav_items=nav_items,
        header_actions=tuple(header_actions or ()),
        primary_action=primary_action,
        content_width_class=content_width_class,
        density=density,
        show_page_header=show_page_header,
        requires_charts=requires_charts,
        accent_profile=accent_profile or AccentProfile(),
        uses_v2_shell=uses_v2_shell,
    )
