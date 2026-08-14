from __future__ import annotations

from datetime import datetime
from pathlib import Path

from openpyxl import Workbook

from .export_streaming import write_query_xlsx
from .raw_fusion_enhanced import EnhancedRawFusionService
from .spreadsheet_utils import sanitize_excel_row


class ScalableRawFusionService(EnhancedRawFusionService):
    """Fusion multi-régimes avec exports exhaustifs, sans LIMIT d'affichage."""

    RESULT_HEADERS = [
        "Statut", "Matricule", "Nom", "Prénom", "Régimes", "Nb régimes", "Nb institutions",
        "Occurrences", "Masse brute", "Masse nette", "Sections", "Catégories", "Grades",
        "Unités d'affectation", "Provinces", "Multi-régimes", "Paiement multiple même régime",
        "Identité incohérente", "Diagnostic",
    ]

    def _result_query(self, status: str = ""):
        condition = "r.fusion_id=?"
        params = []
        if status == "DOUBLON_MATRICULE":
            condition += " AND COALESCE(d.doublon_matricule,FALSE)"
        elif status == "DOUBLON_NOM":
            condition += " AND COALESCE(d.doublon_nom,FALSE)"
        elif status:
            condition += " AND r.statut=?"
            params.append(status)
        query = f"""SELECT r.statut,r.matricule_normalise,r.nom,r.prenom,r.regimes,r.nb_regimes,r.nb_institutions,
                r.occurrences,r.masse_brute,r.masse_net,r.sections,r.categories,r.grades,r.unites_affectation,r.provinces,
                r.paiement_multi_regime,r.paiement_multiple_meme_regime,r.identite_incoherente,
                TRIM(CONCAT_WS(' ; ',NULLIF(r.diagnostic,''),
                  CASE WHEN COALESCE(d.doublon_matricule,FALSE) THEN 'Doublon matricule ('||CAST(d.occurrences_matricule AS VARCHAR)||' occurrences)' END,
                  CASE WHEN COALESCE(d.doublon_nom,FALSE) THEN 'Doublon nom ('||CAST(d.occurrences_nom AS VARCHAR)||' occurrences)' END))
            FROM resultats_fusion_multi r
            LEFT JOIN resultats_fusion_doublons d ON d.fusion_id=r.fusion_id AND d.person_key=r.person_key
            WHERE {condition}
            ORDER BY r.nb_regimes DESC,r.occurrences DESC,r.masse_brute DESC"""
        return query, params

    def export_all(self, fusion_id, parent_folder, progress=None):
        info = self.get_fusion(fusion_id)
        folder = Path(parent_folder) / f"fusion_multi_regimes_{info['quarter']}_{info['year']}_{datetime.now():%Y%m%d_%H%M%S}"
        folder.mkdir(parents=True, exist_ok=True)
        progress and progress(5, "Création de la synthèse")

        book = Workbook()
        sheet = book.active
        sheet.title = "Synthèse"
        sheet.append(["Indicateur", "Valeur"])
        for row in [
            ("Table fusionnée", info["table"]),
            ("Période", f"{info['quarter']} {info['year']}"),
            ("Lignes RAW", info["rows"]),
            ("Sources", info["sources"]),
            ("Régimes", info["regimes"]),
        ]:
            sheet.append(list(sanitize_excel_row(row)))
        sheet.append([])
        sheet.append(["Statut", "Agents", "Occurrences", "Masse brute", "Masse nette"])
        for row in self.summary(fusion_id):
            sheet.append(list(sanitize_excel_row(row)))
        book.save(folder / "00_synthese.xlsx")

        exports = [
            ("01_tous_les_agents.xlsx", ""),
            ("02_agents_deux_regimes.xlsx", "DEUX_REGIMES"),
            ("03_agents_trois_regimes_plus.xlsx", "TROIS_REGIMES_OU_PLUS"),
            ("04_paiements_multiples.xlsx", "PAIEMENT_MULTIPLE_MEME_REGIME"),
            ("05_identites_incoherentes.xlsx", "IDENTITE_INCOHERENTE"),
            ("06_plusieurs_institutions.xlsx", "PLUSIEURS_INSTITUTIONS"),
            ("09_doublons_matricule.xlsx", "DOUBLON_MATRICULE"),
            ("10_doublons_nom.xlsx", "DOUBLON_NOM"),
        ]
        with self.db.connect() as con:
            for index, (filename, status) in enumerate(exports, start=1):
                progress and progress(8 + int(68 * index / len(exports)), f"Export complet {filename}")
                query, extra = self._result_query(status)
                write_query_xlsx(
                    con,
                    folder / filename,
                    query,
                    [fusion_id] + extra,
                    self.RESULT_HEADERS,
                    "Résultats",
                )

            progress and progress(80, "Création de la matrice des régimes")
            regimes, matrix = self.regime_matrix(fusion_id)
            matrix_book = Workbook()
            matrix_sheet = matrix_book.active
            matrix_sheet.title = "Matrice"
            matrix_sheet.append(["Régime"] + regimes)
            for row in matrix:
                matrix_sheet.append(row)
            matrix_book.save(folder / "07_matrice_regimes.xlsx")

            progress and progress(88, "Export complet du RAW fusionné")
            table = self._quote(info["table"])
            write_query_xlsx(
                con,
                folder / "08_listing_fusionne_complet.xlsx",
                f"SELECT * FROM {table}",
                headers=None,
                sheet_name="Listing fusionné",
            )
            con.execute("UPDATE fusions_raw SET dossier_export=? WHERE fusion_id=?", [str(folder), fusion_id])

        progress and progress(100, "Export exhaustif terminé")
        return str(folder)
