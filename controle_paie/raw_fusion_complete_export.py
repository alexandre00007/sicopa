from __future__ import annotations

from pathlib import Path

from .raw_fusion_export_partitioned import (
    PartitionedOccurrenceExportRawFusionService,
    PartitionedRawFusionRiskExporter,
)


class CompleteExportRawFusionService(PartitionedOccurrenceExportRawFusionService):
    """Package final de fusion : annexes 11/12 partitionnées par exécution pour mémoire bornée."""

    def __init__(self, db):
        super().__init__(db)
        self.risk_exporter = PartitionedRawFusionRiskExporter(db)

    def export_all(self, fusion_id, parent_folder, progress=None):
        def previous_progress(value, text=""):
            if progress:
                progress(min(94, int(max(0, value) * 0.94)), text)

        folder = Path(super().export_all(fusion_id, parent_folder, progress=previous_progress))
        self.risk_exporter.export(fusion_id, folder, progress=progress)
        progress and progress(100, "Export complet termine : annexes 11 et 12 partitionnees par execution")
        return str(folder)
