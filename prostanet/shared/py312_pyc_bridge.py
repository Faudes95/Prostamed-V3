from __future__ import annotations

import base64
import os
import pickle
import subprocess
import sys
from pathlib import Path
from typing import Any


_BRIDGE_WORKER = Path(__file__).with_name("_py312_pyc_worker.py")
_DEFAULT_PY312 = "/opt/homebrew/bin/python3.12"


def call_pyc_function(pyc_path: str | Path, function_name: str, *args: Any, **kwargs: Any) -> Any:
    """Call a recovered Python 3.12 bytecode function from the Python 3.14 app.

    Some local clinical modules were present only as APFS dataless source files,
    while their Python 3.12 bytecode remained available. This bridge preserves
    the compiled clinical behavior instead of replacing it with a lossy stub.
    """

    py312 = os.environ.get("PROSTANET_PY312") or _DEFAULT_PY312
    payload = base64.b64encode(pickle.dumps({"args": args, "kwargs": kwargs})).decode("ascii")
    proc = subprocess.run(
        [py312, str(_BRIDGE_WORKER), str(Path(pyc_path)), function_name],
        input=payload,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(Path(__file__).resolve().parents[2]),
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"Python 3.12 pyc bridge failed for {function_name}: {proc.stderr.strip()}"
        )
    try:
        return pickle.loads(base64.b64decode(proc.stdout.encode("ascii")))
    except Exception as exc:  # pragma: no cover - diagnostic safeguard
        raise RuntimeError(
            f"Python 3.12 pyc bridge returned unreadable payload for {function_name}: {exc}"
        ) from exc


__all__ = ["call_pyc_function"]
