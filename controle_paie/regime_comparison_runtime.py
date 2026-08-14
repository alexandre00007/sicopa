from __future__ import annotations

from .regime_comparison import RegimeComparisonService as BaseRegimeComparisonService


class RegimeComparisonService(BaseRegimeComparisonService):
    """Runtime wrapper: un seuil zéro signifie « tout écart réel », jamais « toutes les lignes »."""

    def run(self, institution_a: str, regime_a: str, institution_b: str, regime_b: str,
            quarter: str, year: int, threshold_amount: float = 0,
            threshold_percent: float = 0, progress=None) -> dict:
        amount = float(threshold_amount or 0)
        percent = float(threshold_percent or 0)
        epsilon = 1e-9
        return super().run(
            institution_a, regime_a, institution_b, regime_b, quarter, year,
            threshold_amount=amount if amount > 0 else epsilon,
            threshold_percent=percent if percent > 0 else epsilon,
            progress=progress,
        )
