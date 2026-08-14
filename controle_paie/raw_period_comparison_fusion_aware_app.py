from __future__ import annotations

from .raw_period_comparison_resilient_app import PayrollAppWithResilientRawPeriodComparison
from .raw_period_comparison_versioned import VersionedRawPeriodComparisonService


class PayrollAppWithFusionAwareRawPeriodComparison(PayrollAppWithResilientRawPeriodComparison):
    """Active la comparaison par période pour RAW directs/fusionnés avec exports exhaustifs et versionnement."""

    def _build_matching(self):
        super()._build_matching()
        self.raw_period_comparison_service = VersionedRawPeriodComparisonService(self.db)
        if hasattr(self, "rpc_a"):
            self._rpc_refresh_sources()
