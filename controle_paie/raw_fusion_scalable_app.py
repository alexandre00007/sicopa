from __future__ import annotations

from .raw_fusion_enhanced_app import PayrollAppWithEnhancedRawFusion
from .raw_fusion_complete_export import CompleteExportRawFusionService


class PayrollAppWithScalableRawFusion(PayrollAppWithEnhancedRawFusion):
    """Conserve l'UI de fusion existante et active les exports complets des annexes 11 et 12."""

    def _build_matching(self):
        super()._build_matching()
        self.raw_fusion_service = CompleteExportRawFusionService(self.db)
        if hasattr(self, "raw_fusion_sources"):
            self._refresh_raw_fusion_sources()
