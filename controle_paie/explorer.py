from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd

from .database import Database
from .spreadsheet_utils import sanitize_excel_dataframe


class DataExplorerService:
    OPERATORS = ["égal à", "différent de", "contient", "commence par", ">", ">=", "<", "<=", "est vide", "n’est pas vide"]

    def __init__(self, database: Database):
        self.db = database

    def list_tables(self) -> list[str]:
        with self.db.connect() as connection:
            return [row[0] for row in connection.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='main' ORDER BY table_name"
            ).fetchall()]

    def columns(self, table: str) -> list[str]:
        self._require_table(table)
        with self.db.connect() as connection:
            return [row[1] for row in connection.execute(f'PRAGMA table_info("{table}")').fetchall()]

    def read(self, table: str, column: str = "", operator: str = "", value: str = "",
             limit: int = 500, offset: int = 0) -> pd.DataFrame:
        columns = self.columns(table)
        if column and column not in columns:
            raise ValueError("Colonne inconnue pour cette table.")
        limit = max(1, min(int(limit), 10_000)); offset = max(0, int(offset))
        query = f'SELECT * FROM "{table}"'; params = []
        if column and operator:
            quoted = '"' + column.replace('"', '""') + '"'
            clauses = {
                "égal à": f"CAST({quoted} AS VARCHAR) = ?",
                "différent de": f"CAST({quoted} AS VARCHAR) <> ?",
                "contient": f"CAST({quoted} AS VARCHAR) ILIKE ?",
                "commence par": f"CAST({quoted} AS VARCHAR) ILIKE ?",
                ">": f"TRY_CAST({quoted} AS DOUBLE) > TRY_CAST(? AS DOUBLE)",
                ">=": f"TRY_CAST({quoted} AS DOUBLE) >= TRY_CAST(? AS DOUBLE)",
                "<": f"TRY_CAST({quoted} AS DOUBLE) < TRY_CAST(? AS DOUBLE)",
                "<=": f"TRY_CAST({quoted} AS DOUBLE) <= TRY_CAST(? AS DOUBLE)",
                "est vide": f"({quoted} IS NULL OR CAST({quoted} AS VARCHAR) = '')",
                "n’est pas vide": f"({quoted} IS NOT NULL AND CAST({quoted} AS VARCHAR) <> '')",
            }
            if operator not in clauses:
                raise ValueError("Opérateur de filtre inconnu.")
            query += " WHERE " + clauses[operator]
            if operator not in {"est vide", "n’est pas vide"}:
                params.append(f"%{value}%" if operator == "contient" else f"{value}%" if operator == "commence par" else value)
        query += " LIMIT ? OFFSET ?"; params.extend([limit, offset])
        with self.db.connect() as connection:
            return connection.execute(query, params).df()

    def export(self, target: str, **filters) -> Path:
        filters["limit"] = min(int(filters.get("limit", 10_000)), 100_000)
        data = self.read(**filters)
        path = Path(target); path.parent.mkdir(parents=True, exist_ok=True)
        sanitize_excel_dataframe(data).to_excel(path, index=False, engine="openpyxl")
        return path

    def delete_rows(self, table: str, column: str = "", operator: str = "", value: str = "",
                    column2: str = "", operator2: str = "", value2: str = "") -> int:
        self._require_table(table)
        if not column or not operator:
            raise ValueError("Sélectionnez une colonne et un opérateur pour filtrer la table.")
        query = f'DELETE FROM "{table}"'
        params = []
        clauses = []
        filters = [
            (column, operator, value),
            (column2, operator2, value2),
        ]
        for col, op, raw_value in filters:
            if not col or not op:
                continue
            quoted = '"' + col.replace('"', '""') + '"'
            clause_map = {
                "égal à": f"CAST({quoted} AS VARCHAR) = ?",
                "différent de": f"CAST({quoted} AS VARCHAR) <> ?",
                "contient": f"CAST({quoted} AS VARCHAR) ILIKE ?",
                "commence par": f"CAST({quoted} AS VARCHAR) ILIKE ?",
                ">": f"TRY_CAST({quoted} AS DOUBLE) > TRY_CAST(? AS DOUBLE)",
                ">=": f"TRY_CAST({quoted} AS DOUBLE) >= TRY_CAST(? AS DOUBLE)",
                "<": f"TRY_CAST({quoted} AS DOUBLE) < TRY_CAST(? AS DOUBLE)",
                "<=": f"TRY_CAST({quoted} AS DOUBLE) <= TRY_CAST(? AS DOUBLE)",
                "est vide": f"({quoted} IS NULL OR CAST({quoted} AS VARCHAR) = '')",
                "n’est pas vide": f"({quoted} IS NOT NULL AND CAST({quoted} AS VARCHAR) <> '')",
            }
            if op not in clause_map:
                raise ValueError("Opérateur de filtre inconnu.")
            clause = clause_map[op]
            if op not in {"est vide", "n’est pas vide"}:
                if op == "contient":
                    params.append(f"%{raw_value}%")
                elif op == "commence par":
                    params.append(f"{raw_value}%")
                else:
                    params.append(str(raw_value))
            clauses.append(clause)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        with self.db.connect() as connection:
            count = 0
            if clauses:
                count = connection.execute(f'SELECT COUNT(*) FROM "{table}" WHERE ' + " AND ".join(clauses), params).fetchone()[0]
            else:
                count = connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            connection.execute(query, params)
            return int(count)

    def delete_scope(self, institution_id: str, regime: str, quarter: str, year: int | str) -> dict:
        return self.db.delete_data_scope(institution_id, regime, quarter, year)

    def _require_table(self, table: str) -> None:
        if table not in self.list_tables():
            raise ValueError("Table DuckDB inconnue.")
