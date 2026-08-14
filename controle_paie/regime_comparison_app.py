from __future__ import annotations

from .regime_comparison_runtime import RegimeComparisonService
from .regime_comparison_ui import PayrollAppWithRegimeComparison


class PayrollAppWithFinalRegimeComparison(PayrollAppWithRegimeComparison):
    """Assemble l'UI de comparaison avec la version runtime sécurisée du moteur."""

    def _build_matching(self):
        super()._build_matching()
        self.regime_comparison = RegimeComparisonService(self.db)
