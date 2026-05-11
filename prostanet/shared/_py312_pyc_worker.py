from __future__ import annotations

import base64
import marshal
import pickle
import sys
from pathlib import Path


def _load_namespace(pyc_path: Path) -> dict:
    with pyc_path.open("rb") as handle:
        handle.read(16)
        code = marshal.load(handle)
    namespace = {
        "__name__": "_prostanet_recovered_pyc_module",
        "__file__": str(pyc_path),
        "__package__": "",
    }
    exec(code, namespace)
    return namespace


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: _py312_pyc_worker.py <pyc-path> <function-name>", file=sys.stderr)
        return 2
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    pyc_path = Path(sys.argv[1]).resolve()
    function_name = sys.argv[2]
    payload = pickle.loads(base64.b64decode(sys.stdin.read().encode("ascii")))
    namespace = _load_namespace(pyc_path)
    function = namespace.get(function_name)
    if not callable(function):
        print(f"function not found in pyc: {function_name}", file=sys.stderr)
        return 3
    result = function(*payload.get("args", ()), **payload.get("kwargs", {}))
    sys.stdout.write(base64.b64encode(pickle.dumps(result)).decode("ascii"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
