from __future__ import annotations

import io
import platform
import re
import subprocess
from pathlib import Path

import pandas as pd

from .loaders import _require_mdbtools, _validate_access_file, _windows_access_connection


def read_access_table_fast(path: str, table: str, driver: str) -> pd.DataFrame:
    """Lecture Access optimisee pour les gros volumes.

    Sous Linux, mdb-export est branche directement sur le parseur CSV Pandas au lieu
    de construire d'abord une enorme chaine Python puis un second buffer StringIO.
    Cela reduit fortement les copies memoire et accelere les gros imports.
    """
    _validate_access_file(path)
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table):
        raise ValueError("Nom de table Access invalide")

    if platform.system() == "Windows":
        with _windows_access_connection(path, driver) as con:
            return pd.read_sql(f"SELECT * FROM [{table}]", con)

    _require_mdbtools()
    process = subprocess.Popen(
        ["mdb-export", path, table],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if process.stdout is None:
        raise RuntimeError("Impossible d'ouvrir le flux mdb-export.")

    stream = io.TextIOWrapper(process.stdout, encoding="utf-8", errors="replace", newline="")
    try:
        frame = pd.read_csv(stream, dtype=object, keep_default_na=False, low_memory=False)
    finally:
        try:
            stream.close()
        except Exception:
            pass

    stderr = b""
    if process.stderr is not None:
        stderr = process.stderr.read()
    return_code = process.wait()
    if return_code != 0:
        detail = stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"mdb-export a echoue pour {Path(path).name}/{table}: {detail or return_code}")
    return frame
