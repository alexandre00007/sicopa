from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from .export_streaming import append_query_sheets, atomic_save_workbook
from .raw_fusion_export_memory import (
    cleanup_fusion_export_tables,
    configure_low_memory_export,
    prepare_fusion_export_tables,
)
from .raw_fusion_occurrence_export import OccurrenceExportRawFusionService


class LowMemoryOccurrenceExportRawFusionService(OccurrenceExportRawFusionService):
    """Annexe 11 optimisée pour les fusions de plusieurs millions de lignes."""

    def _low_memory_detail_query(self) -> str:
        # Aucun ORDER BY global : Excel n'a pas besoin d'un tri pour l'audit et ce tri était
        # la principale cause de matérialisation mémoire avant le streaming fetchmany().
        return """
            SELECT
                r.fusion_id,
                COALESCE(src.table_source,b.table_source,''),
                b.execution_id,b.ligne_paie_id,b.ligne_source,b.regime,b.institution_id,
                b.trimestre,b.annee,b.matricule_source,b.matricule_normalise,b.nom,b.prenom,
                b.nom_normalise,b.section,b.categorie,b.grade,b.unite_affectation,b.province,
                b.remuneration_brute_calculee,b.montant_net,r.statut,r.nb_regimes,r.occurrences,
                GREATEST(r.occurrences-1,0),s.nb_executions,s.nb_tables,r.regimes,r.institutions,
                s.noms_distincts,s.matricules_distincts,
                COALESCE(d.doublon_matricule,FALSE),COALESCE(d.doublon_nom,FALSE),
                r.paiement_multi_regime,r.paiement_multiple_meme_regime,r.identite_incoherente,
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
            FROM tmp_sicorpa_fusion_export_base b
            JOIN resultats_fusion_multi r
              ON r.fusion_id=? AND r.person_key=b.person_key
            JOIN tmp_sicorpa_fusion_export_stats s ON s.person_key=b.person_key
            LEFT JOIN tmp_sicorpa_fusion_export_src src ON src.execution_id=b.execution_id
            LEFT JOIN resultats_fusion_doublons d
              ON d.fusion_id=r.fusion_id AND d.person_key=r.person_key
        """

    def export_occurrences(self, fusion_id: str, folder: str | Path, progress=None) -> Path:
        folder = Path(folder)
        target = folder / "11_toutes_occurrences_confondues.xlsx"
        progress and progress(89, "Annexe 11 : préparation faible mémoire")

        book = Workbook(write_only=True)
        with self.db.connect() as con:
            configure_low_memory_export(con, getattr(self.db, "threads", 2))
            prepared = prepare_fusion_export_tables(con, fusion_id)
            try:
                aggregated, aggregated_gross, aggregated_net = con.execute("""
                    SELECT COALESCE(SUM(occurrences),0),COALESCE(SUM(masse_brute),0),COALESCE(SUM(masse_net),0)
                    FROM resultats_fusion_multi WHERE fusion_id=?""", [fusion_id]).fetchone()
                agents = int(con.execute(
                    "SELECT COUNT(*) FROM resultats_fusion_multi WHERE fusion_id=?", [fusion_id]
                ).fetchone()[0] or 0)

                aggregated = int(aggregated or 0)
                aggregated_gross = float(aggregated_gross or 0)
                aggregated_net = float(aggregated_net or 0)
                gross_diff = prepared["physical_gross"] - aggregated_gross
                net_diff = prepared["physical_net"] - aggregated_net
                ok = (
                    prepared["physical_rows"] == aggregated
                    and abs(gross_diff) <= 0.01
                    and abs(net_diff) <= 0.01
                )
                if not ok:
                    raise ValueError(
                        "Incoherence de la fusion : "
                        f"lignes {prepared['physical_rows']} / occurrences {aggregated}, "
                        f"ecart brut {gross_diff:.2f}, ecart net {net_diff:.2f}."
                    )

                progress and progress(91, "Annexe 11 : synthèse par agent")
                append_query_sheets(
                    book, con, self._summary_query(), [fusion_id], self.SUMMARY_HEADERS,
                    sheet_name="Synthese agents", chunk_size=2000,
                )
                progress and progress(94, "Annexe 11 : export des lignes source")
                exported = append_query_sheets(
                    book, con, self._low_memory_detail_query(), [fusion_id],
                    self.OCCURRENCE_HEADERS, sheet_name="Toutes les lignes", chunk_size=2000,
                )

                if exported != prepared["physical_rows"]:
                    raise ValueError(
                        "Export incomplet des occurrences : "
                        f"{exported} lignes exportees sur {prepared['physical_rows']} attendues."
                    )

                control = book.create_sheet("Controle coherence")
                control.append(["Indicateur", "Valeur"])
                control.append(["Mode export", "FAIBLE_MEMOIRE"])
                control.append(["Periode", f"{prepared['quarter']} {prepared['year']}"])
                control.append(["Agents analyses", agents])
                control.append(["Lignes physiques sources", prepared["physical_rows"]])
                control.append(["Occurrences agregees", aggregated])
                control.append(["Lignes exportees", exported])
                control.append(["Difference lignes", prepared["physical_rows"] - aggregated])
                control.append(["Brut lignes physiques", prepared["physical_gross"]])
                control.append(["Brut agrege", aggregated_gross])
                control.append(["Difference brut", gross_diff])
                control.append(["Net lignes physiques", prepared["physical_net"]])
                control.append(["Net agrege", aggregated_net])
                control.append(["Difference net", net_diff])
                control.append(["Controle", "OK"])
            finally:
                cleanup_fusion_export_tables(con)

        atomic_save_workbook(book, target)
        progress and progress(97, f"Fichier genere : {target.name}")
        return target
