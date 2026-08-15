from __future__ import annotations

from .raw_fusion_enhanced_app import PayrollAppWithEnhancedRawFusion
from .raw_fusion_occurrence_export import OccurrenceExportRawFusionService


class PayrollAppWithScalableRawFusion(PayrollAppWithEnhancedRawFusion):
    """Conserve l'UI de fusion existante et active exports exhaustifs + versionnement."""

    def _build_matching(self):
        super()._build_matching()
        self.raw_fusion_service = OccurrenceExportRawFusionService(self.db)
        if hasattr(self, "raw_fusion_sources"):
            self._refresh_raw_fusion_sources()
