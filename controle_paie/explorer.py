from __future__ import annotations

from pathlib import Path

import pandas as pd

from .database import Database
from .export_streaming import write_query_xlsx


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

    def _select_query(self, table: str, column: str = "", operator: str = "", value: str = ""):
        self._require_table(table)
        columns = self.columns(table)
        if column and column not in columns:
            raise ValueError("Colonne inconnue pour cette table.")
        query = f'SELECT * FROM "{table}"'
        params = []
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
        return query, params

    def count(self, table: str, column: str = "", operator: str = "", value: str = "") -> int:
        query, params = self._select_query(table, column, operator, value)
        count_query = f"SELECT COUNT(*) FROM ({query}) q"
        with self.db.connect() as connection:
            return int(connection.execute(count_query, params).fetchone()[0] or 0)

    def read(self, table: str, column: str = "", operator: str = "", value: str = "",
             limit: int = 500, offset: int = 0) -> pd.DataFrame:
        query, params = self._select_query(table, column, operator, value)
        limit = max(1, min(int(limit), 10_000)); offset = max(0, int(offset))
        query += " LIMIT ? OFFSET ?"; params.extend([limit, offset])
        with self.db.connect() as connection:
            return connection.execute(query, params).df()

    def page(self, table: str, column: str = "", operator: str = "", value: str = "",
             page: int = 1, page_size: int = 500) -> dict:
        page_size = max(1, min(int(page_size), 5000))
        page = max(1, int(page))
        total = self.count(table, column, operator, value)
        total_pages = max(1, (total + page_size - 1) // page_size)
        page = min(page, total_pages)
        offset = (page - 1) * page_size
        frame = self.read(table, column, operator, value, limit=page_size, offset=offset)
        return {
            "rows": frame,
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
            "offset": offset,
        }

    def export(self, target: str, **filters) -> Path:
        """Exporte tout le périmètre filtré, indépendamment de la pagination d'affichage."""
        query, params = self._select_query(
            filters.get("table", ""), filters.get("column", ""),
            filters.get("operator", ""), filters.get("value", ""),
        )
        path = Path(target)
        with self.db.connect() as connection:
            write_query_xlsx(connection, path, query, params, sheet_name="Explorateur")
        return path

    def delete_rows(self, table: str, column: str = "", operator: str = "", value: str = "",
                    column2: str = "", operator2: str = "", value2: str = "") -> int:
        self._require_table(table)
        if not column or not operator:
            raise ValueError("Sélectionnez une colonne et un opérateur pour filtrer la table.")
        query = f'DELETE FROM "{table}"'
        params = []
        clauses = []
        filters = [(column, operator, value), (column2, operator2, value2)]
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
                params.append(f"%{raw_value}%" if op == "contient" else f"{raw_value}%" if op == "commence par" else str(raw_value))
            clauses.append(clause)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        with self.db.connect() as connection:
            count_query = f'SELECT COUNT(*) FROM "{table}"' + (" WHERE " + " AND ".join(clauses) if clauses else "")
            count = connection.execute(count_query, params).fetchone()[0]
            connection.execute(query, params)
            return int(count)

    def delete_scope(self, institution_id: str, regime: str, quarter: str, year: int | str) -> dict:
        return self.db.delete_data_scope(institution_id, regime, quarter, year)

    def _require_table(self, table: str) -> None:
        if table not in self.list_tables():
            raise ValueError("Table DuckDB inconnue.")
