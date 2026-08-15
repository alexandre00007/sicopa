from __future__ import annotations

from .data_architecture_app import PayrollAppWithDataArchitecture
from .data_architecture_finalize import assert_schema_health, finalize_data_architecture


class PayrollAppWithFinalDataArchitecture(PayrollAppWithDataArchitecture):
    """Cloture du Lot 2 : schema central V3 + controle de sante obligatoire."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        finalize_data_architecture(self.db)
        self.data_schema_health = assert_schema_health(self.db)
        try:
            self._refresh_data_governance()
        except Exception:
            pass

    def _refresh_data_governance(self):
        super()._refresh_data_governance()
        if not hasattr(self, "data_governance_status"):
            return
        health = getattr(self, "data_schema_health", None)
        if health is None:
            try:
                health = assert_schema_health(self.db)
                self.data_schema_health = health
            except Exception as exc:
                self.data_governance_status.set(f"Schéma de données en erreur : {exc}")
                return
        current = self.data_governance_status.get()
        self.data_governance_status.set(
            f"{current} — schéma V{health['version']} opérationnel"
        )
