from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Font

from .export_streaming import atomic_save_workbook
from .spreadsheet_utils import sanitize_excel_row


DETAIL_HEADERS = [
    "ID Ligne Base", "Regime Source", "Institution Source", "Matricule Source",
    "Nom Brut en Base", "Prenom Brut", "Nom Normalise", "Matricule Normalise",
    "Cle de Matching", "Statut Agent", "Date Affiliation", "Table Source",
    "Execution ID", "Ligne Source", "Section", "Categorie", "Grade",
    "Unite d'affectation", "Province", "Remuneration Brute", "Montant Net",
]

SUMMARY_HEADERS = [
    "Cle / Valeur", "Nombre de Regimes Impactes", "Nombre d'Occurrences",
    "Liste des Regimes", "Action / Detail",
]

GLOBAL_HEADERS = [
    "Rubrique / Cle de Matching", "Nombre d'Agents Uniques",
    "Nombre Total d'Occurrences", "Regimes Impactes", "Lien Direct",
]


def normalize_name_python(value: str | None) -> str:
    """Nom canonique: majuscules, sans accents/ponctuation, mots tries alphabetiquement."""
    text = unicodedata.normalize("NFKD", str(value or "").upper())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    words = re.findall(r"[A-Z0-9]+", text)
    words = [word for word in words if word]
    return "".join(sorted(words))


def normalize_matricule_python(value: str | None) -> str:
    """Matricule canonique: alphanumerique uniquement et zeros initiaux retires."""
    text = re.sub(r"[^A-Z0-9]", "", str(value or "").upper())
    if not text:
        return ""
    # Retire les zeros de tete sans perdre une valeur entierement composee de zeros.
    stripped = text.lstrip("0")
    return stripped or "0"


