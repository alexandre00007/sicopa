#!/usr/bin/env bash
set -Eeuo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
trial_days="${1:-5}"

if [[ "${trial_days}" == "--help" || "${trial_days}" == "-h" ]]; then
    echo "Usage : ./build_windows_from_ubuntu.sh [nombre_de_jours]"
    echo "Exemple : ./build_windows_from_ubuntu.sh 5"
    exit 0
fi

if [[ ! "${trial_days}" =~ ^[1-9][0-9]*$ ]]; then
    echo "Erreur : la durée d'essai doit être un nombre entier strictement positif." >&2
    exit 2
fi

if ! command -v wine >/dev/null 2>&1; then
    echo "Erreur : Wine n'est pas installé ou n'est pas disponible dans PATH." >&2
    exit 3
fi

cd "${project_dir}"
export WINEDEBUG="${WINEDEBUG:--all}"

echo "Vérification de Python Windows dans Wine…"
wine cmd /c "py --version"

echo "Construction de SICORPA pour Windows — essai ${trial_days} jour(s)…"
wine cmd /c "build_windows.bat ${trial_days}"

exe_path="${project_dir}/dist/SICORPA.exe"
if [[ ! -f "${exe_path}" ]]; then
    echo "Erreur : PyInstaller s'est terminé sans produire ${exe_path}." >&2
    exit 4
fi

echo
echo "Build Windows terminé : ${exe_path}"
echo "Durée d'essai : ${trial_days} jour(s)"
