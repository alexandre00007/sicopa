from __future__ import annotations

from .analysis_versioning import AnalysisVersionRegistry
from .identity_policy import IDENTITY_ALGORITHM_VERSION
from .regime_comparison_strict import StrictRegimeComparisonService


class VersionedStrictRegimeComparisonService(StrictRegimeComparisonService):
    ANALYSIS_TYPE = "COMPARAISON_REGIMES"

    def __init__(self, db):
        super().__init__(db)
        self.version_registry = AnalysisVersionRegistry(db)

    def run(self, institution_a: str, regime_a: str, institution_b: str, regime_b: str,
            quarter: str, year: int, threshold_amount: float = 0,
            threshold_percent: float = 0, progress=None, _parent_id: str | None = None,
            _action: str = "ANALYSE") -> dict:
        info = super().run(
            institution_a, regime_a, institution_b, regime_b, quarter, year,
            threshold_amount=threshold_amount, threshold_percent=threshold_percent, progress=progress,
        )
        self.version_registry.record(
            self.ANALYSIS_TYPE,
            info["id"],
            action=_action,
            parent_id=_parent_id,
            parameters={
                "institution_a": institution_a, "regime_a": regime_a,
                "institution_b": institution_b, "regime_b": regime_b,
                "quarter": quarter, "year": int(year),
                "threshold_amount": float(threshold_amount or 0),
                "threshold_percent": float(threshold_percent or 0),
            },
            summary={
                "common": int(info["common"] or 0), "only_a": int(info["only_a"] or 0),
                "only_b": int(info["only_b"] or 0), "double_paiement_potentiel": int(info["double"] or 0),
                "financial": int(info["financial"] or 0), "administrative": int(info["administrative"] or 0),
                "mass_a": str(info["mass_a"] or 0), "mass_b": str(info["mass_b"] or 0),
            },
            algorithm_version=IDENTITY_ALGORITHM_VERSION,
        )
        return info

    def version_history(self, comparison_id: str):
        return self.version_registry.history(self.ANALYSIS_TYPE, comparison_id)
