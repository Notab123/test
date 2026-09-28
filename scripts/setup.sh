#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
umask 077
python3 - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit('Нужен Python 3.10 или новее')
PY
command -v git >/dev/null || { echo 'Нужен Git' >&2; exit 1; }
python3 -m venv .venv
.venv/bin/python tools/workbench.py init
echo 'Готово. Проверка: .venv/bin/python -m unittest discover -s tests -v'
