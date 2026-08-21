from __future__ import annotations

import json
import platform
import re
import subprocess
import unicodedata
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable, Iterable

import duckdb
import pandas as pd

from .loaders import list_access_tables, read_access_table


SUPPORTED_EXTENSIONS = {".xlsx", ".xlsm", ".xls", ".mdb", ".accdb", ".parquet"}


@dataclass
class SearchHit:
    file: str
    container: str
    column: str
    row_number: int
    searched_value: str
    found_value: str
    row_data: dict

    def flat(self) -> dict:
        base = asdict(self)
        base["row_data"] = json.dumps(self.row_data, ensure_ascii=False, default=str)
        return base


def normalize_search_value(value: object) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(c for c in text if not unicodedata.combining(c)).upper()
    return re.sub(r"[^A-Z0-9]", "", text)


def _matches(candidate: object, wanted: str, mode: str) -> bool:
    left = "" if candidate is None else str(candidate)
    right = str(wanted)
    mode = str(mode or "EXACT").upper()
    if mode == "NORMALIZED":
        return normalize_search_value(left) == normalize_search_value(right)
    left_cf, right_cf = left.casefold(), right.casefold()
    if mode == "CONTAINS":
        return right_cf in left_cf
    if mode == "STARTS":
        return left_cf.startswith(right_cf)
    if mode == "ENDS":
        return left_cf.endswith(right_cf)
    return left_cf == right_cf


def _excel_structure(path: Path) -> dict[str, list[str]]:
    book = pd.ExcelFile(path)
    result = {}
    for sheet in book.sheet_names:
        try:
            result[sheet] = [str(c) for c in pd.read_excel(path, sheet_name=sheet, nrows=0).columns]
        except Exception:
            result[sheet] = []
    return result


def _parquet_structure(path: Path) -> dict[str, list[str]]:
    con = duckdb.connect()
    try:
        safe = str(path).replace("'", "''")
        rows = con.execute(f"DESCRIBE SELECT * FROM read_parquet('{safe}')").fetchall()
        return {"Parquet": [str(row[0]) for row in rows]}
    finally:
        con.close()


def _access_columns_linux(path: Path, table: str) -> list[str]:
    proc = subprocess.Popen(
        ["mdb-export", str(path), table], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
    )
    try:
        header = proc.stdout.readline() if proc.stdout else ""
    finally:
        proc.kill()
        proc.communicate()
    if not header:
        return []
    import csv
    return next(csv.reader([header.rstrip("\r\n")]), [])


def inspect_file(path: str | Path, access_driver: str = "Microsoft Access Driver (*.mdb, *.accdb)") -> dict[str, list[str]]:
    source = Path(path)
    suffix = source.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Format non pris en charge : {source.suffix}")
    if suffix in {".xlsx", ".xlsm", ".xls"}:
        return _excel_structure(source)
    if suffix == ".parquet":
        return _parquet_structure(source)
    tables = list_access_tables(str(source), access_driver)
    result = {}
    for table in tables:
        try:
            if platform.system() != "Windows":
                result[table] = _access_columns_linux(source, table)
            else:
                result[table] = [str(c) for c in read_access_table(str(source), table, access_driver).columns]
        except Exception:
            result[table] = []
    return result


def inspect_files(paths: Iterable[str | Path], access_driver: str = "Microsoft Access Driver (*.mdb, *.accdb)", progress: Callable[[int, str], None] | None = None) -> dict[str, dict[str, list[str]]]:
    items = [Path(p) for p in paths]
    result = {}
    total = max(1, len(items))
    for index, path in enumerate(items, 1):
        progress and progress(int(index * 100 / total), f"Structure : {path.name}")
        result[str(path)] = inspect_file(path, access_driver)
    return result


def _iter_excel(path: Path, containers: Iterable[str]):
    for sheet in containers:
        frame = pd.read_excel(path, sheet_name=sheet, dtype=object)
        yield sheet, frame
        del frame


def _iter_access(path: Path, containers: Iterable[str], access_driver: str):
    for table in containers:
        frame = read_access_table(str(path), table, access_driver)
        yield table, frame
        del frame


def _search_frame(path: Path, container: str, frame: pd.DataFrame, values: list[str], key_column: str | None, all_columns: bool) -> list[SearchHit]:
    columns = [str(c) for c in frame.columns]
    targets = columns if all_columns else ([key_column] if key_column in columns else [])
    hits: list[SearchHit] = []
    if not targets:
        return hits
    for row_pos, (_, row) in enumerate(frame.iterrows(), start=2):
        row_dict = {str(k): ("" if pd.isna(v) else v) for k, v in row.to_dict().items()}
        for column in targets:
            candidate = row_dict.get(column, "")
            for wanted, mode in values:
                if _matches(candidate, wanted, mode):
                    hits.append(SearchHit(str(path), container, column, row_pos, wanted, str(candidate), row_dict))
    return hits


