from __future__ import annotations

import logging
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

APP_NAME = "SICORPA"
APP_VERSION = "1.0.0"
CURRENT_SCHEMA_VERSION = 2
DEVELOPER = "Alexandre Mulumba Kande"


@dataclass(frozen=True)
class RuntimePaths:
    data_dir: Path
    database: Path
    results_dir: Path
    backups_dir: Path
    imports_dir: Path
    logs_dir: Path
    log_file: Path


def _documents_dir() -> Path:
    candidate = Path.home() / "Documents"
    return candidate if candidate.exists() else Path.home()


def default_runtime_paths() -> RuntimePaths:
    override = os.environ.get("SICORPA_HOME", "").strip()
    if override:
        data_dir = Path(override).expanduser().resolve()
        documents_root = data_dir
    elif platform.system() == "Windows":
        data_dir = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / APP_NAME
        documents_root = _documents_dir() / APP_NAME
    else:
        data_dir = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP_NAME.lower()
        documents_root = _documents_dir() / APP_NAME
    return RuntimePaths(
        data_dir=data_dir,
        database=data_dir / "controle_paie.duckdb",
        results_dir=documents_root / "Resultats",
        backups_dir=documents_root / "Sauvegardes",
        imports_dir=documents_root / "Imports",
        logs_dir=data_dir / "journaux",
        log_file=data_dir / "journaux" / "sicorpa.log",
    )


def initialize_runtime(paths: RuntimePaths, legacy_database: Path | None = None) -> bool:
    for folder in (paths.data_dir, paths.results_dir, paths.backups_dir, paths.imports_dir, paths.logs_dir):
        folder.mkdir(parents=True, exist_ok=True)
    configure_logging(paths.log_file)
    migrated = False
    legacy = legacy_database or Path.cwd() / "traitement" / "controle_paie.duckdb"
    if not paths.database.exists() and legacy.exists() and legacy.resolve() != paths.database.resolve():
        shutil.copy2(legacy, paths.database)
        migrated = True
        logging.info("Ancienne base copiée vers %s", paths.database)
    return migrated


def configure_logging(log_file: Path) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    if not any(isinstance(handler, logging.FileHandler) and Path(handler.baseFilename) == log_file for handler in root.handlers):
        handler = logging.FileHandler(log_file, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"))
        root.addHandler(handler)
    root.setLevel(logging.INFO)


def database_schema_version(database: Path) -> int:
    if not database.exists():
        return 0
    try:
        import duckdb
        connection=duckdb.connect(str(database),read_only=True)
        try:
            row=connection.execute("SELECT valeur FROM sicorpa_meta WHERE cle='schema_version'").fetchone()
            return int(row[0]) if row else 0
        finally:
            connection.close()
    except Exception:
        return 0


def backup_database(database: Path, backups_dir: Path, reason: str = "manuel") -> Path | None:
    if not database.exists():
        return None
    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    target = backups_dir / f"controle_paie_{reason}_{stamp}.duckdb"
    shutil.copy2(database, target)
    logging.info("Sauvegarde DuckDB créée : %s", target)
    return target


def open_path(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True) if path.suffix == "" else None
    if platform.system() == "Windows":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif platform.system() == "Darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def resource_path(relative: str) -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return root / relative
