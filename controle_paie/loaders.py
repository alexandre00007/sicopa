from __future__ import annotations

import re
import io
import platform
import shutil
import struct
import subprocess
import uuid
from pathlib import Path
from typing import Callable, Dict, Optional

import pandas as pd

from .config import AppConfig
from .database import Database
from .standardization import infer_declaration_mapping, standardize_declaration, standardize_payroll

Progress = Optional[Callable[[int, str], None]]

DECLARATION_STANDARD_FIELDS = (
    ("matricule_source", "Texte", "Identifiant prioritaire pour le rapprochement"),
    ("nom", "Texte", "Nom ou nom complet de l’agent"),
    ("prenom", "Texte", "Prénom séparé, si disponible"),
    ("grade", "Texte", "Grade administratif"),
    ("service", "Texte", "Service ou direction"),
    ("unite_affectation", "Texte", "Unité ou lieu d’affectation"),
    ("province", "Texte", "Province d’affectation"),
    ("remuneration_declaree", "Montant", "Rémunération portée sur la liste déclarative"),
    ("statut_agent", "Texte", "Statut ou situation administrative"),
)
DECLARATION_MATCHING_REQUIRED_FIELDS = {
    "matricule_source": "Matricule",
    "nom": "Nom / noms de l’agent",
}


def _validate_access_file(path: str) -> None:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"Fichier Access introuvable : {path}")
    if source.suffix.lower() not in {".mdb", ".accdb"}:
        raise ValueError("Le fichier sélectionné doit avoir l’extension .mdb ou .accdb")


def _validate_excel_file(path: str) -> None:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"Fichier Excel introuvable : {path}")
    if source.suffix.lower() not in {".xlsx", ".xls", ".xlsm"}:
        raise ValueError("Le déclaratif doit être un fichier Excel .xlsx, .xls ou .xlsm.")


def select_access_driver(drivers: list[str], requested: str, source_suffix: str = ".accdb") -> str:
    """Select an installed Access driver before ODBC can raise the opaque IM002 error."""
    exact = next((driver for driver in drivers if driver.casefold() == requested.casefold()), None)
    if exact:
        return exact
    candidates = [driver for driver in drivers
                  if "access" in driver.casefold() and "mdb" in driver.casefold()]
    if source_suffix.casefold() == ".accdb":
        candidates = [driver for driver in candidates if "accdb" in driver.casefold()]
    if candidates:
        return candidates[-1]
    bits = struct.calcsize("P") * 8
    detected = ", ".join(drivers) if drivers else "aucun pilote ODBC"
    raise RuntimeError(
        "Pilote ODBC Microsoft Access introuvable (IM002 évitée). "
        f"SICORPA fonctionne en {bits} bits : installez Microsoft Access Database Engine {bits} bits, "
        f"puis redémarrez l’application. Pilotes détectés : {detected}."
    )


def _windows_access_connection(path: str, requested_driver: str):
    try:
        import pyodbc
    except ImportError as exc:
        raise RuntimeError("Le composant pyodbc manque dans SICORPA; réinstallez l’application.") from exc
    driver = select_access_driver(list(pyodbc.drivers()), requested_driver, Path(path).suffix)
    try:
        return pyodbc.connect(f"Driver={{{driver}}};DBQ={path};")
    except Exception as exc:
        message = str(exc).lower()
        if "im002" in message or "sqldriverconnect" in message or "source de données introuvable" in message:
            bits = struct.calcsize("P") * 8
            raise RuntimeError(
                "Connexion Access impossible : le pilote ODBC n’est pas correctement enregistré "
                f"pour SICORPA {bits} bits (IM002). Réparez ou installez Microsoft Access Database "
                f"Engine {bits} bits, puis redémarrez Windows. Pilote demandé : {driver}."
            ) from exc
        raise


def _require_mdbtools() -> None:
    if any(shutil.which(command) is None for command in ("mdb-tables", "mdb-export")):
        raise RuntimeError("Lecture Access indisponible sous Linux. Installez mdbtools : sudo apt-get update && sudo apt-get install -y mdbtools, puis redémarrez l’application.")


def list_access_tables(path: str, driver: str) -> list[str]:
    _validate_access_file(path)
    if platform.system() == "Windows":
        with _windows_access_connection(path, driver) as con:
            return sorted({row.table_name for row in con.cursor().tables(tableType="TABLE")})
    _require_mdbtools()
    result = subprocess.run(["mdb-tables", "-1", path], check=True, capture_output=True, text=True)
    return sorted(line.strip() for line in result.stdout.splitlines() if line.strip())


