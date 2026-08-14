from .raw_fusion_app import PayrollAppWithRawFusion
from .raw_fusion_period import PeriodAwareRawFusionService


class PayrollAppWithPeriodAwareRawFusion(PayrollAppWithRawFusion):
    """Active le service de fusion RAW filtré par exécution/période."""

    def _build_matching(self):
        super()._build_matching()
        self.raw_fusion_service = PeriodAwareRawFusionService(self.db)
