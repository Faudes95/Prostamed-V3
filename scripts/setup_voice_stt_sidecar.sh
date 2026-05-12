#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${VOICE_STT_BOOTSTRAP_PYTHON:-python3.11}"
VENV_DIR="${ROOT_DIR}/.venv-voice311"

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  echo "python3.11 no está instalado. Instala Python 3.11 o exporta VOICE_STT_BOOTSTRAP_PYTHON=/ruta/python3.11" >&2
  exit 2
fi

"${PYTHON_BIN}" -m venv "${VENV_DIR}"
"${VENV_DIR}/bin/python" -m pip install --upgrade pip
"${VENV_DIR}/bin/python" -m pip install -r "${ROOT_DIR}/requirements-voice.txt"
"${VENV_DIR}/bin/python" -c "import faster_whisper; print('Voice STT sidecar listo')"
