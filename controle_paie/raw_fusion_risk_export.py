from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from .export_streaming import append_query_sheets, atomic_save_workbook


RISK_SUMMARY_HEADERS = [
    "Categorie anomalie", "Statut", "Matricule", "Nom normalise", "Nom", "Prenom",
    "Regimes", "Institutions", "Nb regimes", "Nb institutions", "Nb lignes physiques",
    "Nb repetitions", "Nb executions", "Nb tables RAW", "Masse brute", "Masse nette",
    "Doublon matricule", "Doublon nom", "Multi-regimes", "Multiple meme regime",
    "Identite incoherente", "Diagnostic",
]

RISK_DETAIL_HEADERS = [
    "Categorie anomalie", "Table RAW source", "Execution ID", "Ligne paie ID", "Ligne source",
    "Regime", "Institution", "Trimestre", "Annee", "Matricule source", "Matricule normalise",
    "Nom", "Prenom", "Nom normalise", "Section", "Categorie", "Grade", "Unite d'affectation",
    "Province", "Remuneration brute", "Montant net", "Statut analyse", "Nb regimes agent",
    "Nb lignes physiques agent", "Nb repetitions agent", "Nb executions agent", "Nb tables RAW agent",
    "Regimes agent", "Institutions agent", "Noms distincts agent", "Matricules distincts agent",
    "Doublon matricule", "Doublon nom", "Multi-regimes", "Multiple meme regime",
    "Identite incoherente", "Diagnostic",
]


