#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python -m pip install -r requirements-build.txt
python -m PyInstaller --noconfirm sicorpa.spec
printf '%s\n' "Exécutable créé : dist/SICORPA"
