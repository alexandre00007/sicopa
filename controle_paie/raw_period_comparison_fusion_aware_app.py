from __future__ import annotations

from .raw_period_comparison_fusion_aware import FusionAwareRawPeriodComparisonService
from .raw_period_comparison_resilient_app import PayrollAppWithResilientRawPeriodComparison


class PayrollAppWithFusionAwareRawPeriodComparison(PayrollAppWithResilientRawPeriodComparison):
    """Active la comparaison par période pour RAW directs et RAW issus de fusions."""

    def _build_matching(self):
        super()._build_matching()
        self.raw_period_comparison_service = FusionAwareRawPeriodComparisonService(self.db)
        if hasattr(self, "rpc_a"):
            self._rpc_refresh_sources()
