from __future__ import annotations

from .raw_fusion_period import PeriodAwareRawFusionService


class DuplicateAwareRawFusionService(PeriodAwareRawFusionService):
    """Enrichit l'analyse de fusion avec les doublons par matricule et par nom."""

    def ensure_schema(self):
        super().ensure_schema()
        with self.db.connect() as con:
            con.execute("""CREATE TABLE IF NOT EXISTS resultats_fusion_doublons (
                fusion_id VARCHAR,
                person_key VARCHAR,
                doublon_matricule BOOLEAN DEFAULT FALSE,
                doublon_nom BOOLEAN DEFAULT FALSE,
                occurrences_matricule BIGINT DEFAULT 0,
                occurrences_nom BIGINT DEFAULT 0,
                PRIMARY KEY(fusion_id, person_key)
            )""")
            con.execute("CREATE INDEX IF NOT EXISTS idx_fusion_doublons ON resultats_fusion_doublons(fusion_id,doublon_matricule,doublon_nom)")

    def create_fusion(self, table_names, quarter, year, suffix="", progress=None):
        info = super().create_fusion(table_names, quarter, year, suffix, progress=progress)
        self._compute_duplicates(info["id"])
        return info

    def _compute_duplicates(self, fusion_id: str) -> None:
        with self.db.connect() as con:
            execution_ids = [r[0] for r in con.execute(
                "SELECT DISTINCT execution_id FROM sources_fusion_raw WHERE fusion_id=? AND execution_id IS NOT NULL",
                [fusion_id],
            ).fetchall()]
            if not execution_ids:
                return
            ph = ",".join("?" for _ in execution_ids)
            con.execute("DELETE FROM resultats_fusion_doublons WHERE fusion_id=?", [fusion_id])
            con.execute(f"""INSERT INTO resultats_fusion_doublons
                WITH base AS (
                    SELECT matricule_normalise,nom_normalise
                    FROM paie_standardisee
                    WHERE execution_id IN ({ph})
                ), mat_counts AS (
                    SELECT matricule_normalise,COUNT(*) n
                    FROM base
                    WHERE COALESCE(matricule_normalise,'') NOT IN ('','NU')
                    GROUP BY matricule_normalise
                ), nom_counts AS (
                    SELECT nom_normalise,COUNT(*) n
                    FROM base
                    WHERE COALESCE(nom_normalise,'')<>''
                    GROUP BY nom_normalise
                )
                SELECT ?,r.person_key,
                       COALESCE(mc.n,0)>1,
                       COALESCE(nc.n,0)>1,
                       COALESCE(mc.n,0),
                       COALESCE(nc.n,0)
                FROM resultats_fusion_multi r
                LEFT JOIN mat_counts mc ON mc.matricule_normalise=r.matricule_normalise
                LEFT JOIN nom_counts nc ON nc.nom_normalise=r.nom_normalise
                WHERE r.fusion_id=?""", execution_ids + [fusion_id, fusion_id])

    def list_results(self, fusion_id: str, status: str = "", limit: int = 3000) -> list[tuple]:
        condition = "r.fusion_id=?"
        params = [fusion_id]
        if status == "DOUBLON_MATRICULE":
            condition += " AND COALESCE(d.doublon_matricule,FALSE)"
        elif status == "DOUBLON_NOM":
            condition += " AND COALESCE(d.doublon_nom,FALSE)"
        elif status:
            condition += " AND r.statut=?"
            params.append(status)
        params.append(max(1, min(int(limit), 10000)))
        with self.db.connect() as con:
            return con.execute(f"""SELECT r.statut,r.matricule_normalise,r.nom,r.prenom,r.regimes,r.nb_regimes,r.nb_institutions,
                r.occurrences,r.masse_brute,r.masse_net,r.sections,r.categories,r.grades,r.unites_affectation,r.provinces,
                r.paiement_multi_regime,r.paiement_multiple_meme_regime,r.identite_incoherente,
                TRIM(CONCAT_WS(' ; ',NULLIF(r.diagnostic,''),
                    CASE WHEN COALESCE(d.doublon_matricule,FALSE) THEN 'Doublon matricule ('||CAST(d.occurrences_matricule AS VARCHAR)||' occurrences)' END,
                    CASE WHEN COALESCE(d.doublon_nom,FALSE) THEN 'Doublon nom ('||CAST(d.occurrences_nom AS VARCHAR)||' occurrences)' END))
                FROM resultats_fusion_multi r
                LEFT JOIN resultats_fusion_doublons d ON d.fusion_id=r.fusion_id AND d.person_key=r.person_key
                WHERE {condition}
                ORDER BY r.nb_regimes DESC,r.occurrences DESC,r.masse_brute DESC LIMIT ?""", params).fetchall()

    def summary(self, fusion_id: str) -> list[tuple]:
        rows = list(super().summary(fusion_id))
        with self.db.connect() as con:
            extra = con.execute("""SELECT 'DOUBLON_MATRICULE',COUNT(*),
                       COALESCE(SUM(r.occurrences),0),COALESCE(SUM(r.masse_brute),0),COALESCE(SUM(r.masse_net),0)
                    FROM resultats_fusion_doublons d
                    JOIN resultats_fusion_multi r ON r.fusion_id=d.fusion_id AND r.person_key=d.person_key
                    WHERE d.fusion_id=? AND d.doublon_matricule
                    UNION ALL
                    SELECT 'DOUBLON_NOM',COUNT(*),
                       COALESCE(SUM(r.occurrences),0),COALESCE(SUM(r.masse_brute),0),COALESCE(SUM(r.masse_net),0)
                    FROM resultats_fusion_doublons d
                    JOIN resultats_fusion_multi r ON r.fusion_id=d.fusion_id AND r.person_key=d.person_key
                    WHERE d.fusion_id=? AND d.doublon_nom""", [fusion_id, fusion_id]).fetchall()
        return rows + [row for row in extra if int(row[1] or 0) > 0]

    def delete_fusion(self, fusion_id: str) -> None:
        with self.db.connect() as con:
            con.execute("DELETE FROM resultats_fusion_doublons WHERE fusion_id=?", [fusion_id])
        return super().delete_fusion(fusion_id)
