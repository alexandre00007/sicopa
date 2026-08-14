from __future__ import annotations

from .raw_fusion_enhanced_app import PayrollAppWithEnhancedRawFusion
from .raw_fusion_scalable import ScalableRawFusionService


class PayrollAppWithScalableRawFusion(PayrollAppWithEnhancedRawFusion):
    """Conserve l'UI de fusion existante et active les exports exhaustifs en streaming."""

    def _build_matching(self):
        super()._build_matching()
        self.raw_fusion_service = ScalableRawFusionService(self.db)
        if hasattr(self, "raw_fusion_sources"):
            self._refresh_raw_fusion_sources()