class DrillDownAnnex12Exporter:
    """Annexe 12 a 7 feuilles, limitee aux correspondances presentes dans >= 2 regimes."""

    SHEETS = {
        "global": "Synthese Globale",
        "nom_summary": "Synthese_Nom",
        "mat_summary": "Synthese_Matricule",
        "combo_summary": "Synthese_Matricule_Nom",
        "nom_detail": "Detail_Nom",
        "mat_detail": "Detail_Matricule",
        "combo_detail": "Detail_Matricule_Nom",
    }

    def __init__(self, db):
        self.db = db

    @staticmethod
    def _name_sql(alias: str = "p") -> str:
        # DuckDB: tokenise le nom nettoye, trie les mots puis les concatene.
        # regexp_split_to_array + list_sort reste compact car il travaille ligne par ligne.
        return f"""array_to_string(list_sort(regexp_split_to_array(
            trim(regexp_replace(upper(strip_accents(coalesce({alias}.nom,'')) || ' ' ||
                 strip_accents(coalesce({alias}.prenom,''))), '[^A-Z0-9]+', ' ', 'g')),
            '\\s+')), '')"""

    @staticmethod
    def _mat_sql(alias: str = "p") -> str:
        return f"""CASE
            WHEN regexp_replace(upper(coalesce({alias}.matricule_source,'')), '[^A-Z0-9]', '', 'g')='' THEN ''
            ELSE coalesce(nullif(ltrim(regexp_replace(upper(coalesce({alias}.matricule_source,'')), '[^A-Z0-9]', '', 'g'),'0'),''),'0')
        END"""

    def _prepare(self, con, fusion_id: str) -> tuple[str, int]:
        con.execute("SET threads=1")
        con.execute("SET preserve_insertion_order=false")
        row = con.execute("SELECT trimestre,annee FROM fusions_raw WHERE fusion_id=?", [fusion_id]).fetchone()
        if not row:
            raise ValueError(f"Fusion introuvable : {fusion_id}")
        quarter, year = row[0], int(row[1])

        con.execute("DROP TABLE IF EXISTS tmp_ann12_scope")
        con.execute("DROP TABLE IF EXISTS tmp_ann12_nom_keys")
        con.execute("DROP TABLE IF EXISTS tmp_ann12_mat_keys")
        con.execute("DROP TABLE IF EXISTS tmp_ann12_combo_keys")

        name_key = self._name_sql("p")
        mat_key = self._mat_sql("p")
        con.execute(f"""CREATE TEMP TABLE tmp_ann12_scope AS
            SELECT p.ligne_paie_id,p.execution_id,p.institution_id,p.regime,p.table_source,
                   p.matricule_source,p.nom,p.prenom,p.ligne_source,p.section,p.categorie,p.grade,
                   p.unite_affectation,p.province,p.remuneration_brute_calculee,p.montant_net,
                   {name_key} AS nom_cle,
                   {mat_key} AS matricule_cle,
                   CASE WHEN ({mat_key})<>'' AND ({name_key})<>''
                        THEN ({mat_key}) || '|' || ({name_key}) ELSE '' END AS combo_cle
            FROM paie_standardisee p
            WHERE p.trimestre=? AND p.annee=?
              AND p.execution_id IN (
                SELECT DISTINCT execution_id FROM sources_fusion_raw
                WHERE fusion_id=? AND execution_id IS NOT NULL
              )""", [quarter, year, fusion_id])

        # Seules les cles observees dans au moins deux regimes sont retenues.
        con.execute("""CREATE TEMP TABLE tmp_ann12_nom_keys AS
            SELECT nom_cle AS cle,COUNT(DISTINCT regime) nb_regimes,COUNT(*) occurrences,
                   string_agg(DISTINCT regime, ' | ' ORDER BY regime) regimes
            FROM tmp_ann12_scope WHERE nom_cle<>'' GROUP BY nom_cle
            HAVING COUNT(DISTINCT regime)>=2""")
        con.execute("""CREATE TEMP TABLE tmp_ann12_mat_keys AS
            SELECT matricule_cle AS cle,COUNT(DISTINCT regime) nb_regimes,COUNT(*) occurrences,
                   string_agg(DISTINCT regime, ' | ' ORDER BY regime) regimes
            FROM tmp_ann12_scope WHERE matricule_cle<>'' GROUP BY matricule_cle
            HAVING COUNT(DISTINCT regime)>=2""")
        con.execute("""CREATE TEMP TABLE tmp_ann12_combo_keys AS
            SELECT combo_cle AS cle,COUNT(DISTINCT regime) nb_regimes,COUNT(*) occurrences,
                   string_agg(DISTINCT regime, ' | ' ORDER BY regime) regimes
            FROM tmp_ann12_scope WHERE combo_cle<>'' GROUP BY combo_cle
            HAVING COUNT(DISTINCT regime)>=2""")
        return quarter, year

    @staticmethod
    def _cleanup(con):
        for table in ("tmp_ann12_combo_keys", "tmp_ann12_mat_keys", "tmp_ann12_nom_keys", "tmp_ann12_scope"):
            try:
                con.execute(f"DROP TABLE IF EXISTS {table}")
            except Exception:
                pass

    @staticmethod
    def _hyperlink_cell(sheet_name: str, row: int, label: str):
        cell = WriteOnlyCell(None, value=label)
        cell.hyperlink = f"#'{sheet_name}'!A{row}"
        cell.font = Font(color="0563C1", underline="single")
        return cell

    @staticmethod
    def _back_cell(target_sheet: str):
        cell = WriteOnlyCell(None, value="< Retour")
        cell.hyperlink = f"#'{target_sheet}'!A1"
        cell.font = Font(color="0563C1", underline="single", bold=True)
        return cell

    def _detail_rows_for_key(self, con, key_column: str, key: str):
        return con.execute(f"""SELECT ligne_paie_id,regime,institution_id,matricule_source,nom,prenom,
            nom_cle,matricule_cle,{key_column},'' AS statut_agent,NULL AS date_affiliation,
            table_source,execution_id,ligne_source,section,categorie,grade,unite_affectation,
            province,remuneration_brute_calculee,montant_net
            FROM tmp_ann12_scope WHERE {key_column}=?
            ORDER BY regime,execution_id,ligne_source,ligne_paie_id""", [key])

    def _build_detail_sheet(self, book, con, sheet_name: str, key_table: str, key_column: str, progress=None):
        ws = book.create_sheet(sheet_name)
        ws.append([self._back_cell(self.SHEETS["global"])] + [""] * (len(DETAIL_HEADERS)-1))
        ws.append(list(sanitize_excel_row(DETAIL_HEADERS)))
        starts: dict[str, int] = {}
        current_row = 3
        keys = con.execute(f"SELECT cle,occurrences FROM {key_table} ORDER BY cle").fetchall()
        total = max(1, len(keys))
        for idx, (key, _occ) in enumerate(keys, 1):
            starts[str(key)] = current_row
            cursor = self._detail_rows_for_key(con, key_column, str(key))
            while True:
                rows = cursor.fetchmany(1000)
                if not rows:
                    break
                for row in rows:
                    ws.append(list(sanitize_excel_row(row)))
                    current_row += 1
            if progress and idx % 100 == 0:
                progress(98, f"Annexe 12 : {sheet_name} {idx}/{total}")
        return starts, current_row - 3

    def _build_summary_sheet(self, book, con, sheet_name: str, key_table: str, detail_sheet: str, starts: dict[str, int]):
        ws = book.create_sheet(sheet_name)
        ws.append([self._back_cell(self.SHEETS["global"]), "", "", "", ""])
        ws.append(list(sanitize_excel_row(SUMMARY_HEADERS)))
        for key, nb_regimes, occurrences, regimes in con.execute(
            f"SELECT cle,nb_regimes,occurrences,regimes FROM {key_table} ORDER BY occurrences DESC,cle"
        ).fetchall():
            target = starts.get(str(key), 3)
            occ_cell = self._hyperlink_cell(detail_sheet, target, str(int(occurrences or 0)))
            action = self._hyperlink_cell(detail_sheet, target, "Voir les lignes")
            ws.append([key, int(nb_regimes or 0), occ_cell, regimes or "", action])

    def _global_metrics(self, con):
        specs = [
            ("Matching par Nom Normalise", "tmp_ann12_nom_keys", self.SHEETS["nom_summary"]),
            ("Matching par Matricule", "tmp_ann12_mat_keys", self.SHEETS["mat_summary"]),
            ("Matching par Matricule + Nom", "tmp_ann12_combo_keys", self.SHEETS["combo_summary"]),
        ]
        result = []
        for label, table, target_sheet in specs:
            row = con.execute(f"""SELECT COUNT(*) agents,COALESCE(SUM(occurrences),0) occ,
                COALESCE(string_agg(DISTINCT s.regime,' | ' ORDER BY s.regime),'') regimes
                FROM {table} k LEFT JOIN tmp_ann12_scope s
                  ON (CASE WHEN '{table}'='tmp_ann12_nom_keys' THEN s.nom_cle
                           WHEN '{table}'='tmp_ann12_mat_keys' THEN s.matricule_cle
                           ELSE s.combo_cle END)=k.cle""").fetchone()
            result.append((label, int(row[0] or 0), int(row[1] or 0), row[2] or "", target_sheet))
        return result

    def export(self, fusion_id: str, folder: str | Path, progress=None) -> Path:
        target = Path(folder) / "12_matching_multi_regimes_drilldown.xlsx"
        book = Workbook(write_only=True)
        # Creer les feuilles dans l'ordre final exige par le cahier des charges.
        global_ws = book.create_sheet(self.SHEETS["global"])
        nom_summary_ws = book.create_sheet(self.SHEETS["nom_summary"])
        mat_summary_ws = book.create_sheet(self.SHEETS["mat_summary"])
        combo_summary_ws = book.create_sheet(self.SHEETS["combo_summary"])
        nom_detail_ws = book.create_sheet(self.SHEETS["nom_detail"])
        mat_detail_ws = book.create_sheet(self.SHEETS["mat_detail"])
        combo_detail_ws = book.create_sheet(self.SHEETS["combo_detail"])
        # Les feuilles sont recreees proprement plus bas; supprimer les placeholders write-only est impossible.
        # On ferme donc ce classeur logique et construit le classeur final dans l'ordre ci-dessous.
        del global_ws, nom_summary_ws, mat_summary_ws, combo_summary_ws, nom_detail_ws, mat_detail_ws, combo_detail_ws
        book = Workbook(write_only=True)

        with self.db.connect() as con:
            self._prepare(con, fusion_id)
            try:
                progress and progress(97, "Annexe 12 : preparation des details multi-regimes")
                # Pour conserver exactement l'ordre des 7 feuilles, on calcule d'abord les positions,
                # puis on recree le classeur et on ecrit les syntheses avec les liens connus.
                # Un mini-classeur temporaire permet de calculer les ancres sans garder les donnees en RAM.
                temp_book = Workbook(write_only=True)
                nom_starts, nom_rows = self._build_detail_sheet(temp_book, con, self.SHEETS["nom_detail"], "tmp_ann12_nom_keys", "nom_cle")
                mat_starts, mat_rows = self._build_detail_sheet(temp_book, con, self.SHEETS["mat_detail"], "tmp_ann12_mat_keys", "matricule_cle")
                combo_starts, combo_rows = self._build_detail_sheet(temp_book, con, self.SHEETS["combo_detail"], "tmp_ann12_combo_keys", "combo_cle")
                # Refaire directement le classeur final; les requetes sont partitionnees par cle, donc memoire bornee.
                book = Workbook(write_only=True)
                global_ws = book.create_sheet(self.SHEETS["global"])
                global_ws.append(list(sanitize_excel_row(GLOBAL_HEADERS)))
                for label, agents, occ, regimes, target_sheet in self._global_metrics(con):
                    global_ws.append([label, agents, occ, regimes, self._hyperlink_cell(target_sheet, 1, "Ouvrir")])

                self._build_summary_sheet(book, con, self.SHEETS["nom_summary"], "tmp_ann12_nom_keys", self.SHEETS["nom_detail"], nom_starts)
                self._build_summary_sheet(book, con, self.SHEETS["mat_summary"], "tmp_ann12_mat_keys", self.SHEETS["mat_detail"], mat_starts)
                self._build_summary_sheet(book, con, self.SHEETS["combo_summary"], "tmp_ann12_combo_keys", self.SHEETS["combo_detail"], combo_starts)
                self._build_detail_sheet(book, con, self.SHEETS["nom_detail"], "tmp_ann12_nom_keys", "nom_cle", progress)
                self._build_detail_sheet(book, con, self.SHEETS["mat_detail"], "tmp_ann12_mat_keys", "matricule_cle", progress)
                self._build_detail_sheet(book, con, self.SHEETS["combo_detail"], "tmp_ann12_combo_keys", "combo_cle", progress)
            finally:
                self._cleanup(con)

        atomic_save_workbook(book, target)
        progress and progress(99, f"Annexe 12 generee : {target.name}")
        return target