def read_access_table(path: str, table: str, driver: str) -> pd.DataFrame:
    _validate_access_file(path)
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table):
        raise ValueError("Nom de table Access invalide")
    if platform.system() == "Windows":
        with _windows_access_connection(path, driver) as con:
            return pd.read_sql(f"SELECT * FROM [{table}]", con)
    _require_mdbtools()
    result = subprocess.run(["mdb-export", path, table], check=True, capture_output=True,
                            text=True, encoding="utf-8", errors="replace")
    return pd.read_csv(io.StringIO(result.stdout), dtype=object, keep_default_na=False)

def excel_sheets(path: str) -> list[str]:
    _validate_excel_file(path)
    return pd.ExcelFile(path).sheet_names


def preview_excel(path: str, sheet: str, header_row: int = 1, rows: int = 20) -> pd.DataFrame:
    _validate_excel_file(path)
    if int(header_row) < 1:
        raise ValueError("La ligne d’en-tête doit être supérieure ou égale à 1.")
    return pd.read_excel(path, sheet_name=sheet, header=max(header_row - 1, 0), nrows=rows)


def describe_declaration_structure(columns, explicit_mapping: Optional[Dict[str, str]] = None,
                                   required_sources: Optional[list[str]] = None) -> dict:
    source_columns = [str(column) for column in columns]
    mapping = infer_declaration_mapping(source_columns, explicit_mapping)
    required_sources = list(required_sources or [])
    missing_required = [column for column in required_sources if column not in source_columns]
    sources_by_target = {target: source for source, target in mapping.items() if source in source_columns}
    configured_required_targets = {
        (explicit_mapping or {}).get(source) for source in required_sources
        if (explicit_mapping or {}).get(source)
    }
    required_targets = set(DECLARATION_MATCHING_REQUIRED_FIELDS) | configured_required_targets
    rows = []
    for field, data_type, description in DECLARATION_STANDARD_FIELDS:
        source = sources_by_target.get(field, "")
        configured_required = field in required_targets
        if source:
            status = "✓ Obligatoire présent" if configured_required else "✓ Présent"
        elif configured_required:
            status = "✗ Obligatoire manquant"
        else:
            status = "Optionnel"
        rows.append((field, data_type, source, status, description))
    issues = []
    if missing_required:
        issues.append("colonnes obligatoires absentes : " + ", ".join(missing_required))
    missing_matching = [DECLARATION_MATCHING_REQUIRED_FIELDS[field]
                        for field in DECLARATION_MATCHING_REQUIRED_FIELDS
                        if field not in sources_by_target]
    if missing_matching:
        issues.append("champs obligatoires pour le rapprochement non reconnus : " +
                      ", ".join(missing_matching))
    unmapped = [column for column in source_columns if column not in mapping]
    return {"columns": source_columns, "mapping": mapping, "rows": rows,
            "issues": issues, "unmapped": unmapped,
            "missing_matching": missing_matching, "ready": not issues}


