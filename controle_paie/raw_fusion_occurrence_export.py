from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from .export_streaming import append_query_sheets, atomic_save_workbook
from .raw_fusion_scalable_versioned import VersionedScalableRawFusionService


class OccurrenceExportRawFusionService(VersionedScalableRawFusionService):
    """Ajoute un audit exhaustif, ligne par ligne, des occurrences de la fusion RAW."""

    OCCURRENCE_HEADERS = [
        "Fusion ID", "Table RAW source", "Execution ID", "Ligne source", "Regime", "Institution",
        "Trimestre", "Annee", "Matricule source", "Matricule normalise", "Nom", "Prenom",
        "Nom normalise", "Section", "Categorie", "Grade", "Unite d'affectation", "Province",
        "Remuneration brute", "Montant net", "Statut analyse", "Nb regimes agent",
        "Nb lignes physiques agent", "Nb repetitions agent", "Regimes agent", "Institutions agent",
        "Doublon matricule", "Doublon nom", "Multi-regimes", "Multiple meme regime",
        "Identite incoherente", "Type occurrence", "Diagnostic",
    ]

    SUMMARY_HEADERS = [
        "Statut", "Matricule", "Nom normalise", "Nom", "Prenom", "Regimes", "Institutions",
        "Nb regimes", "Nb institutions", "Nb lignes physiques", "Nb repetitions",
        "Masse brute", "Masse nette", "Doublon matricule", "Doublon nom",
        "Multi-regimes", "Multiple meme regime", "Identite incoherente", "Diagnostic",
    ]

    def _occurrence_query(self) -> str:
        return """
            WITH src AS (
                SELECT execution_id, MIN(table_source) AS table_source
                FROM sources_fusion_raw
                WHERE fusion_id=?
                GROUP BY execution_id
            ), base AS (
                SELECT p.*,
                    CASE
                        WHEN COALESCE(p.matricule_normalise,'') NOT IN ('','NU')
                            THEN 'M:'||p.matricule_normalise
                        WHEN COALESCE(p.nom_normalise,'')<>''
                            THEN 'N:'||p.nom_normalise
                        ELSE 'L:'||p.ligne_paie_id
                    END AS person_key
                FROM paie_standardisee p
                WHERE p.execution_id IN (
                    SELECT DISTINCT execution_id FROM sources_fusion_raw
                    WHERE fusion_id=? AND execution_id IS NOT NULL
                )
            )
            SELECT
                r.fusion_id,
                COALESCE(src.table_source,b.table_source,''),
                b.execution_id,
                b.ligne_source,
                b.regime,
                b.institution_id,
                b.trimestre,
                b.annee,
                b.matricule_source,
                b.matricule_normalise,
                b.nom,
                b.prenom,
                b.nom_normalise,
                b.section,
                b.categorie,
                b.grade,
                b.unite_affectation,
                b.province,
                b.remuneration_brute_calculee,
                b.montant_net,
                r.statut,
                r.nb_regimes,
                r.occurrences,
                GREATEST(r.occurrences-1,0),
                r.regimes,
                r.institutions,
                COALESCE(d.doublon_matricule,FALSE),
                COALESCE(d.doublon_nom,FALSE),
                r.paiement_multi_regime,
                r.paiement_multiple_meme_regime,
                r.identite_incoherente,
                CASE
                    WHEN r.identite_incoherente THEN 'IDENTITE_INCOHERENTE'
                    WHEN COALESCE(d.doublon_matricule,FALSE) AND COALESCE(d.doublon_nom,FALSE)
                        THEN 'MATRICULE_ET_NOM_REPETES'
                    WHEN r.nb_regimes>1 THEN 'MEME_IDENTITE_MULTI_REGIME'
                    WHEN r.paiement_multiple_meme_regime THEN 'PAIEMENT_MULTIPLE_MEME_REGIME'
                    WHEN COALESCE(d.doublon_matricule,FALSE) THEN 'MATRICULE_REPETE'
                    WHEN COALESCE(d.doublon_nom,FALSE) THEN 'NOM_REPETE'
                    WHEN r.occurrences>1 THEN 'MEME_IDENTITE_REPETEE'
                    ELSE 'OCCURRENCE_UNIQUE'
                END,
                r.diagnostic
            FROM base b
            JOIN resultats_fusion_multi r
              ON r.fusion_id=? AND r.person_key=b.person_key
            LEFT JOIN src ON src.execution_id=b.execution_id
            LEFT JOIN resultats_fusion_doublons d
              ON d.fusion_id=r.fusion_id AND d.person_key=r.person_key
            ORDER BY r.nb_regimes DESC,r.occurrences DESC,
                     r.matricule_normalise,r.nom_normalise,b.regime,b.execution_id,b.ligne_source
        """

    def _summary_query(self) -> str:
        return """
            SELECT r.statut,r.matricule_normalise,r.nom_normalise,r.nom,r.prenom,
                   r.regimes,r.institutions,r.nb_regimes,r.nb_institutions,r.occurrences,
                   GREATEST(r.occurrences-1,0),r.masse_brute,r.masse_net,
                   COALESCE(d.doublon_matricule,FALSE),COALESCE(d.doublon_nom,FALSE),
                   r.paiement_multi_regime,r.paiement_multiple_meme_regime,
                   r.identite_incoherente,r.diagnostic
            FROM resultats_fusion_multi r
            LEFT JOIN resultats_fusion_doublons d
              ON d.fusion_id=r.fusion_id AND d.person_key=r.person_key
            WHERE r.fusion_id=?
            ORDER BY r.nb_regimes DESC,r.occurrences DESC,r.matricule_normalise,r.nom_normalise
        """

    def occurrence_consistency(self, fusion_id: str) -> dict:
        """Vérifie que les lignes physiques correspondent aux occurrences agrégées."""
        with self.db.connect() as con:
            physical = int(con.execute("""
                SELECT COUNT(*) FROM paie_standardisee
                WHERE execution_id IN (
                    SELECT DISTINCT execution_id FROM sources_fusion_raw
                    WHERE fusion_id=? AND execution_id IS NOT NULL
                )
            """, [fusion_id]).fetchone()[0] or 0)
            aggregated = int(con.execute("""
                SELECT COALESCE(SUM(occurrences),0)
                FROM resultats_fusion_multi WHERE fusion_id=?
            """, [fusion_id]).fetchone()[0] or 0)
            agents = int(con.execute("""
                SELECT COUNT(*) FROM resultats_fusion_multi WHERE fusion_id=?
            """, [fusion_id]).fetchone()[0] or 0)
        return {
            "physical_rows": physical,
            "aggregated_occurrences": aggregated,
            "agents": agents,
            "difference": physical - aggregated,
            "ok": physical == aggregated,
        }

    def export_occurrences(self, fusion_id: str, folder: str | Path, progress=None) -> Path:
        folder = Path(folder)
        target = folder / "11_toutes_occurrences_confondues.xlsx"
        check = self.occurrence_consistency(fusion_id)
        if not check["ok"]:
            raise ValueError(
                "Incoherence des occurrences de fusion : "
                f"{check['physical_rows']} lignes physiques contre "
                f"{check['aggregated_occurrences']} occurrences agregees."
            )

        progress and progress(90, "Annexe occurrences : synthese par agent")
        book = Workbook(write_only=True)
        with self.db.connect() as con:
            append_query_sheets(
                book, con, self._summary_query(), [fusion_id], self.SUMMARY_HEADERS,
                sheet_name="Synthese agents",
            )
            progress and progress(94, "Annexe occurrences : toutes les lignes source")
            exported = append_query_sheets(
                book, con, self._occurrence_query(), [fusion_id, fusion_id, fusion_id],
                self.OCCURRENCE_HEADERS, sheet_name="Toutes les lignes",
            )

        if exported != check["physical_rows"]:
            raise ValueError(
                "Export incomplet des occurrences : "
                f"{exported} lignes exportees sur {check['physical_rows']} attendues."
            )

        control = book.create_sheet("Controle coherence")
        control.append(["Indicateur", "Valeur"])
        control.append(["Agents analyses", check["agents"]])
        control.append(["Lignes physiques sources", check["physical_rows"]])
        control.append(["Occurrences agregees", check["aggregated_occurrences"]])
        control.append(["Lignes exportees", exported])
        control.append(["Difference", check["difference"]])
        control.append(["Controle", "OK" if check["ok"] and exported == check["physical_rows"] else "ECHEC"])
        atomic_save_workbook(book, target)
        progress and progress(99, f"Fichier genere : {target.name}")
        return target

    def export_all(self, fusion_id, parent_folder, progress=None):
        def base_progress(value, text=""):
            if progress:
                progress(min(88, int(max(0, value) * 0.88)), text)

        folder = Path(super().export_all(fusion_id, parent_folder, progress=base_progress))
        self.export_occurrences(fusion_id, folder, progress=progress)
        progress and progress(100, "Export exhaustif termine, occurrences incluses")
        return str(folder)
