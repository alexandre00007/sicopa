from __future__ import annotations

from openpyxl import load_workbook
from openpyxl.styles import Font

from .regime_comparison_strict import StrictRegimeComparisonService
from .spreadsheet_utils import sanitize_excel_row


class StrictExportRegimeComparisonService(StrictRegimeComparisonService):
    """Ajoute les catégories strictes à l'export Excel historique."""

    def export(self, comparison_id: str, path: str) -> str:
        target = super().export(comparison_id, path)
        wb = load_workbook(target)
        ws = wb["Synthèse"]
        for row in ws.iter_rows(min_col=1, max_col=2):
            if row[0].value == "Agents communs / payés dans les deux":
                row[0].value = "Identités exactes communes"
            if row[0].value == "Écarts financiers":
                row[0].value = "Écarts financiers sur identités fiables"
            if row[0].value == "Écarts administratifs":
                row[0].value = "Écarts administratifs sur identités fiables"
        summary = self.get_summary(comparison_id)
        ws.append(["Double paiement potentiel — identité exacte", summary["double"]])
        ws.append(["Règle stricte", "Commun certain = même matricule normalisé ET même nom normalisé ; aucun candidat ambigu n'est choisi arbitrairement"])

        headers = ["Statut","Clé","Matricule","Nom","Occurrences A","Occurrences B","Brut A","Brut B",
                   "Écart brut","Net A","Net B","Écart net","Écart %","Grade A","Grade B","Catégorie A",
                   "Catégorie B","Affectation A","Affectation B","Diagnostic"]
        for title, status in [
            ("Nom probable", "COMMUN_PAR_NOM_PROBABLE"),
            ("Double paiement potentiel", "DOUBLE_PAIEMENT_POTENTIEL"),
            ("Nom matricule différent", "NOM_MATRICULE_DIFFERENT"),
            ("Ambigu matricule", "MATCH_AMBIGU_MATRICULE"),
            ("Ambigu nom", "MATCH_AMBIGU_NOM"),
        ]:
            if title[:31] in wb.sheetnames:
                del wb[title[:31]]
            sheet = wb.create_sheet(title[:31])
            sheet.append(headers)
            for cell in sheet[1]:
                cell.font = Font(bold=True)
            for row in self.list_results(comparison_id, status, 10000):
                sheet.append(list(sanitize_excel_row(row)))
            sheet.freeze_panes = "A2"
            sheet.auto_filter.ref = sheet.dimensions

        wb.save(target)
        return target
