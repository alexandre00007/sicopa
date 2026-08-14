from __future__ import annotations

import re
from typing import Iterable


# XML 1.0 interdit ces caractères de contrôle. Ils peuvent provenir d'Access,
# d'un copier-coller ou d'un ancien système et sont acceptés par DuckDB, mais
# font échouer openpyxl lors de la création du fichier XLSX.
_INVALID_XML_CHARACTERS = re.compile(
    r"[\x00-\x08\x0B\x0C\x0E-\x1F\uD800-\uDFFF\uFFFE\uFFFF]+"
)
EXCEL_MAX_TEXT_LENGTH = 32_767


def sanitize_xml_text(value: object) -> str:
    """Return XML-safe text while keeping visible information separated."""
    text = value if isinstance(value, str) else str(value)
    return _INVALID_XML_CHARACTERS.sub(" ", text)


def sanitize_excel_value(value: object) -> object:
    """Make a cell value safe for XLSX without changing typed numeric values."""
    if not isinstance(value, str):
        return value
    return sanitize_xml_text(value)[:EXCEL_MAX_TEXT_LENGTH]


def sanitize_excel_row(row: Iterable[object]) -> tuple[object, ...]:
    """Sanitize one streamed row before it is passed to openpyxl."""
    return tuple(sanitize_excel_value(value) for value in row)


def sanitize_excel_dataframe(frame):
    """Return a safe copy of a pandas frame while preserving numeric columns."""
    result = frame.copy()
    result.columns = [sanitize_excel_value(column) for column in result.columns]
    for column in result.select_dtypes(include=["object", "string"]).columns:
        result[column] = result[column].map(sanitize_excel_value)
    return result
