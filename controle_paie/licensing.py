from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

try:
    from ._trial_build import BUILD_CREATED_UTC, BUILD_ID, STATE_SECRET, TRIAL_DAYS
except ImportError:
    BUILD_CREATED_UTC = ""
    BUILD_ID = "SOURCE"
    STATE_SECRET = "source-development-only"
    TRIAL_DAYS = 0


ACTIVE = "ACTIVE"
EXPIRING = "EXPIRING"
EXPIRED = "EXPIRED"
CLOCK_ROLLBACK = "CLOCK_ROLLBACK"
INVALID = "INVALID"
DEVELOPMENT = "DEVELOPMENT"


@dataclass(frozen=True)
class TrialPolicy:
    days: int = TRIAL_DAYS
    build_id: str = BUILD_ID
    build_created_utc: str = BUILD_CREATED_UTC
    state_secret: str = STATE_SECRET
    rollback_tolerance_hours: int = 6


@dataclass(frozen=True)
class TrialStatus:
    code: str
    days_total: int
    days_remaining: int
    first_run: Optional[datetime]
    last_run: Optional[datetime]
    expires_at: Optional[datetime]
    build_id: str
    message: str

    @property
    def allowed(self) -> bool:
        return self.code in {ACTIVE, EXPIRING, DEVELOPMENT}

    @property
    def enabled(self) -> bool:
        return self.code != DEVELOPMENT

    @property
    def short_label(self) -> str:
        if self.code == DEVELOPMENT:
            return "Mode développement"
        if self.code == ACTIVE:
            return f"Essai — {self.days_remaining} jours restants"
        if self.code == EXPIRING:
            return f"Essai — expire dans {self.days_remaining} jours"
        if self.code == EXPIRED:
            return "Version d’essai expirée"
        if self.code == CLOCK_ROLLBACK:
            return "Horloge système incohérente"
        return "État d’essai invalide"


class TrialManager:
    STATE_FILENAME = ".sicorpa_trial.json"

    def __init__(self, data_dir: Path, policy: TrialPolicy | None = None):
        self.data_dir = Path(data_dir)
        self.policy = policy or TrialPolicy()
        self.state_path = self.data_dir / self.STATE_FILENAME

    @staticmethod
    def _utc(value: datetime | None = None) -> datetime:
        current = value or datetime.now(timezone.utc)
        return current.astimezone(timezone.utc).replace(microsecond=0)

    def _signature(self, payload: dict) -> str:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return hmac.new(self.policy.state_secret.encode("utf-8"), canonical, hashlib.sha256).hexdigest()

    def _signed(self, payload: dict) -> dict:
        document = dict(payload)
        document["signature"] = self._signature(payload)
        return document

    def _write(self, payload: dict) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        document = self._signed(payload)
        descriptor, temporary_name = tempfile.mkstemp(prefix=".sicorpa_trial_", suffix=".tmp", dir=self.data_dir)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(document, stream, ensure_ascii=False, indent=2)
                stream.flush();os.fsync(stream.fileno())
            Path(temporary_name).replace(self.state_path)
        finally:
            temporary = Path(temporary_name)
            if temporary.exists():
                temporary.unlink()

    def _read(self) -> dict:
        document = json.loads(self.state_path.read_text(encoding="utf-8"))
        signature = document.pop("signature", "")
        if not signature or not hmac.compare_digest(signature, self._signature(document)):
            raise ValueError("Signature de l’état d’essai invalide.")
        return document

    def _new_state(self, now: datetime) -> dict:
        return {
            "schema": 1,
            "installation_id": str(uuid.uuid4()),
            "first_run_utc": now.isoformat(),
            "last_run_utc": now.isoformat(),
            "run_count": 1,
        }

    def check(self, now: datetime | None = None) -> TrialStatus:
        current = self._utc(now)
        if self.policy.days <= 0:
            return TrialStatus(DEVELOPMENT,0,0,None,None,None,self.policy.build_id,"Essai désactivé dans l’exécution depuis les sources.")
        try:
            build_created=datetime.fromisoformat(self.policy.build_created_utc).astimezone(timezone.utc) if self.policy.build_created_utc else None
            tolerance=timedelta(hours=self.policy.rollback_tolerance_hours)
            if build_created and current < build_created-tolerance:
                return TrialStatus(CLOCK_ROLLBACK,self.policy.days,0,None,None,None,self.policy.build_id,"La date de l’ordinateur est antérieure à la date de création de cette version. Corrigez l’horloge système.")
            if self.state_path.exists():
                state = self._read()
            else:
                state = self._new_state(current);self._write(state)
            first_run=datetime.fromisoformat(state["first_run_utc"]).astimezone(timezone.utc)
            last_run=datetime.fromisoformat(state["last_run_utc"]).astimezone(timezone.utc)
        except Exception as exc:
            return TrialStatus(INVALID,self.policy.days,0,None,None,None,self.policy.build_id,f"L’état local de la version d’essai est illisible ou a été modifié : {exc}")
        expires_at=first_run+timedelta(days=self.policy.days)
        if current < last_run-tolerance:
            return TrialStatus(CLOCK_ROLLBACK,self.policy.days,0,first_run,last_run,expires_at,self.policy.build_id,"La date de l’ordinateur est antérieure au dernier lancement enregistré. Corrigez l’horloge système.")
        remaining_seconds=max(0,(expires_at-current).total_seconds())
        days_remaining=max(0,int((remaining_seconds+86399)//86400))
        if current >= expires_at:
            code=EXPIRED;message="La période d’essai est terminée. Les données existantes restent consultables, mais les nouveaux traitements sont bloqués."
        else:
            code=EXPIRING if days_remaining<=7 else ACTIVE
            message=f"Version d’essai valable jusqu’au {expires_at.astimezone().strftime('%d/%m/%Y à %H:%M')}."
        if current >= last_run:
            state["last_run_utc"]=current.isoformat();state["run_count"]=int(state.get("run_count",0))+1
            try:self._write(state)
            except OSError:pass
        return TrialStatus(code,self.policy.days,days_remaining,first_run,last_run,expires_at,self.policy.build_id,message)
