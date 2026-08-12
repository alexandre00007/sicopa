#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

trial_days="${1:-${SICORPA_TRIAL_DAYS:-}}"
if [[ -z "$trial_days" ]]; then
    read -r -p "Durée de la version d'essai en jours [30] : " trial_days
    trial_days="${trial_days:-30}"
fi

python -m pip install -r requirements-build.txt
python tools/generate_trial_config.py --days "$trial_days"

cleanup_trial_config() {
    python -c "from pathlib import Path; Path('controle_paie/_trial_build.py').unlink(missing_ok=True)"
}
trap cleanup_trial_config EXIT

python -m PyInstaller --noconfirm sicorpa.spec
printf '%s\n' "Exécutable d'essai créé : dist/SICORPA ($trial_days jours)"
