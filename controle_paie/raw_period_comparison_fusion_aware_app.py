from __future__ import annotations

from .raw_period_comparison_resilient_app import PayrollAppWithResilientRawPeriodComparison
from .raw_period_comparison_scalable import ScalableRawPeriodComparisonService


class PayrollAppWithFusionAwareRawPeriodComparison(PayrollAppWithResilientRawPeriodComparison):
    """Active la comparaison par période pour RAW directs/fusionnés avec exports exhaustifs."""

    def _build_matching(self):
        super()._build_matching()
        self.raw_period_comparison_service = ScalableRawPeriodComparisonService(self.db)
        if hasattr(self, "rpc_a"):
            self._rpc_refresh_sources()
