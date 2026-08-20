from __future__ import annotations

from pathlib import Path

from .raw_fusion_annex12_drilldown import DrillDownAnnex12Exporter
from .raw_fusion_export_partitioned import PartitionedOccurrenceExportRawFusionService


class CompleteExportRawFusionService(PartitionedOccurrenceExportRawFusionService):
    """Package final : annexe 11 exhaustive et annexe 12 interactive a 7 feuilles."""

    def __init__(self, db):
        super().__init__(db)
        self.risk_exporter = DrillDownAnnex12Exporter(db)

    def export_all(self, fusion_id, parent_folder, progress=None):
        def previous_progress(value, text=""):
            if progress:
                progress(min(94, int(max(0, value) * 0.94)), text)

        folder = Path(super().export_all(fusion_id, parent_folder, progress=previous_progress))
        self.risk_exporter.export(fusion_id, folder, progress=progress)
        progress and progress(100, "Export complet termine : annexe 11 exhaustive et annexe 12 drill-down multi-regimes")
        return str(folder)
