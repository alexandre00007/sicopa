from __future__ import annotations

import os
import time
from pathlib import Path


class PerformanceHealthService:
    """Metriques et maintenance prudente de la base SICORPA."""

    def __init__(self, db, raw_catalog=None):
        self.db = db
        self.raw_catalog = raw_catalog

    @staticmethod
    def _dir_size(path: Path) -> int:
        total = 0
        if not path.exists():
            return 0
        for root, _dirs, files in os.walk(path):
            for name in files:
                try:
                    total += (Path(root) / name).stat().st_size
                except OSError:
                    pass
        return total

    @staticmethod
    def _human_size(size: int) -> str:
        value = float(max(0, size))
        units = ["o", "Ko", "Mo", "Go", "To"]
        for unit in units:
            if value < 1024 or unit == units[-1]:
                return f"{value:.1f} {unit}"
            value /= 1024
        return f"{value:.1f} To"

    def snapshot(self) -> dict:
        db_path = Path(self.db.path)
        temp_path = Path(self.db.temp_directory)
        with self.db.connect() as con:
            raw_count = int(con.execute("""SELECT COUNT(*) FROM information_schema.tables
                WHERE table_schema='main' AND table_name LIKE 'raw_%'""").fetchone()[0] or 0)
            tables_count = int(con.execute("""SELECT COUNT(*) FROM information_schema.tables
                WHERE table_schema='main'""").fetchone()[0] or 0)
            treatments = int(con.execute("""SELECT COUNT(*) FROM information_schema.tables
                WHERE table_schema='main' AND table_name='journal_traitements'""").fetchone()[0] or 0)
            running = 0
            errors = 0
            if treatments:
                running = int(con.execute("SELECT COUNT(*) FROM journal_traitements WHERE statut='EN_COURS'").fetchone()[0] or 0)
                errors = int(con.execute("""SELECT COUNT(*) FROM journal_traitements
                    WHERE statut='ERREUR' AND date_debut>=CURRENT_TIMESTAMP-INTERVAL '7 days'""").fetchone()[0] or 0)
        db_size = db_path.stat().st_size if db_path.exists() else 0
        temp_size = self._dir_size(temp_path)
        tuning = self.db.tuning_info()
        return {
            "database_path": str(db_path),
            "database_size": db_size,
            "database_size_text": self._human_size(db_size),
            "temp_path": str(temp_path),
            "temp_size": temp_size,
            "temp_size_text": self._human_size(temp_size),
            "threads": tuning.get("threads"),
            "memory_limit_mb": tuning.get("memory_limit_mb"),
            "raw_tables": raw_count,
            "tables": tables_count,
            "running_treatments": running,
            "errors_7d": errors,
        }

    def checkpoint(self) -> dict:
        started = time.perf_counter()
        with self.db.connect() as con:
            con.execute("CHECKPOINT")
        return {"operation": "CHECKPOINT", "seconds": round(time.perf_counter() - started, 3)}

    def refresh_catalog(self) -> int:
        if self.raw_catalog is None:
            return 0
        return len(self.raw_catalog.refresh())

    def cleanup_orphan_temp_files(self, min_age_hours: float = 24.0) -> dict:
        """Supprime seulement les fichiers temporaires anciens, jamais ceux d'un traitement recent."""
        temp_path = Path(self.db.temp_directory)
        if not temp_path.exists():
            return {"files": 0, "bytes": 0}
        threshold = time.time() - max(1.0, float(min_age_hours)) * 3600
        deleted = 0
        freed = 0
        for path in temp_path.rglob("*"):
            if not path.is_file():
                continue
            try:
                stat = path.stat()
                if stat.st_mtime >= threshold:
                    continue
                size = stat.st_size
                path.unlink()
                deleted += 1
                freed += size
            except OSError:
                pass
        return {"files": deleted, "bytes": freed, "bytes_text": self._human_size(freed)}
