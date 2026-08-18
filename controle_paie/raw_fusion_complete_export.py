from __future__ import annotations

from pathlib import Path

from .raw_fusion_occurrence_export_low_memory import LowMemoryOccurrenceExportRawFusionService
from .raw_fusion_risk_export_low_memory import LowMemoryRawFusionRiskExporter


class CompleteExportRawFusionService(LowMemoryOccurrenceExportRawFusionService):
    """Package final de fusion : annexes 11 et 12 optimisées pour les gros volumes."""

    def __init__(self, db):
        super().__init__(db)
        self.risk_exporter = LowMemoryRawFusionRiskExporter(db)

    def export_all(self, fusion_id, parent_folder, progress=None):
        def previous_progress(value, text=""):
            if progress:
                progress(min(94, int(max(0, value) * 0.94)), text)

        folder = Path(super().export_all(fusion_id, parent_folder, progress=previous_progress))
        self.risk_exporter.export(fusion_id, folder, progress=progress)
        progress and progress(100, "Export complet termine : annexes 11 et 12 incluses en mode faible memoire")
        return str(folder)
