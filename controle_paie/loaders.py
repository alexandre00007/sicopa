from __future__ import annotations

import re
import io
import platform
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Callable, Dict, Optional

import pandas as pd

from .config import AppConfig
from .database import Database
from .standardization import standardize_declaration, standardize_payroll

Progress = Optional[Callable[[int, str], None]]


def _validate_access_file(path: str) -> None:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"Fichier Access introuvable : {path}")
    if source.suffix.lower() not in {".mdb", ".accdb"}:
        raise ValueError("Le fichier sélectionné doit avoir l’extension .mdb ou .accdb")


def _require_mdbtools() -> None:
    if any(shutil.which(command) is None for command in ("mdb-tables", "mdb-export")):
        raise RuntimeError("Lecture Access indisponible sous Linux. Installez mdbtools : sudo apt-get update && sudo apt-get install -y mdbtools, puis redémarrez l’application.")


def list_access_tables(path: str, driver: str) -> list[str]:
    _validate_access_file(path)
    if platform.system() == "Windows":
        try:
            import pyodbc
        except ImportError as exc:
            raise RuntimeError("Installez pyodbc avec : python -m pip install pyodbc") from exc
        with pyodbc.connect(f"Driver={{{driver}}};DBQ={path};") as con:
            return sorted({row.table_name for row in con.cursor().tables(tableType="TABLE")})
    _require_mdbtools()
    result = subprocess.run(["mdb-tables", "-1", path], check=True, capture_output=True, text=True)
    return sorted(line.strip() for line in result.stdout.splitlines() if line.strip())


def read_access_table(path: str, table: str, driver: str) -> pd.DataFrame:
    _validate_access_file(path)
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table):
        raise ValueError("Nom de table Access invalide")
    if platform.system() == "Windows":
        try:
            import pyodbc
        except ImportError as exc:
            raise RuntimeError("Installez pyodbc avec : python -m pip install pyodbc") from exc
        with pyodbc.connect(f"Driver={{{driver}}};DBQ={path};") as con:
            return pd.read_sql(f"SELECT * FROM [{table}]", con)
    _require_mdbtools()
    result = subprocess.run(["mdb-export", path, table], check=True, capture_output=True,
                            text=True, encoding="utf-8", errors="replace")
    return pd.read_csv(io.StringIO(result.stdout), dtype=object, keep_default_na=False)

def excel_sheets(path: str) -> list[str]:
    return pd.ExcelFile(path).sheet_names


def preview_excel(path: str, sheet: str, header_row: int = 1, rows: int = 20) -> pd.DataFrame:
    return pd.read_excel(path, sheet_name=sheet, header=max(header_row - 1, 0), nrows=rows)


class IngestionService:
    def __init__(self, database: Database, config: AppConfig):
        self.db, self.config = database, config

    def load_access(self, path: str, table: str, institution_id: str, regime: str,
                    quarter: str, year: int, mode: str = "append", mapping: Optional[Dict[str, str]] = None,
                    progress: Progress = None) -> str:
        execution_id = str(uuid.uuid4())
        progress and progress(5, "Lecture de la table Access")
        raw = read_access_table(path, table, self.config.access_driver)
        metadata = dict(execution_id=execution_id, institution_id=institution_id, regime=regime,
                        trimestre=quarter, annee=year, table_source=table)
        mapping = mapping if mapping is not None else self.db.get_column_mapping(regime, "ACCESS")
        missing_required = [column for column in self.db.required_source_columns(regime, "ACCESS") if column not in raw.columns]
        if missing_required: raise ValueError(f"Colonnes Access obligatoires absentes : {', '.join(missing_required)}")
        standard = standardize_payroll(raw, metadata, mapping)
        destination = self.config.regimes[regime].raw_table
        progress and progress(45, "Chargement dans DuckDB")
        with self.db.connect() as con:
            con.execute("BEGIN")
            try:
                if mode == "replace_period":
                    con.execute("DELETE FROM paie_standardisee WHERE regime=? AND trimestre=? AND annee=? AND institution_id=?", [regime, quarter, year, institution_id])
                con.register("raw_frame", raw)
                con.execute(f'CREATE TABLE IF NOT EXISTS "{destination}" AS SELECT *, ?::VARCHAR execution_id, ?::VARCHAR trimestre, ?::INTEGER annee FROM raw_frame WHERE FALSE', [execution_id, quarter, year])
                con.execute(f'INSERT INTO "{destination}" SELECT *, ?, ?, ? FROM raw_frame', [execution_id, quarter, year])
                con.register("standard_frame", standard)
                con.execute("INSERT INTO paie_standardisee BY NAME SELECT * FROM standard_frame")
                con.execute("INSERT INTO journal_executions (execution_id,type_operation,fichier_source,table_source,table_destination,institution_id,regime,trimestre,annee,mode_chargement,lignes_lues,lignes_chargees,statut,date_fin) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)", [execution_id,"IMPORT_ACCESS",str(path),table,destination,institution_id,regime,quarter,year,mode,len(raw),len(standard),"TERMINE"])
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
        progress and progress(100, "Table Access chargée")
        return execution_id

    def load_excel(self, path: str, sheet: str, header_row: int, institution_id: str,
                   regime: str, quarter: str, year: int, mode: str = "append",
                   mapping: Optional[Dict[str, str]] = None, progress: Progress = None) -> str:
        execution_id = str(uuid.uuid4())
        progress and progress(5, "Lecture du déclaratif Excel")
        raw = pd.read_excel(path, sheet_name=sheet, header=max(header_row - 1, 0))
        metadata = dict(execution_id=execution_id, institution_id=institution_id, regime=regime,
                        trimestre=quarter, annee=year, fichier_source=str(path), feuille_source=sheet)
        mapping = mapping if mapping is not None else self.db.get_column_mapping(regime, "EXCEL")
        missing_required = [column for column in self.db.required_source_columns(regime, "EXCEL") if column not in raw.columns]
        if missing_required: raise ValueError(f"Colonnes Excel obligatoires absentes : {', '.join(missing_required)}")
        standard = standardize_declaration(raw, metadata, mapping)
        progress and progress(50, "Chargement du déclaratif dans DuckDB")
        with self.db.connect() as con:
            con.execute("BEGIN")
            try:
                if mode == "replace_period":
                    con.execute("DELETE FROM declaratif_standardise WHERE regime=? AND trimestre=? AND annee=? AND institution_id=?", [regime, quarter, year, institution_id])
                con.register("standard_frame", standard)
                con.execute("INSERT INTO declaratif_standardise BY NAME SELECT * FROM standard_frame")
                con.execute("INSERT INTO journal_executions (execution_id,type_operation,fichier_source,table_source,table_destination,institution_id,regime,trimestre,annee,mode_chargement,lignes_lues,lignes_chargees,statut,date_fin) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)", [execution_id,"IMPORT_EXCEL",str(path),sheet,"declaratif_standardise",institution_id,regime,quarter,year,mode,len(raw),len(standard),"TERMINE"])
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
        progress and progress(100, "Déclaratif chargé")
        return execution_id
