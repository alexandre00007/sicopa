from __future__ import annotations

import math
from pathlib import Path

from openpyxl import Workbook

from .export_streaming import write_query_xlsx
from .raw_period_occurrences import OccurrenceAwareRawPeriodComparisonService


class OccurrenceExportRawPeriodComparisonService(OccurrenceAwareRawPeriodComparisonService):
    """Expose les métriques d'occurrences dans l'UI et les exports exhaustifs."""

    @staticmethod
    def _result_condition(comparison_id: str, status: str = ""):
        condition = "comparaison_id=?"
        params = [comparison_id]
        special = {
            "MEME_MATRICULE_NOM_DIFFERENT": "meme_matricule_nom_different",
            "MEME_NOM_MATRICULE_DIFFERENT": "meme_nom_matricule_different",
            "DOUBLON_MATRICULE_A": "doublon_matricule_a",
            "DOUBLON_MATRICULE_B": "doublon_matricule_b",
            "DOUBLON_NOM_A": "doublon_nom_a",
            "DOUBLON_NOM_B": "doublon_nom_b",
            "COMMUN_EXACT_1_VS_1": "situation_occurrences='COMMUN_EXACT_1_VS_1'",
            "COMMUN_EXACT_REPETE_A": "situation_occurrences='COMMUN_EXACT_REPETE_A'",
            "COMMUN_EXACT_REPETE_B": "situation_occurrences='COMMUN_EXACT_REPETE_B'",
            "COMMUN_EXACT_REPETE_A_ET_B": "situation_occurrences='COMMUN_EXACT_REPETE_A_ET_B'",
        }
        if status in special:
            condition += " AND " + special[status]
        elif status:
            condition += " AND statut=?"
            params.append(status)
        return condition, params

    def list_results_enriched(self, comparison_id: str, status: str = "", limit: int = 3000, offset: int = 0):
        condition, params = self._result_condition(comparison_id, status)
        limit = max(1, min(int(limit), 10000))
        offset = max(0, int(offset))
        params.extend([limit, offset])
        with self.db.connect() as con:
            return con.execute(f"""SELECT statut,matricule_a,matricule_b,nom_a,nom_b,prenom_a,prenom_b,
                commun_matricule,commun_nom,regime_a,regime_b,institution_a,institution_b,
                occurrences_a,occurrences_b,lignes_source_a,lignes_source_b,ecart_lignes,situation_occurrences,
                brut_a,brut_b,ecart_brut,net_a,net_b,ecart_net,
                section_a,section_b,categorie_a,categorie_b,grade_a,grade_b,unite_a,unite_b,province_a,province_b,
                executions_a,executions_b,numeros_lignes_a,numeros_lignes_b,montants_distincts_a,montants_distincts_b,diagnostic
                FROM resultats_comparaison_raw_periode WHERE {condition}
                ORDER BY CASE WHEN statut='COMMUN_PAR_MATRICULE_ET_NOM' THEN 0 ELSE 1 END,
                         GREATEST(occurrences_a,occurrences_b) DESC,ABS(ecart_brut) DESC LIMIT ? OFFSET ?""", params).fetchall()

    def page_results_enriched(self, comparison_id: str, status: str = "", page: int = 1, page_size: int = 250):
        page_size = max(25, min(int(page_size), 2000))
        condition, params = self._result_condition(comparison_id, status)
        with self.db.connect() as con:
            total = int(con.execute(
                f"SELECT COUNT(*) FROM resultats_comparaison_raw_periode WHERE {condition}", params
            ).fetchone()[0])
        total_pages = max(1, math.ceil(total / page_size))
        page = max(1, min(int(page), total_pages))
        offset = (page - 1) * page_size
        rows = self.list_results_enriched(comparison_id, status, page_size, offset)
        return {"rows": rows, "total": total, "page": page, "page_size": page_size,
                "total_pages": total_pages, "offset": offset}

    def delete(self, comparison_id: str):
        with self.db.connect() as con:
            con.execute("DELETE FROM occurrences_comparaison_raw WHERE comparaison_id=?", [comparison_id])
        return super().delete(comparison_id)

    def export_all(self, comparison_id: str, parent_folder, progress=None):
        folder = Path(super().export_all(comparison_id, parent_folder, progress=progress))
        progress and progress(92, "Export des occurrences détaillées")
        with self.db.connect() as con:
            headers = ["Côté","Table source","Execution ID","Ligne paie ID","Ligne source","Matricule normalisé",
                       "Nom normalisé","Nom","Prénom","Institution","Régime","Section","Catégorie","Grade",
                       "Unité d'affectation","Province","Brut","Net"]
            for side, filename in (("A", "17_occurrences_source_A.xlsx"), ("B", "18_occurrences_source_B.xlsx")):
                write_query_xlsx(
                    con, folder / filename,
                    """SELECT cote,table_source,execution_id,ligne_paie_id,ligne_source,matricule_normalise,
                              nom_normalise,nom,prenom,institution_id,regime,section,categorie,grade,
                              unite_affectation,province,brut,net
                       FROM occurrences_comparaison_raw
                       WHERE comparaison_id=? AND cote=?
                       ORDER BY matricule_normalise,nom_normalise,execution_id,ligne_source""",
                    [comparison_id, side], headers, f"Occurrences {side}",
                )

        metrics = self.occurrence_summary(comparison_id)
        wb = Workbook()
        ws = wb.active
        ws.title = "Occurrences"
        ws.append(["Indicateur", "Valeur"])
        for label, key in [
            ("Communs exacts", "communs_exacts"),
            ("Communs exacts 1 vs 1", "communs_1_vs_1"),
            ("Communs exacts répétés A", "communs_repetes_a"),
            ("Communs exacts répétés B", "communs_repetes_b"),
            ("Communs exacts répétés A et B", "communs_repetes_a_b"),
            ("Identités répétées A", "identites_repetees_a"),
            ("Identités répétées B", "identites_repetees_b"),
            ("Nombre total de répétitions A", "repetitions_a"),
            ("Nombre total de répétitions B", "repetitions_b"),
        ]:
            ws.append([label, metrics[key]])
        ws.append([])
        ws.append(["Règle", "Occurrences = répétitions après la première ligne; Nb lignes source = lignes physiques réelles."])
        wb.save(folder / "19_synthese_occurrences.xlsx")
        progress and progress(100, "Export des occurrences terminé")
        return str(folder)
