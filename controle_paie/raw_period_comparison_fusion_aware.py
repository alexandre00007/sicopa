from __future__ import annotations

from .raw_period_comparison import RawPeriodComparisonService


class FusionAwareRawPeriodComparisonService(RawPeriodComparisonService):
    """Comparaison RAW compatible avec les imports directs et les RAW matérialisés par une fusion."""

    def _fusion_metadata(self, table_name: str):
        with self.db.connect() as con:
            return con.execute(
                """SELECT fusion_id,trimestre,annee,statut,nombre_regimes
                   FROM fusions_raw
                   WHERE table_fusion=?
                   ORDER BY cree_le DESC
                   LIMIT 1""",
                [table_name],
            ).fetchone()

    def _executions(self, table_name: str, quarter: str, year: int):
        # 1) Cas habituel : raw_* provenant directement d'un IMPORT_ACCESS.
        rows = super()._executions(table_name, quarter, year)
        if rows:
            return rows

        # 2) Cas d'un raw_multi_regimes_* : sa provenance est enregistrée
        # dans fusions_raw / sources_fusion_raw et non comme table_destination
        # d'un IMPORT_ACCESS.
        with self.db.connect() as con:
            fusion = con.execute(
                """SELECT fusion_id
                   FROM fusions_raw
                   WHERE table_fusion=?
                     AND trimestre=? AND annee=?
                     AND statut='TERMINE'
                   ORDER BY cree_le DESC
                   LIMIT 1""",
                [table_name, quarter, int(year)],
            ).fetchone()
            if not fusion:
                return []
            return con.execute(
                """SELECT DISTINCT execution_id,institution_id,regime
                   FROM sources_fusion_raw
                   WHERE fusion_id=?
                     AND execution_id IS NOT NULL
                   ORDER BY execution_id""",
                [fusion[0]],
            ).fetchall()

    def list_raw_tables(self):
        with self.db.connect() as con:
            names = [r[0] for r in con.execute(
                """SELECT table_name
                   FROM information_schema.tables
                   WHERE table_schema='main' AND table_name LIKE 'raw_%'
                   ORDER BY table_name"""
            ).fetchall()]
            out = []
            for name in names:
                count = int(con.execute(f"SELECT COUNT(*) FROM {self._quote(name)}").fetchone()[0])
                meta = con.execute(
                    """SELECT regime,institution_id,trimestre,annee
                       FROM journal_executions
                       WHERE table_destination=? AND type_operation='IMPORT_ACCESS'
                       ORDER BY date_debut DESC
                       LIMIT 1""",
                    [name],
                ).fetchone()
                if meta:
                    out.append((name, count, *meta))
                    continue

                fusion = con.execute(
                    """SELECT fusion_id,trimestre,annee
                       FROM fusions_raw
                       WHERE table_fusion=? AND statut='TERMINE'
                       ORDER BY cree_le DESC
                       LIMIT 1""",
                    [name],
                ).fetchone()
                if not fusion:
                    out.append((name, count, "", "", "", ""))
                    continue

                source_meta = con.execute(
                    """SELECT
                         STRING_AGG(DISTINCT COALESCE(regime,''), ', ' ORDER BY COALESCE(regime,'')),
                         STRING_AGG(DISTINCT COALESCE(institution_id,''), ', ' ORDER BY COALESCE(institution_id,''))
                       FROM sources_fusion_raw
                       WHERE fusion_id=?""",
                    [fusion[0]],
                ).fetchone()
                regimes = (source_meta[0] if source_meta else "") or ""
                institutions = (source_meta[1] if source_meta else "") or ""
                out.append((name, count, regimes, institutions, fusion[1], fusion[2]))
            return out
