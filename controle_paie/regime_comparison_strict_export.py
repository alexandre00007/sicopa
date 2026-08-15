from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from .export_streaming import append_query_sheets, atomic_save_workbook
from .regime_comparison_versioned import VersionedStrictRegimeComparisonService


class StrictExportRegimeComparisonService(VersionedStrictRegimeComparisonService):
    """Export strict, exhaustif et streaming de la comparaison entre régimes."""

    HEADERS = ["Statut","Clé","Matricule","Nom","Occurrences A","Occurrences B","Brut A","Brut B",
               "Écart brut","Net A","Net B","Écart net","Écart %","Grade A","Grade B","Catégorie A",
               "Catégorie B","Affectation A","Affectation B","Diagnostic"]

    def _export_query(self, status: str = ""):
        condition = "comparaison_id=?"
        params = []
        if status == "DOUBLE_PAIEMENT":
            condition += " AND double_paiement"
        elif status:
            condition += " AND statut=?"
            params.append(status)
        query = f"""SELECT statut,cle_type,COALESCE(matricule_a,matricule_b,''),
                COALESCE(NULLIF(nom_a,''),nom_b,''),occurrences_a,occurrences_b,
                remuneration_a,remuneration_b,ecart_remuneration,net_a,net_b,ecart_net,ecart_pourcentage,
                COALESCE(grade_a,''),COALESCE(grade_b,''),COALESCE(categorie_a,''),COALESCE(categorie_b,''),
                COALESCE(affectation_a,''),COALESCE(affectation_b,''),diagnostic
            FROM resultats_comparaison_regimes WHERE {condition}
            ORDER BY CASE WHEN statut='COMMUN_IDENTIQUE' THEN 1 ELSE 0 END,
                     ABS(ecart_remuneration) DESC,nom_a,nom_b"""
        return query, params

    def export(self, comparison_id: str, path: str) -> str:
        summary = self.get_summary(comparison_id)
        target = Path(path)
        if target.suffix.lower() != ".xlsx":
            target = target.with_suffix(".xlsx")
        target.parent.mkdir(parents=True, exist_ok=True)

        book = Workbook(write_only=True)
        ws = book.create_sheet("Synthèse")
        ws.append(["Indicateur", "Valeur"])
        for row in [
            ("Comparaison", f"{summary['regime_a']} vs {summary['regime_b']}"),
            ("Période", f"{summary['quarter']} {summary['year']}"),
            ("Lignes régime A", summary["rows_a"]),
            ("Lignes régime B", summary["rows_b"]),
            ("Identités exactes communes", summary["common"]),
            ("Uniquement régime A", summary["only_a"]),
            ("Uniquement régime B", summary["only_b"]),
            ("Double paiement potentiel — identité exacte", summary["double"]),
            ("Écarts financiers sur identités fiables", summary["financial"]),
            ("Écarts administratifs sur identités fiables", summary["administrative"]),
            ("Masse régime A", summary["mass_a"]),
            ("Masse régime B", summary["mass_b"]),
            ("Écart de masse", (summary["mass_a"] or 0) - (summary["mass_b"] or 0)),
            ("Règle stricte", "Commun certain = même matricule normalisé ET même nom normalisé ; aucun candidat ambigu n'est choisi arbitrairement"),
        ]:
            ws.append(list(row))

        sheets = [("Tous les résultats", "")]
        labels = {
            "COMMUN_IDENTIQUE": "Communs identiques",
            "COMMUN_PAR_NOM_PROBABLE": "Nom probable",
            "ECART_FINANCIER": "Écarts financiers",
            "ECART_ADMINISTRATIF": "Écarts administratifs",
            "ECART_FINANCIER_ET_ADMIN": "Écarts fin+admin",
            "PAIEMENT_MULTIPLE": "Paiements multiples",
            "DOUBLE_PAIEMENT_POTENTIEL": "Double paiement potentiel",
            "IDENTITE_INCOHERENTE": "Identités incohérentes",
            "NOM_MATRICULE_DIFFERENT": "Nom matricule différent",
            "MATCH_AMBIGU_MATRICULE": "Ambigu matricule",
            "MATCH_AMBIGU_NOM": "Ambigu nom",
            "UNIQUEMENT_REGIME_A": "Uniquement A",
            "UNIQUEMENT_REGIME_B": "Uniquement B",
        }
        sheets.extend((labels.get(status, status), status) for status in self.STATUSES)

        with self.db.connect() as con:
            for title, status in sheets:
                query, extra = self._export_query(status)
                append_query_sheets(book, con, query, [comparison_id] + extra,
                                    headers=self.HEADERS, sheet_name=title)

        atomic_save_workbook(book, target)
        with self.db.connect() as con:
            con.execute("UPDATE comparaisons_regimes SET fichier_export=? WHERE comparaison_id=?",
                        [str(target), comparison_id])
        return str(target)
