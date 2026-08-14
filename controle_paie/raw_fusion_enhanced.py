from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font

from .raw_fusion_duplicates import DuplicateAwareRawFusionService
from .spreadsheet_utils import sanitize_excel_row


class EnhancedRawFusionService(DuplicateAwareRawFusionService):
    """Service complet : fusion, réanalyse, doublons et exports dédiés."""

    def export_all(self, fusion_id, parent_folder, progress=None):
        folder = Path(super().export_all(fusion_id, parent_folder, progress=progress))
        headers = ["Statut","Matricule","Nom","Prénom","Régimes","Nb régimes","Nb institutions","Occurrences",
                   "Masse brute","Masse nette","Sections","Catégories","Grades","Unités d'affectation","Provinces",
                   "Multi-régimes","Paiement multiple même régime","Identité incohérente","Diagnostic"]
        for index, (filename, status) in enumerate([
            ("09_doublons_matricule.xlsx", "DOUBLON_MATRICULE"),
            ("10_doublons_nom.xlsx", "DOUBLON_NOM"),
        ], start=1):
            progress and progress(90 + index * 4, f"Export {filename}")
            book = Workbook(); sheet = book.active; sheet.title = "Résultats"; sheet.append(headers)
            for cell in sheet[1]: cell.font = Font(bold=True)
            for row in self.list_results(fusion_id, status, 10000):
                sheet.append(list(sanitize_excel_row(row)))
            sheet.freeze_panes = "A2"; sheet.auto_filter.ref = sheet.dimensions
            book.save(folder / filename)
        progress and progress(100, "Export complet terminé")
        return str(folder)