class RawFusionRiskExporter:
    """Produit l'annexe ciblée sur les agents multi-régimes ou présentant une anomalie."""

    BAD_MATRICULES = "('', 'NU', 'NULL', 'N/A', 'NA', 'NEANT', 'NÉANT', 'INCONNU', 'NONE')"

    def __init__(self, db):
        self.db = db

    @staticmethod
    def _category_expr(alias: str = "r", source_alias: str = "b", duplicate_alias: str = "d") -> str:
        r, b, d = alias, source_alias, duplicate_alias
        return f"""CASE
            WHEN COALESCE({r}.identite_incoherente,FALSE)
                OR {r}.statut='MATRICULE_PARTAGE_IDENTITES_DIFFERENTES'
                THEN 'MATRICULE_PARTAGE_NOMS_DIFFERENTS'
            WHEN COALESCE(NULLIF(TRIM({b}.matricule_source),''),'')='' THEN 'MATRICULE_NULL_OU_VIDE'
            WHEN UPPER(TRIM(COALESCE({b}.matricule_source,'')))='NU' THEN 'MATRICULE_NU'
            WHEN UPPER(TRIM(COALESCE({b}.matricule_source,''))) IN ('NULL','N/A','NA','NEANT','NÉANT','INCONNU','NONE')
                THEN 'MATRICULE_NON_EXPLOITABLE'
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
    def _risk_predicate(r: str = "r", b: str = "b", d: str = "d") -> str:
        # Un agent sain mono-régime n'entre jamais dans l'annexe 12.
        return f"""(
            COALESCE({r}.nb_regimes,0)>1
            OR COALESCE({r}.occurrences,0)>1
            OR COALESCE({r}.nb_institutions,0)>1
            OR COALESCE({r}.paiement_multiple_meme_regime,FALSE)
            OR COALESCE({r}.identite_incoherente,FALSE)
            OR COALESCE({d}.doublon_matricule,FALSE)
            OR COALESCE({d}.doublon_nom,FALSE)
            OR COALESCE(NULLIF(TRIM({b}.matricule_source),''),'')=''
            OR UPPER(TRIM(COALESCE({b}.matricule_source,''))) IN ('NU','NULL','N/A','NA','NEANT','NÉANT','INCONNU','NONE')
        )"""

    def _base_cte(self) -> str:
        return """
            WITH fusion AS (
                SELECT fusion_id,trimestre,annee FROM fusions_raw WHERE fusion_id=?
            ), src AS (
                SELECT s.execution_id,MIN(s.table_source) AS table_source
                FROM sources_fusion_raw s JOIN fusion f ON f.fusion_id=s.fusion_id
                GROUP BY s.execution_id
            ), base AS (
                SELECT p.*,
                    CASE
                        WHEN COALESCE(p.matricule_normalise,'') NOT IN ('','NU') THEN 'M:'||p.matricule_normalise
                        WHEN COALESCE(p.nom_normalise,'')<>'' THEN 'N:'||p.nom_normalise
                        ELSE 'L:'||p.ligne_paie_id
                    END AS person_key
                FROM paie_standardisee p CROSS JOIN fusion f
                WHERE p.trimestre=f.trimestre AND p.annee=f.annee
                  AND p.execution_id IN (
                    SELECT DISTINCT execution_id FROM sources_fusion_raw
                    WHERE fusion_id=f.fusion_id AND execution_id IS NOT NULL
                  )
            ), stats AS (
                SELECT person_key,
                    COUNT(DISTINCT execution_id) nb_executions,
                    COUNT(DISTINCT COALESCE(table_source,'')) nb_tables,
                    STRING_AGG(DISTINCT NULLIF(nom_normalise,''),' | ' ORDER BY NULLIF(nom_normalise,'')) noms_distincts,
                    STRING_AGG(DISTINCT NULLIF(matricule_normalise,''),' | ' ORDER BY NULLIF(matricule_normalise,'')) matricules_distincts
                FROM base GROUP BY person_key
            )
        """

    def summary_query(self) -> str:
        category = self._category_expr()
        risk = self._risk_predicate()
        return self._base_cte() + f"""
            SELECT {category} categorie_anomalie,
                r.statut,r.matricule_normalise,r.nom_normalise,r.nom,r.prenom,r.regimes,r.institutions,
                r.nb_regimes,r.nb_institutions,r.occurrences,GREATEST(r.occurrences-1,0),
                s.nb_executions,s.nb_tables,r.masse_brute,r.masse_net,
                COALESCE(d.doublon_matricule,FALSE),COALESCE(d.doublon_nom,FALSE),
                r.paiement_multi_regime,r.paiement_multiple_meme_regime,r.identite_incoherente,r.diagnostic
            FROM resultats_fusion_multi r
            JOIN stats s ON s.person_key=r.person_key
            LEFT JOIN resultats_fusion_doublons d ON d.fusion_id=r.fusion_id AND d.person_key=r.person_key
            LEFT JOIN base b ON b.person_key=r.person_key
            WHERE r.fusion_id=? AND {risk}
            QUALIFY ROW_NUMBER() OVER (PARTITION BY r.person_key ORDER BY b.ligne_paie_id)=1
            ORDER BY categorie_anomalie,r.nb_regimes DESC,r.occurrences DESC,r.matricule_normalise,r.nom_normalise
        """

    def detail_query(self, category_filter: str | None = None) -> tuple[str, list]:
        category = self._category_expr()
        risk = self._risk_predicate()
        extra_where = ""
        params: list = []
        if category_filter:
            extra_where = f" AND ({category})=?"
            params.append(category_filter)
        query = self._base_cte() + f"""
            SELECT {category} categorie_anomalie,
                COALESCE(src.table_source,b.table_source,''),b.execution_id,b.ligne_paie_id,b.ligne_source,
                b.regime,b.institution_id,b.trimestre,b.annee,b.matricule_source,b.matricule_normalise,
                b.nom,b.prenom,b.nom_normalise,b.section,b.categorie,b.grade,b.unite_affectation,b.province,
                b.remuneration_brute_calculee,b.montant_net,r.statut,r.nb_regimes,r.occurrences,
                GREATEST(r.occurrences-1,0),s.nb_executions,s.nb_tables,r.regimes,r.institutions,
                s.noms_distincts,s.matricules_distincts,COALESCE(d.doublon_matricule,FALSE),
                COALESCE(d.doublon_nom,FALSE),r.paiement_multi_regime,r.paiement_multiple_meme_regime,
                r.identite_incoherente,r.diagnostic
            FROM base b
            JOIN resultats_fusion_multi r ON r.fusion_id=? AND r.person_key=b.person_key
            JOIN stats s ON s.person_key=b.person_key
            LEFT JOIN src ON src.execution_id=b.execution_id
            LEFT JOIN resultats_fusion_doublons d ON d.fusion_id=r.fusion_id AND d.person_key=r.person_key
            WHERE {risk}{extra_where}
            ORDER BY categorie_anomalie,r.nb_regimes DESC,r.occurrences DESC,
                     r.matricule_normalise,r.nom_normalise,b.regime,b.execution_id,b.ligne_source,b.ligne_paie_id
        """
        return query, params

    def _counts(self, fusion_id: str) -> dict:
        with self.db.connect() as con:
            summary_sql = "SELECT COUNT(*) FROM (" + self.summary_query() + ") q"
            risky_agents = int(con.execute(summary_sql, [fusion_id, fusion_id]).fetchone()[0] or 0)
            detail_sql, extra = self.detail_query()
            risky_rows = int(con.execute("SELECT COUNT(*) FROM (" + detail_sql + ") q", [fusion_id, fusion_id] + extra).fetchone()[0] or 0)
            all_agents = int(con.execute("SELECT COUNT(*) FROM resultats_fusion_multi WHERE fusion_id=?", [fusion_id]).fetchone()[0] or 0)
            healthy_single = int(con.execute("""SELECT COUNT(*) FROM resultats_fusion_multi r
                LEFT JOIN resultats_fusion_doublons d ON d.fusion_id=r.fusion_id AND d.person_key=r.person_key
                WHERE r.fusion_id=? AND COALESCE(r.nb_regimes,0)=1 AND COALESCE(r.occurrences,0)=1
                  AND COALESCE(r.nb_institutions,0)<=1 AND NOT COALESCE(r.paiement_multiple_meme_regime,FALSE)
                  AND NOT COALESCE(r.identite_incoherente,FALSE)
                  AND NOT COALESCE(d.doublon_matricule,FALSE) AND NOT COALESCE(d.doublon_nom,FALSE)""", [fusion_id]).fetchone()[0] or 0)
        return {"all_agents": all_agents, "risky_agents": risky_agents, "risky_rows": risky_rows, "healthy_single": healthy_single}

    def export(self, fusion_id: str, folder: str | Path, progress=None) -> Path:
        folder = Path(folder)
        target = folder / "12_synthese_occurrences_agents_a_risque.xlsx"
        counts = self._counts(fusion_id)
        book = Workbook(write_only=True)

        progress and progress(95, "Annexe 12 : synthese des agents a risque")
        with self.db.connect() as con:
            summary_rows = append_query_sheets(
                book, con, self.summary_query(), [fusion_id, fusion_id], RISK_SUMMARY_HEADERS,
                sheet_name="Synthese generale",
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
            ]
            exported_detail = 0
            for sheet_name, category_name in categories:
                query, extra = self.detail_query(category_name)
                exported_detail += append_query_sheets(
                    book, con, query, [fusion_id, fusion_id] + extra, RISK_DETAIL_HEADERS,
                    sheet_name=sheet_name,
                )

            # Cette feuille garantit qu'aucune anomalie non couverte par une catégorie spécialisée ne soit perdue.
            query, extra = self.detail_query("AUTRE_ANOMALIE")
            exported_detail += append_query_sheets(
                book, con, query, [fusion_id, fusion_id] + extra, RISK_DETAIL_HEADERS,
                sheet_name="11_Autres_anomalies",
            )

        control = book.create_sheet("Controle")
        control.append(["Indicateur", "Valeur"])
        control.append(["Agents analyses au total", counts["all_agents"]])
        control.append(["Agents a risque", counts["risky_agents"]])
        control.append(["Agents sains mono-regime exclus", counts["healthy_single"]])
        control.append(["Lignes physiques a risque attendues", counts["risky_rows"]])
        control.append(["Lignes detail exportees", exported_detail])
        control.append(["Lignes synthese exportees", summary_rows])
        control.append(["Controle exclusion", "OK" if counts["risky_agents"] <= counts["all_agents"] else "ECHEC"])
        control.append(["Controle detail", "OK" if exported_detail == counts["risky_rows"] else "ECHEC"])

        if summary_rows != counts["risky_agents"]:
            raise ValueError(f"Annexe 12 incoherente : {summary_rows} agents exportes sur {counts['risky_agents']} attendus.")
        if exported_detail != counts["risky_rows"]:
            raise ValueError(f"Annexe 12 incomplete : {exported_detail} lignes detaillees sur {counts['risky_rows']} attendues.")

        atomic_save_workbook(book, target)
        progress and progress(99, f"Fichier genere : {target.name}")
        return target
