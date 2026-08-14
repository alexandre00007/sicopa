from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font

from .raw_fusion_duplicates import DuplicateAwareRawFusionService
from .spreadsheet_utils import sanitize_excel_row


class EnhancedRawFusionService(DuplicateAwareRawFusionService):
    """Service complet : fusion, réanalyse, doublons et garde-fous d'identité."""

    def _apply_strict_identity_guard(self, fusion_id: str) -> None:
        """Empêche une identité incohérente d'être présentée comme multi-régime certaine."""
        with self.db.connect() as con:
            con.execute("""UPDATE resultats_fusion_multi SET
                    statut='MATRICULE_PARTAGE_IDENTITES_DIFFERENTES',
                    paiement_multi_regime=FALSE,
                    paiement_multiple_meme_regime=FALSE,
                    diagnostic=TRIM(CONCAT_WS(' ; ',NULLIF(diagnostic,''),
                        'Conclusion bloquée : ce matricule est associé à plusieurs noms normalisés'))
                WHERE fusion_id=? AND COALESCE(identite_incoherente,FALSE)""", [fusion_id])

    def create_fusion(self, table_names, quarter, year, suffix="", progress=None):
        info = super().create_fusion(table_names, quarter, year, suffix, progress=progress)
        progress and progress(97, "Application des contrôles stricts d'identité")
        self._apply_strict_identity_guard(info["id"])
        progress and progress(100, "Fusion et analyse strictes terminées")
        return self.get_fusion(info["id"])

    def reanalyze(self, fusion_id: str, progress=None):
        info = super().reanalyze(fusion_id, progress=progress)
        progress and progress(97, "Application des contrôles stricts d'identité")
        self._apply_strict_identity_guard(fusion_id)
        progress and progress(100, "Réanalyse stricte terminée")
        return self.get_fusion(fusion_id)

    def export_all(self, fusion_id, parent_folder, progress=None):
        folder = Path(super().export_all(fusion_id, parent_folder, progress=progress))
        headers = ["Statut","Matricule","Nom","Prénom","Régimes","Nb régimes","Nb institutions","Occurrences",
                   "Masse brute","Masse nette","Sections","Catégories","Grades","Unités d'affectation","Provinces",
                   "Multi-régimes","Paiement multiple même régime","Identité incohérente","Diagnostic"]
        for index, (filename, status) in enumerate([
            ("09_doublons_matricule.xlsx", "DOUBLON_MATRICULE"),
            ("10_doublons_nom.xlsx", "DOUBLON_NOM"),
            ("11_identites_incoherentes_strictes.xlsx", "MATRICULE_PARTAGE_IDENTITES_DIFFERENTES"),
        ], start=1):
            progress and progress(88 + index * 3, f"Export {filename}")
            book = Workbook(); sheet = book.active; sheet.title = "Résultats"; sheet.append(headers)
            for cell in sheet[1]: cell.font = Font(bold=True)
            for row in self.list_results(fusion_id, status, 10000):
                sheet.append(list(sanitize_excel_row(row)))
            sheet.freeze_panes = "A2"; sheet.auto_filter.ref = sheet.dimensions
            book.save(folder / filename)
        progress and progress(100, "Export complet terminé")
        return str(folder)