def _search_parquet(path: Path, values: list[tuple[str, str]], key_column: str | None, all_columns: bool) -> list[SearchHit]:
    con = duckdb.connect()
    hits: list[SearchHit] = []
    try:
        safe = str(path).replace("'", "''")
        columns = [str(r[0]) for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet('{safe}')").fetchall()]
        targets = columns if all_columns else ([key_column] if key_column in columns else [])
        for column in targets:
            qcol = '"' + column.replace('"', '""') + '"'
            for wanted, mode in values:
                if mode == "EXACT":
                    predicate = f"lower(CAST({qcol} AS VARCHAR))=lower(?)"
                    params = [wanted]
                elif mode == "CONTAINS":
                    predicate = f"lower(CAST({qcol} AS VARCHAR)) LIKE lower(?)"
                    params = [f"%{wanted}%"]
                elif mode == "STARTS":
                    predicate = f"lower(CAST({qcol} AS VARCHAR)) LIKE lower(?)"
                    params = [f"{wanted}%"]
                elif mode == "ENDS":
                    predicate = f"lower(CAST({qcol} AS VARCHAR)) LIKE lower(?)"
                    params = [f"%{wanted}"]
                else:
                    # Le mode normalisé est évalué côté Python pour préserver exactement la même règle.
                    predicate = "TRUE"
                    params = []
                cursor = con.execute(f"SELECT row_number() OVER () rn,* FROM read_parquet('{safe}') WHERE {predicate}", params)
                names = [d[0] for d in cursor.description]
                while True:
                    rows = cursor.fetchmany(2000)
                    if not rows:
                        break
                    for raw in rows:
                        data = dict(zip(names, raw))
                        candidate = data.get(column, "")
                        if mode == "NORMALIZED" and not _matches(candidate, wanted, mode):
                            continue
                        rn = int(data.pop("rn", 0) or 0) + 1
                        hits.append(SearchHit(str(path), "Parquet", column, rn, wanted, str(candidate), data))
        return hits
    finally:
        con.close()


def search_files(paths: Iterable[str | Path], structures: dict[str, dict[str, list[str]]], searched_values: Iterable[str], mode: str = "EXACT", key_column: str | None = None, all_columns: bool = False, access_driver: str = "Microsoft Access Driver (*.mdb, *.accdb)", progress: Callable[[int, str], None] | None = None) -> list[SearchHit]:
    files = [Path(p) for p in paths]
    values = [(str(v).strip(), str(mode).upper()) for v in searched_values if str(v).strip()]
    if not values:
        raise ValueError("Saisissez au moins une valeur à rechercher.")
    if not all_columns and not str(key_column or "").strip():
        raise ValueError("Sélectionnez une colonne clé ou activez Recherche partout.")
    hits: list[SearchHit] = []
    total = max(1, len(files))
    for index, path in enumerate(files, 1):
        progress and progress(int((index - 1) * 100 / total), f"Recherche : {path.name}")
        suffix = path.suffix.lower()
        containers = list((structures.get(str(path)) or {}).keys())
        if suffix == ".parquet":
            hits.extend(_search_parquet(path, values, key_column, all_columns))
            continue
        iterator = _iter_excel(path, containers) if suffix in {".xlsx", ".xlsm", ".xls"} else _iter_access(path, containers, access_driver)
        for container, frame in iterator:
            hits.extend(_search_frame(path, container, frame, values, key_column, all_columns))
    progress and progress(100, f"Recherche terminée : {len(hits)} occurrence(s)")
    return hits


def export_hits_xlsx(hits: Iterable[SearchHit], searched_values: Iterable[str], target: str | Path) -> Path:
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    rows = [h.flat() for h in hits]
    values = [str(v).strip() for v in searched_values if str(v).strip()]
    found = {h.searched_value for h in hits}
    summary = pd.DataFrame([
        {"Indicateur": "Valeurs recherchées", "Valeur": len(values)},
        {"Indicateur": "Valeurs trouvées", "Valeur": len(found)},
        {"Indicateur": "Valeurs non trouvées", "Valeur": len(set(values) - found)},
        {"Indicateur": "Occurrences totales", "Valeur": len(rows)},
        {"Indicateur": "Fichiers avec résultat", "Valeur": len({h.file for h in hits})},
    ])
    detail = pd.DataFrame(rows)
    missing = pd.DataFrame({"Valeur non trouvée": sorted(set(values) - found)})
    with pd.ExcelWriter(target, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="Synthese", index=False)
        detail.to_excel(writer, sheet_name="Correspondances", index=False)
        missing.to_excel(writer, sheet_name="Non_trouves", index=False)
    return target
