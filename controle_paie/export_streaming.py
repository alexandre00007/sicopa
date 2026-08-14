from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from .spreadsheet_utils import sanitize_excel_row


EXCEL_MAX_DATA_ROWS = 1_048_575  # une ligne réservée à l'en-tête


def write_query_xlsx(con, path: str | Path, query: str, params=None, headers=None,
                     sheet_name: str = "Résultats", chunk_size: int = 5000) -> int:
    """Écrit tout le résultat DuckDB en streaming, avec découpage automatique des feuilles Excel."""
    cursor = con.execute(query, params or [])
    if headers is None:
        headers = [column[0] for column in cursor.description]
    headers = list(headers)

    book = Workbook(write_only=True)
    sheet_index = 1
    sheet = book.create_sheet(sheet_name[:31])
    sheet.append(headers)
    rows_in_sheet = 0
    total = 0

    while True:
        chunk = cursor.fetchmany(max(100, int(chunk_size)))
        if not chunk:
            break
        for row in chunk:
            if rows_in_sheet >= EXCEL_MAX_DATA_ROWS:
                sheet_index += 1
                suffix = f"_{sheet_index}"
                sheet = book.create_sheet((sheet_name[:31-len(suffix)] + suffix)[:31])
                sheet.append(headers)
                rows_in_sheet = 0
            sheet.append(list(sanitize_excel_row(row)))
            rows_in_sheet += 1
            total += 1

    book.save(Path(path))
    return total
