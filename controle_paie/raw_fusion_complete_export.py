from __future__ import annotations

from pathlib import Path

from .raw_fusion_occurrence_export import OccurrenceExportRawFusionService
from .raw_fusion_risk_export import RawFusionRiskExporter


class CompleteExportRawFusionService(OccurrenceExportRawFusionService):
    """Package final de fusion : annexes exhaustives 11 et ciblées à risque 12."""

    def __init__(self, db):
        super().__init__(db)
        self.risk_exporter = RawFusionRiskExporter(db)

    def export_all(self, fusion_id, parent_folder, progress=None):
        def previous_progress(value, text=""):
            if progress:
                progress(min(94, int(max(0, value) * 0.94)), text)

        folder = Path(super().export_all(fusion_id, parent_folder, progress=previous_progress))
        self.risk_exporter.export(fusion_id, folder, progress=progress)
        progress and progress(100, "Export complet termine : annexes occurrences 11 et 12 incluses")
        return str(folder)
