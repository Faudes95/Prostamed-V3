from __future__ import annotations

from functools import lru_cache
from pathlib import Path


STATIC_DIR = Path(__file__).resolve().parents[2] / "static"


def _ordered_matches(candidates: list[str], patterns: list[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if (STATIC_DIR / candidate).exists() and candidate not in seen:
            ordered.append(candidate)
            seen.add(candidate)
    for pattern in patterns:
        for match in sorted(STATIC_DIR.glob(pattern)):
            rel = match.relative_to(STATIC_DIR).as_posix()
            if rel not in seen:
                ordered.append(rel)
                seen.add(rel)
    return ordered


def _resolve_asset(
    *,
    candidates: list[str],
    patterns: list[str],
    fallback: str | None,
    alt: str,
) -> dict[str, object]:
    matches = _ordered_matches(candidates, patterns)
    if matches:
        return {
            "src": f"/static/{matches[0]}",
            "relative_path": matches[0],
            "available": True,
            "is_fallback": False,
            "alt": alt,
        }
    if fallback:
        return {
            "src": f"/static/{fallback}",
            "relative_path": fallback,
            "available": (STATIC_DIR / fallback).exists(),
            "is_fallback": True,
            "alt": alt,
        }
    return {
        "src": "",
        "relative_path": "",
        "available": False,
        "is_fallback": True,
        "alt": alt,
    }


@lru_cache(maxsize=1)
def build_ui_assets() -> dict[str, dict[str, object]]:
    prostamed_logo = _resolve_asset(
        candidates=[
            "img/prostamed_logo_official.png",
            "img/prostamed_logo_header_official.png",
            "img/prostamed_logo_header.png",
            "img/prostamed_logo_header.jpg",
            "img/prostamed_logo_header.jpeg",
            "img/prostamed_logo_header.webp",
            "img/prostamed_logo_header.svg",
            "img/prostamed_logo_real.png",
            "img/prostamed_logo_real.jpg",
            "img/prostamed_logo_real.jpeg",
            "img/prostamed_logo_real.webp",
            "img/prostamed_logo.png",
            "img/prostamed_logo.jpg",
            "img/prostamed_logo.jpeg",
            "img/prostamed_logo.webp",
        ],
        patterns=[
            "img/*prostamed*logo*.png",
            "img/*prostamed*logo*.jpg",
            "img/*prostamed*logo*.jpeg",
            "img/*prostamed*logo*.webp",
            "img/*prostamed*.png",
            "img/*prostamed*.jpg",
            "img/*prostamed*.jpeg",
            "img/*prostamed*.webp",
            "img/*prostamed*logo*.svg",
            "img/*prostamed*.svg",
        ],
        fallback="img/prostamed_logo.svg",
        alt="PROSTAMED",
    )
    tnm_overview = _resolve_asset(
        candidates=[
            "img/tnm/tnm_cancer_prostata_real.png",
            "img/tnm/tnm_cancer_prostata_real.jpg",
            "img/tnm/tnm_cancer_prostata_real.jpeg",
            "img/tnm/tnm_cancer_prostata.png",
            "img/tnm/tnm-cancer-prostata.png",
            "img/tnm/tnm_prostata_real.png",
            "img/tnm/tnm_overview.png",
        ],
        patterns=[
            "img/tnm/*tnm*prostata*.png",
            "img/tnm/*tnm*prostata*.jpg",
            "img/tnm/*tnm*prostata*.jpeg",
            "img/tnm/*tnm*prostata*.webp",
            "img/tnm/*overview*.png",
            "img/tnm/*overview*.jpg",
            "img/tnm/*overview*.jpeg",
            "img/tnm/*overview*.webp",
        ],
        fallback=None,
        alt="TNM cáncer de próstata",
    )
    return {
        "prostamed_logo": prostamed_logo,
        "prostamed_favicon": prostamed_logo,
        "tnm_overview": tnm_overview,
    }
