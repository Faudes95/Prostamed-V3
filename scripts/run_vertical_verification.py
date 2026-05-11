from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from prostanet.domains.clinical_validation import run_vertical_verification


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run CRPC-first and post-RP salvage-first verification audit.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--visual-mode", default="textual", choices=["textual", "playwright_real"])
    parser.add_argument("--live-limit-per-vertical", type=int, default=2)
    parser.add_argument("--seed-live-samples-when-missing", action="store_true")
    parser.add_argument(
        "--output",
        default=str(Path("output") / "vertical_verification_latest.json"),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_vertical_verification(
        base_url=args.base_url,
        visual_mode=args.visual_mode,
        live_limit_per_vertical=args.live_limit_per_vertical,
        seed_live_samples_when_missing=args.seed_live_samples_when_missing,
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(str(output_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
