from pathlib import Path

import pandas as pd

from controle_paie.file_data_search import (
    inspect_files,
    normalize_search_value,
    search_files,
)


def test_normalize_search_value():
    assert normalize_search_value(" 00-12.3 ") == "00123"
    assert normalize_search_value("Múlúmba Alexandre") == "MULUMBAALEXANDRE"


def test_excel_multi_sheet_search_returns_full_rows(tmp_path):
    path = tmp_path / "agents.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame([
            {"Matricule": "000-123", "Nom": "MULUMBA", "Section": "FIN", "Grade": "A1"},
            {"Matricule": "999", "Nom": "AUTRE", "Section": "RH", "Grade": "B1"},
        ]).to_excel(writer, sheet_name="T1", index=False)
        pd.DataFrame([
            {"Matricule": "123", "Nom": "MULUMBA", "Section": "AUDIT", "Grade": "A2"},
        ]).to_excel(writer, sheet_name="T2", index=False)

    structures = inspect_files([path])
    assert set(structures[str(path)]) == {"T1", "T2"}
    assert "Section" in structures[str(path)]["T1"]

    hits = search_files([path], structures, ["000123", "123"], mode="NORMALIZED", key_column="Matricule")
    assert len(hits) == 4  # chaque valeur recherchée normalisée retrouve les deux lignes 123
    assert {hit.container for hit in hits} == {"T1", "T2"}
    assert {hit.row_data["Section"] for hit in hits} == {"FIN", "AUDIT"}


def test_search_everywhere_finds_column_and_parquet(tmp_path):
    path = tmp_path / "agents.parquet"
    pd.DataFrame([
        {"Matricule": "10", "Nom": "KABILA", "Province": "KINSHASA"},
        {"Matricule": "20", "Nom": "MULUMBA", "Province": "KONGO CENTRAL"},
    ]).to_parquet(path, index=False)

    structures = inspect_files([path])
    hits = search_files([path], structures, ["KONGO CENTRAL"], mode="EXACT", all_columns=True)
    assert len(hits) == 1
    assert hits[0].column == "Province"
    assert hits[0].row_data["Nom"] == "MULUMBA"
