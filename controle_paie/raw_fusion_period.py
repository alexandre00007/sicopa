from __future__ import annotations

from .raw_fusion import RawFusionMultiRegimeService


class PeriodAwareRawFusionService(RawFusionMultiRegimeService):
    """Garantit que la table RAW fusionnée ne contient que les exécutions de la période choisie."""

    def create_fusion(self, table_names, quarter, year, suffix="", progress=None):
        info = super().create_fusion(table_names, quarter, year, suffix, progress=progress)
        with self.db.connect() as con:
            execution_ids = [r[0] for r in con.execute(
                "SELECT DISTINCT execution_id FROM sources_fusion_raw WHERE fusion_id=? AND execution_id IS NOT NULL",
                [info["id"]],
            ).fetchall()]
            if execution_ids:
                placeholders = ",".join("?" for _ in execution_ids)
                safe = self._quote(info["table"])
                columns = {r[0] for r in con.execute(f"DESCRIBE {safe}").fetchall()}
                if "execution_id" in columns:
                    con.execute(
                        f"DELETE FROM {safe} WHERE execution_id IS NULL OR execution_id NOT IN ({placeholders})",
                        execution_ids,
                    )
                    rows = int(con.execute(f"SELECT COUNT(*) FROM {safe}").fetchone()[0])
                    con.execute("UPDATE fusions_raw SET lignes_fusion=? WHERE fusion_id=?", [rows, info["id"]])
        return self.get_fusion(info["id"])
