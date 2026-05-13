#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

python3 -m venv .venv-security
.venv-security/bin/python -m pip install --upgrade pip
.venv-security/bin/python -m pip install -r requirements-dev.txt
.venv-security/bin/pip-audit --version
