from __future__ import annotations

from collections import Counter

from .analysis_versioning import AnalysisVersionRegistry
from .identity_policy import IDENTITY_ALGORITHM_VERSION
from .matching import MatchingService


class VersionedMatchingService(MatchingService):
    ANALYSIS_TYPE = "RAPPROCHEMENT_PAIE_DECLARATIF"

    def __init__(self, database):
        super().__init__(database)
        self.version_registry = AnalysisVersionRegistry(database)

    def run(self, institution_id: str, regime: str, quarter: str, year: int,
            progress=None, impact_formula_id: str = "") -> str:
        execution_id = super().run(
            institution_id, regime, quarter, year,
            progress=progress, impact_formula_id=impact_formula_id,
        )
        with self.db.connect() as con:
            rows = con.execute("""SELECT statut_rapprochement,COUNT(*)
                FROM resultats_rapprochement WHERE execution_id=?
                GROUP BY statut_rapprochement""", [execution_id]).fetchall()
        self.version_registry.record(
            self.ANALYSIS_TYPE,
            execution_id,
            action="ANALYSE",
            parameters={
                "institution_id": institution_id, "regime": regime,
                "quarter": quarter, "year": int(year), "impact_formula_id": impact_formula_id,
            },
            summary={"statuts": {str(status): int(count or 0) for status, count in rows}},
            algorithm_version=IDENTITY_ALGORITHM_VERSION,
        )
        return execution_id