class IngestionService:
    def __init__(self, database: Database, config: AppConfig):
        self.db, self.config = database, config

    def inspect_declaration_structure(self, path: str, sheet: str, header_row: int,
                                      regime: str) -> dict:
        _validate_excel_file(path)
        if not sheet.strip():
            raise ValueError("Sélectionnez la feuille du déclaratif.")
        if int(header_row) < 1:
            raise ValueError("La ligne d’en-tête doit être supérieure ou égale à 1.")
        header = pd.read_excel(path, sheet_name=sheet, header=int(header_row)-1, nrows=0)
        return describe_declaration_structure(
            header.columns,
            self.db.get_column_mapping(regime, "EXCEL"),
            self.db.required_source_columns(regime, "EXCEL"),
        )

    def load_access(self, path: str, table: str, institution_id: str, regime: str,
                    quarter: str, year: int, mode: str = "append", mapping: Optional[Dict[str, str]] = None,
                    progress: Progress = None) -> str:
        execution_id = str(uuid.uuid4())
        progress and progress(-1, f"Ouverture du fichier Access : {Path(path).name}")
        raw = read_access_table(path, table, self.config.access_driver)
        raw_count=len(raw)
        progress and progress(30, f"Table {table} lue : {raw_count:,} lignes".replace(","," "))
        metadata = dict(execution_id=execution_id, institution_id=institution_id, regime=regime,
                        trimestre=quarter, annee=year, table_source=table)
        mapping = mapping if mapping is not None else self.db.get_column_mapping(regime, "ACCESS")
        missing_required = [column for column in self.db.required_source_columns(regime, "ACCESS") if column not in raw.columns]
        if missing_required: raise ValueError(f"Colonnes Access obligatoires absentes : {', '.join(missing_required)}")
        progress and progress(-1, "Standardisation et validation des colonnes Access")
        standard = standardize_payroll(raw, metadata, mapping)
        destination = self.config.regimes[regime].raw_table
        progress and progress(55, f"{len(standard):,} lignes standardisées — préparation de DuckDB".replace(","," "))
        with self.db.connect() as con:
            con.execute("BEGIN")
            try:
                if mode == "replace_period":
                    con.execute("DELETE FROM paie_standardisee WHERE regime=? AND trimestre=? AND annee=? AND institution_id=?", [regime, quarter, year, institution_id])
                con.register("raw_frame", raw)
                con.execute(f'CREATE TABLE IF NOT EXISTS "{destination}" AS SELECT *, ?::VARCHAR execution_id, ?::VARCHAR trimestre, ?::INTEGER annee FROM raw_frame WHERE FALSE', [execution_id, quarter, year])
                con.execute(f'INSERT INTO "{destination}" SELECT *, ?, ?, ? FROM raw_frame', [execution_id, quarter, year])
                con.unregister("raw_frame");del raw
                progress and progress(75, f"Données brutes écrites dans {destination}")
                con.register("standard_frame", standard)
                con.execute("INSERT INTO paie_standardisee BY NAME SELECT * FROM standard_frame")
                progress and progress(90, "Données standardisées écrites — finalisation du journal")
                con.execute("INSERT INTO journal_executions (execution_id,type_operation,fichier_source,table_source,table_destination,institution_id,regime,trimestre,annee,mode_chargement,lignes_lues,lignes_chargees,statut,date_fin) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)", [execution_id,"IMPORT_ACCESS",str(path),table,destination,institution_id,regime,quarter,year,mode,raw_count,len(standard),"TERMINE"])
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                con.execute(f'DELETE FROM "{destination}" WHERE execution_id=?', [execution_id])
                con.execute("DELETE FROM paie_standardisee WHERE execution_id=?", [execution_id])
                con.execute("DELETE FROM journal_executions WHERE execution_id=?", [execution_id])
                raise
        progress and progress(100, f"Table Access chargée : {len(standard):,} lignes".replace(","," "))
        return execution_id

    def load_excel(self, path: str, sheet: str, header_row: int, institution_id: str,
                   regime: str, quarter: str, year: int, mode: str = "append",
                   mapping: Optional[Dict[str, str]] = None, progress: Progress = None) -> str:
        _validate_excel_file(path)
        execution_id = str(uuid.uuid4())
        progress and progress(-1, f"Ouverture du déclaratif : {Path(path).name}")
        raw = pd.read_excel(path, sheet_name=sheet, header=max(header_row - 1, 0))
        raw_count=len(raw)
        if not raw_count:
            raise ValueError("La feuille déclarative ne contient aucune ligne de données.")
        progress and progress(25, f"Feuille {sheet} lue : {raw_count:,} lignes".replace(",", " "))
        metadata = dict(execution_id=execution_id, institution_id=institution_id, regime=regime,
                        trimestre=quarter, annee=year, fichier_source=str(path), feuille_source=sheet)
        mapping = mapping if mapping is not None else self.db.get_column_mapping(regime, "EXCEL")
        required = self.db.required_source_columns(regime, "EXCEL")
        structure = describe_declaration_structure(raw.columns, mapping, required)
        if structure["issues"]:
            raise ValueError("Structure déclarative incompatible : " + "; ".join(structure["issues"]) +
                             ". Consultez Structure d’importation ou Mapping colonnes.")
        progress and progress(-1, "Standardisation et contrôle des identifiants déclaratifs")
        resolved_mapping = structure["mapping"]
        schema_rows = [(execution_id, "EXCEL", sheet, str(column), str(dtype),
                        resolved_mapping.get(str(column)), str(column) in required)
                       for column, dtype in raw.dtypes.items()]
        standard = standardize_declaration(raw, metadata, resolved_mapping)
        usable_matricules=(~standard["matricule_normalise"].isin(["","NU"])).sum()
        usable_names=(standard["nom_normalise"]!="").sum()
        empty_fields=[]
        if not usable_matricules:empty_fields.append("Matricule")
        if not usable_names:empty_fields.append("Nom / noms de l’agent")
        if empty_fields:
            raise ValueError("Champs déclaratifs sans aucune valeur exploitable : " +
                             ", ".join(empty_fields) +
                             ". Corrigez les données avant le rapprochement.")
        missing_matricules=int(standard["matricule_normalise"].isin(["","NU"]).sum())
        missing_names=int((standard["nom_normalise"]=="").sum())
        del raw
        progress and progress(55,(f"{len(standard):,} lignes standardisées — "
            f"{missing_matricules:,} sans matricule exploitable, {missing_names:,} sans nom — "
            "préparation de DuckDB").replace(",", " "))
        with self.db.connect() as con:
            con.execute("BEGIN")
            try:
                if mode == "replace_period":
                    matching_refs=con.execute("""SELECT COUNT(DISTINCT r.execution_id)
                        FROM resultats_rapprochement r JOIN declaratif_standardise d
                          ON d.ligne_declaratif_id=r.ligne_declaratif_id
                        WHERE d.regime=? AND d.trimestre=? AND d.annee=? AND d.institution_id=?""",
                        [regime,quarter,year,institution_id]).fetchone()[0]
                    campaign_refs=con.execute("""SELECT COUNT(*) FROM campagnes_analyse_multi
                        WHERE regime_declaratif=? AND trimestre=? AND annee=?
                          AND institution_declarative_id=?""",
                        [regime,quarter,year,institution_id]).fetchone()[0]
                    if matching_refs or campaign_refs:
                        raise ValueError("Remplacement bloqué : le déclaratif actuel est déjà utilisé par "
                                         f"{matching_refs} rapprochement(s) et {campaign_refs} campagne(s) multi-régimes. "
                                         "Ajoutez une nouvelle version afin de conserver la traçabilité.")
                    con.execute("DELETE FROM declaratif_standardise WHERE regime=? AND trimestre=? AND annee=? AND institution_id=?", [regime, quarter, year, institution_id])
                if schema_rows:
                    con.executemany("INSERT INTO schemas_sources VALUES (?,?,?,?,?,?,?)", schema_rows)
                con.register("standard_frame", standard)
                con.execute("INSERT INTO declaratif_standardise BY NAME SELECT * FROM standard_frame")
                progress and progress(85, "Déclaratif écrit dans DuckDB — finalisation du journal")
                con.execute("INSERT INTO journal_executions (execution_id,type_operation,fichier_source,table_source,table_destination,institution_id,regime,trimestre,annee,mode_chargement,lignes_lues,lignes_chargees,statut,date_fin) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)", [execution_id,"IMPORT_EXCEL",str(path),sheet,"declaratif_standardise",institution_id,regime,quarter,year,mode,raw_count,len(standard),"TERMINE"])
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
        progress and progress(100, f"Déclaratif chargé : {len(standard):,} lignes".replace(",", " "))
        return execution_id

    def load_payroll_excel(self, path: str, sheet: str, header_row: int, institution_id: str,
                           regime: str, quarter: str, year: int, mode: str = "append",
                           mapping: Optional[Dict[str, str]] = None, progress: Progress = None) -> str:
        """Charge un listing de paie Excel dans le schéma analytique de la paie."""
        execution_id = str(uuid.uuid4())
        progress and progress(-1, f"Ouverture du listing Excel : {Path(path).name}")
        raw = pd.read_excel(path, sheet_name=sheet, header=max(header_row - 1, 0))
        raw_count=len(raw)
        progress and progress(30, f"Feuille {sheet} lue : {raw_count:,} lignes".replace(",", " "))
        metadata = dict(execution_id=execution_id, institution_id=institution_id, regime=regime,
                        trimestre=quarter, annee=year, table_source=f"{Path(path).name} — {sheet}")
        mapping = mapping if mapping is not None else self.db.get_column_mapping(regime, "PAIE_EXCEL")
        missing_required = [column for column in self.db.required_source_columns(regime, "PAIE_EXCEL") if column not in raw.columns]
        if missing_required:
            raise ValueError(f"Colonnes obligatoires du listing Excel absentes : {chr(44).join(missing_required)}")
        progress and progress(-1, "Standardisation et validation des colonnes du listing")
        standard = standardize_payroll(raw, metadata, mapping)
        del raw
        progress and progress(60, f"{len(standard):,} lignes standardisées — préparation de DuckDB".replace(",", " "))
        with self.db.connect() as con:
            con.execute("BEGIN")
            try:
                if mode == "replace_period":
                    con.execute("DELETE FROM paie_standardisee WHERE regime=? AND trimestre=? AND annee=? AND institution_id=?", [regime, quarter, year, institution_id])
                con.register("standard_frame", standard)
                con.execute("INSERT INTO paie_standardisee BY NAME SELECT * FROM standard_frame")
                progress and progress(90, "Listing standardisé écrit — finalisation du journal")
                con.execute("INSERT INTO journal_executions (execution_id,type_operation,fichier_source,table_source,table_destination,institution_id,regime,trimestre,annee,mode_chargement,lignes_lues,lignes_chargees,statut,date_fin) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)", [execution_id,"IMPORT_PAIE_EXCEL",str(path),sheet,"paie_standardisee",institution_id,regime,quarter,year,mode,raw_count,len(standard),"TERMINE"])
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
        progress and progress(100, f"Listing Excel chargé : {len(standard):,} lignes".replace(",", " "))
        return execution_id
