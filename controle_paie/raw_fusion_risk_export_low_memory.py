from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from .export_streaming import append_query_sheets, atomic_save_workbook
from .raw_fusion_export_memory import (
    cleanup_fusion_export_tables,
    configure_low_memory_export,
    prepare_fusion_export_tables,
)
from .raw_fusion_risk_export import RISK_DETAIL_HEADERS, RISK_SUMMARY_HEADERS, RawFusionRiskExporter


class LowMemoryRawFusionRiskExporter(RawFusionRiskExporter):
    """Annexe 12 optimisée : base/stats matérialisées une seule fois, sans tris globaux."""

    @staticmethod
    def _category_expr_low_memory(r: str = "r", s: str = "s", d: str = "d") -> str:
        return f"""CASE
            WHEN COALESCE({r}.identite_incoherente,FALSE)
                OR {r}.statut='MATRICULE_PARTAGE_IDENTITES_DIFFERENTES'
                THEN 'MATRICULE_PARTAGE_NOMS_DIFFERENTS'
            WHEN COALESCE({s}.has_matricule_vide,FALSE) THEN 'MATRICULE_NULL_OU_VIDE'
            WHEN COALESCE({s}.has_matricule_nu,FALSE) THEN 'MATRICULE_NU'
            WHEN COALESCE({s}.has_matricule_non_exploitable,FALSE) THEN 'MATRICULE_NON_EXPLOITABLE'
            WHEN COALESCE({r}.paiement_multiple_meme_regime,FALSE) THEN 'PAIEMENT_MULTIPLE_MEME_REGIME'
            WHEN COALESCE({d}.doublon_matricule,FALSE) AND COALESCE({d}.doublon_nom,FALSE)
                THEN 'PAR_MATRICULE_ET_NOM'
            WHEN COALESCE({d}.doublon_matricule,FALSE) THEN 'PAR_MATRICULE'
            WHEN COALESCE({d}.doublon_nom,FALSE) THEN 'PAR_NOM'
            WHEN COALESCE({r}.nb_institutions,0)>1 THEN 'PLUSIEURS_INSTITUTIONS'
            WHEN COALESCE({r}.nb_regimes,0)>1 THEN 'MULTI_REGIME'
            ELSE 'AUTRE_ANOMALIE'
        END"""

    @staticmethod
    def _risk_predicate_low_memory(r: str = "r", s: str = "s", d: str = "d") -> str:
        return f"""(
            COALESCE({r}.nb_regimes,0)>1
            OR COALESCE({r}.occurrences,0)>1
            OR COALESCE({r}.nb_institutions,0)>1
            OR COALESCE({r}.paiement_multiple_meme_regime,FALSE)
            OR COALESCE({r}.identite_incoherente,FALSE)
            OR COALESCE({d}.doublon_matricule,FALSE)
            OR COALESCE({d}.doublon_nom,FALSE)
            OR COALESCE({s}.has_matricule_vide,FALSE)
            OR COALESCE({s}.has_matricule_nu,FALSE)
            OR COALESCE({s}.has_matricule_non_exploitable,FALSE)
        )"""

    def _summary_query_low_memory(self) -> str:
        category = self._category_expr_low_memory()
        risk = self._risk_predicate_low_memory()
        return f"""SELECT {category} categorie_anomalie,
            r.statut,r.matricule_normalise,r.nom_normalise,r.nom,r.prenom,r.regimes,r.institutions,
            r.nb_regimes,r.nb_institutions,r.occurrences,GREATEST(r.occurrences-1,0),
            s.nb_executions,s.nb_tables,r.masse_brute,r.masse_net,
            COALESCE(d.doublon_matricule,FALSE),COALESCE(d.doublon_nom,FALSE),
            r.paiement_multi_regime,r.paiement_multiple_meme_regime,r.identite_incoherente,r.diagnostic
        FROM resultats_fusion_multi r
        JOIN tmp_sicorpa_fusion_export_stats s ON s.person_key=r.person_key
        LEFT JOIN resultats_fusion_doublons d
          ON d.fusion_id=r.fusion_id AND d.person_key=r.person_key
        WHERE r.fusion_id=? AND {risk}"""

    def _detail_query_low_memory(self, category_filter: str | None = None) -> tuple[str, list]:
        category = self._category_expr_low_memory()
        risk = self._risk_predicate_low_memory()
        extra = ""
        params: list = []
        if category_filter:
            extra = f" AND ({category})=?"
            params.append(category_filter)
        return f"""SELECT {category} categorie_anomalie,
            COALESCE(src.table_source,b.table_source,''),b.execution_id,b.ligne_paie_id,b.ligne_source,
            b.regime,b.institution_id,b.trimestre,b.annee,b.matricule_source,b.matricule_normalise,
            b.nom,b.prenom,b.nom_normalise,b.section,b.categorie,b.grade,b.unite_affectation,b.province,
            b.remuneration_brute_calculee,b.montant_net,r.statut,r.nb_regimes,r.occurrences,
            GREATEST(r.occurrences-1,0),s.nb_executions,s.nb_tables,r.regimes,r.institutions,
            s.noms_distincts,s.matricules_distincts,COALESCE(d.doublon_matricule,FALSE),
            COALESCE(d.doublon_nom,FALSE),r.paiement_multi_regime,r.paiement_multiple_meme_regime,
            r.identite_incoherente,r.diagnostic
        FROM tmp_sicorpa_fusion_export_base b
        JOIN resultats_fusion_multi r ON r.fusion_id=? AND r.person_key=b.person_key
        JOIN tmp_sicorpa_fusion_export_stats s ON s.person_key=b.person_key
        LEFT JOIN tmp_sicorpa_fusion_export_src src ON src.execution_id=b.execution_id
        LEFT JOIN resultats_fusion_doublons d
          ON d.fusion_id=r.fusion_id AND d.person_key=r.person_key
        WHERE {risk}{extra}""", params

    def export(self, fusion_id: str, folder: str | Path, progress=None) -> Path:
        folder = Path(folder)
        target = folder / "12_synthese_occurrences_agents_a_risque.xlsx"
        book = Workbook(write_only=True)

        progress and progress(96, "Annexe 12 : préparation faible mémoire")
        with self.db.connect() as con:
            configure_low_memory_export(con, getattr(self.db, "threads", 2))
            prepare_fusion_export_tables(con, fusion_id)
            try:
                summary_query = self._summary_query_low_memory()
                risky_agents = int(con.execute(
                    "SELECT COUNT(*) FROM (" + summary_query + ") q", [fusion_id]
                ).fetchone()[0] or 0)
                all_agents = int(con.execute(
                    "SELECT COUNT(*) FROM resultats_fusion_multi WHERE fusion_id=?", [fusion_id]
                ).fetchone()[0] or 0)
                healthy_single = int(con.execute("""SELECT COUNT(*) FROM resultats_fusion_multi r
                    LEFT JOIN resultats_fusion_doublons d
                      ON d.fusion_id=r.fusion_id AND d.person_key=r.person_key
                    JOIN tmp_sicorpa_fusion_export_stats s ON s.person_key=r.person_key
                    WHERE r.fusion_id=? AND COALESCE(r.nb_regimes,0)=1 AND COALESCE(r.occurrences,0)=1
                      AND COALESCE(r.nb_institutions,0)<=1
                      AND NOT COALESCE(r.paiement_multiple_meme_regime,FALSE)
                      AND NOT COALESCE(r.identite_incoherente,FALSE)
                      AND NOT COALESCE(d.doublon_matricule,FALSE)
                      AND NOT COALESCE(d.doublon_nom,FALSE)
                      AND NOT COALESCE(s.has_matricule_vide,FALSE)
                      AND NOT COALESCE(s.has_matricule_nu,FALSE)
                      AND NOT COALESCE(s.has_matricule_non_exploitable,FALSE)""", [fusion_id]).fetchone()[0] or 0)

                detail_all, _ = self._detail_query_low_memory()
                risky_rows = int(con.execute(
                    "SELECT COUNT(*) FROM (" + detail_all + ") q", [fusion_id]
                ).fetchone()[0] or 0)

                progress and progress(97, "Annexe 12 : synthèse des agents à risque")
                summary_rows = append_query_sheets(
                    book, con, summary_query, [fusion_id], RISK_SUMMARY_HEADERS,
                    sheet_name="Synthese generale", chunk_size=2000,
                )
                categories = [
                    ("01_Par_matricule", "PAR_MATRICULE"),
                    ("02_Par_nom", "PAR_NOM"),
                    ("03_Matricule_et_nom", "PAR_MATRICULE_ET_NOM"),
                    ("04_Matricule_NU", "MATRICULE_NU"),
                    ("05_Null_vide", "MATRICULE_NULL_OU_VIDE"),
                    ("06_Non_exploitable", "MATRICULE_NON_EXPLOITABLE"),
                    ("07_Identites_incoh", "MATRICULE_PARTAGE_NOMS_DIFFERENTS"),
                    ("08_Multi_regimes", "MULTI_REGIME"),
                    ("09_Paiements_multiples", "PAIEMENT_MULTIPLE_MEME_REGIME"),
                    ("10_Plusieurs_instit", "PLUSIEURS_INSTITUTIONS"),
                    ("11_Autres_anomalies", "AUTRE_ANOMALIE"),
                ]
                exported_detail = 0
                for sheet_name, category_name in categories:
                    query, extra = self._detail_query_low_memory(category_name)
                    exported_detail += append_query_sheets(
                        book, con, query, [fusion_id] + extra, RISK_DETAIL_HEADERS,
                        sheet_name=sheet_name, chunk_size=2000,
                    )

                control = book.create_sheet("Controle")
                control.append(["Indicateur", "Valeur"])
                control.append(["Mode export", "FAIBLE_MEMOIRE"])
                control.append(["Agents analyses au total", all_agents])
                control.append(["Agents a risque", risky_agents])
                control.append(["Agents sains mono-regime exclus", healthy_single])
                control.append(["Lignes physiques a risque attendues", risky_rows])
                control.append(["Lignes detail exportees", exported_detail])
                control.append(["Lignes synthese exportees", summary_rows])
                control.append(["Controle exclusion", "OK" if risky_agents <= all_agents else "ECHEC"])
                control.append(["Controle detail", "OK" if exported_detail == risky_rows else "ECHEC"])

                if summary_rows != risky_agents:
                    raise ValueError(
                        f"Annexe 12 incoherente : {summary_rows} agents exportes sur {risky_agents} attendus."
                    )
                if exported_detail != risky_rows:
                    raise ValueError(
                        f"Annexe 12 incomplete : {exported_detail} lignes detaillees sur {risky_rows} attendues."
                    )
            finally:
                cleanup_fusion_export_tables(con)

        atomic_save_workbook(book, target)
        progress and progress(99, f"Fichier genere : {target.name}")
        return target
