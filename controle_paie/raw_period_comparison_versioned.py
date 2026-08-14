from __future__ import annotations

from .analysis_versioning import AnalysisVersionRegistry
from .identity_policy import IDENTITY_ALGORITHM_VERSION
from .raw_period_comparison_scalable import ScalableRawPeriodComparisonService


class VersionedRawPeriodComparisonService(ScalableRawPeriodComparisonService):
    """Comparaison RAW stricte avec historique immuable des réanalyses."""

    ANALYSIS_TYPE = "COMPARAISON_RAW_PERIODE"

    def __init__(self, db):
        super().__init__(db)
        self.version_registry = AnalysisVersionRegistry(db)

    def analyze(self, table_a: str, table_b: str, quarter: str, year: int, progress=None,
                _parent_id: str | None = None, _action: str = "ANALYSE"):
        info = super().analyze(table_a, table_b, quarter, year, progress=progress)
        base, metrics = self.summary(info["id"])
        self.version_registry.record(
            self.ANALYSIS_TYPE,
            info["id"],
            action=_action,
            parent_id=_parent_id,
            parameters={"table_a": table_a, "table_b": table_b, "quarter": quarter, "year": int(year)},
            summary={
                "statuts": [list(row) for row in base],
                "communs_matricule": int(metrics[0] or 0),
                "communs_nom": int(metrics[1] or 0),
                "communs_exacts": int(metrics[2] or 0),
                "matricule_nom_different": int(metrics[3] or 0),
                "nom_matricule_different": int(metrics[4] or 0),
            },
            algorithm_version=IDENTITY_ALGORITHM_VERSION,
            version_number=1,
        )
        return info

    def reanalyze(self, comparison_id: str, progress=None):
        """Crée une nouvelle comparaison liée à l'ancienne au lieu de la supprimer."""
        previous = self.get_comparison(comparison_id)
        progress and progress(5, "Création d'une nouvelle version de la comparaison")
        return self.analyze(
            previous["table_a"], previous["table_b"], previous["quarter"], previous["year"],
            progress=progress, _parent_id=comparison_id, _action="REANALYSE",
        )

    def version_history(self, comparison_id: str):
        return self.version_registry.history(self.ANALYSIS_TYPE, comparison_id)
