from __future__ import annotations

import argparse
import os
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SECRET_FILE = ROOT / ".sicorpa_trial_secret"
OUTPUT = ROOT / "controle_paie" / "_trial_build.py"


def build_config(days: int) -> Path:
    if not 1 <= days <= 3650:
        raise ValueError("Le nombre de jours doit être compris entre 1 et 3650.")
    supplied = os.environ.get("SICORPA_TRIAL_SECRET", "").strip()
    if supplied:
        secret = supplied
    elif SECRET_FILE.exists():
        secret = SECRET_FILE.read_text(encoding="utf-8").strip()
    else:
        secret = secrets.token_hex(32)
        SECRET_FILE.write_text(secret, encoding="utf-8")
    if len(secret) < 32:
        raise ValueError("Le secret de construction doit contenir au moins 32 caractères.")
    content = (
        "# Généré automatiquement pendant la construction — ne pas versionner.\n"
        f"TRIAL_DAYS = {days}\n"
        f"BUILD_ID = {str(uuid.uuid4())!r}\n"
        f"BUILD_CREATED_UTC = {datetime.now(timezone.utc).replace(microsecond=0).isoformat()!r}\n"
        f"STATE_SECRET = {secret!r}\n"
    )
    OUTPUT.write_text(content, encoding="utf-8")
    return OUTPUT


def main() -> None:
    parser=argparse.ArgumentParser(description="Génère la politique d’essai intégrée à SICORPA.")
    parser.add_argument("--days",required=True,type=int)
    args=parser.parse_args()
    print(build_config(args.days))


if __name__ == "__main__":
    main()
