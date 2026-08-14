from __future__ import annotations

from .analysis_versioning import AnalysisVersionRegistry
from .identity_policy import IDENTITY_ALGORITHM_VERSION
from .raw_fusion_scalable import ScalableRawFusionService


class VersionedScalableRawFusionService(ScalableRawFusionService):
    ANALYSIS_TYPE = "FUSION_MULTI_REGIMES"

    def __init__(self, db):
        super().__init__(db)
        self.version_registry = AnalysisVersionRegistry(db)

    def _apply_strict_identity_guard(self, fusion_id: str) -> None:
        """Empêche toute conclusion forte sur un matricule porté par plusieurs identités."""
        with self.db.connect() as con:
            con.execute("""UPDATE resultats_fusion_multi
                SET statut='MATRICULE_PARTAGE_IDENTITES_DIFFERENTES',
                    paiement_multi_regime=FALSE,
                    paiement_multiple_meme_regime=FALSE,
                    diagnostic=TRIM(CONCAT_WS(' ; ',NULLIF(diagnostic,''),
                        'Identité non certifiée : même matricule associé à plusieurs noms',
                        'Masses et occurrences conservées uniquement à titre technique ; aucune conclusion automatique de multi-régime ou double paiement'))
                WHERE fusion_id=? AND identite_incoherente""", [fusion_id])

    def _summary_payload(self, fusion_id: str) -> dict:
        return {"statuts": [list(row) for row in self.summary(fusion_id)]}

    def create_fusion(self, table_names, quarter, year, suffix="", progress=None):
        info = super().create_fusion(table_names, quarter, year, suffix, progress=progress)
        self._apply_strict_identity_guard(info["id"])
        self.version_registry.record(
            self.ANALYSIS_TYPE, info["id"], action="ANALYSE",
            parameters={"tables": list(table_names), "quarter": quarter, "year": int(year), "suffix": suffix},
            summary=self._summary_payload(info["id"]), algorithm_version=IDENTITY_ALGORITHM_VERSION,
        )
        return info

    def reanalyze(self, fusion_id: str, progress=None) -> dict:
        self.version_registry.record(
            self.ANALYSIS_TYPE, fusion_id, action="SNAPSHOT_AVANT_REANALYSE",
            summary=self._summary_payload(fusion_id), algorithm_version=IDENTITY_ALGORITHM_VERSION,
        )
        info = super().reanalyze(fusion_id, progress=progress)
        self._apply_strict_identity_guard(fusion_id)
        self.version_registry.record(
            self.ANALYSIS_TYPE, fusion_id, action="REANALYSE",
            parameters={"quarter": info["quarter"], "year": int(info["year"]), "table": info["table"]},
            summary=self._summary_payload(fusion_id), algorithm_version=IDENTITY_ALGORITHM_VERSION,
        )
        return info

    def version_history(self, fusion_id: str):
        return self.version_registry.history(self.ANALYSIS_TYPE, fusion_id)
