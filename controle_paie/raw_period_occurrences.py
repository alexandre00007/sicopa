from __future__ import annotations

from .raw_period_comparison_policy_scalable import PolicyScalableRawPeriodComparisonService


class OccurrenceAwareRawPeriodComparisonService(PolicyScalableRawPeriodComparisonService):
    """Enrichit la comparaison RAW avec les lignes source reelles et les repetitions.

    Semantique:
    - lignes_source_* = nombre total de lignes physiques de l'identite dans la source;
    - occurrences_* = nombre de repetitions au-dela de la premiere ligne (0 si unique);
    - situation_occurrences = qualite 1-vs-1 / repetition A / B / A+B pour un commun exact.
    """

    def ensure_schema(self):
        super().ensure_schema()
        with self.db.connect() as con:
            for statement in [
                "ALTER TABLE resultats_comparaison_raw_periode ADD COLUMN IF NOT EXISTS lignes_source_a BIGINT DEFAULT 0",
                "ALTER TABLE resultats_comparaison_raw_periode ADD COLUMN IF NOT EXISTS lignes_source_b BIGINT DEFAULT 0",
                "ALTER TABLE resultats_comparaison_raw_periode ADD COLUMN IF NOT EXISTS executions_a BIGINT DEFAULT 0",
                "ALTER TABLE resultats_comparaison_raw_periode ADD COLUMN IF NOT EXISTS executions_b BIGINT DEFAULT 0",
                "ALTER TABLE resultats_comparaison_raw_periode ADD COLUMN IF NOT EXISTS numeros_lignes_a VARCHAR",
                "ALTER TABLE resultats_comparaison_raw_periode ADD COLUMN IF NOT EXISTS numeros_lignes_b VARCHAR",
                "ALTER TABLE resultats_comparaison_raw_periode ADD COLUMN IF NOT EXISTS montants_distincts_a BIGINT DEFAULT 0",
                "ALTER TABLE resultats_comparaison_raw_periode ADD COLUMN IF NOT EXISTS montants_distincts_b BIGINT DEFAULT 0",
                "ALTER TABLE resultats_comparaison_raw_periode ADD COLUMN IF NOT EXISTS situation_occurrences VARCHAR",
                "ALTER TABLE resultats_comparaison_raw_periode ADD COLUMN IF NOT EXISTS ecart_lignes BIGINT DEFAULT 0",
            ]:
                con.execute(statement)
            con.execute("""CREATE TABLE IF NOT EXISTS occurrences_comparaison_raw (
                comparaison_id VARCHAR NOT NULL,
                cote VARCHAR NOT NULL,
                table_source VARCHAR,
                execution_id VARCHAR,
                ligne_paie_id VARCHAR,
                ligne_source BIGINT,
                matricule_normalise VARCHAR,
                nom_normalise VARCHAR,
                nom VARCHAR,
                prenom VARCHAR,
                institution_id VARCHAR,
                regime VARCHAR,
                section VARCHAR,
                categorie VARCHAR,
                grade VARCHAR,
                unite_affectation VARCHAR,
                province VARCHAR,
                brut DECIMAL(38,2),
                net DECIMAL(38,2)
            )""")
            con.execute("CREATE INDEX IF NOT EXISTS idx_occ_cmp_raw_identite ON occurrences_comparaison_raw(comparaison_id,cote,matricule_normalise,nom_normalise)")

    def analyze(self, table_a: str, table_b: str, quarter: str, year: int, progress=None):
        info = super().analyze(table_a, table_b, quarter, year, progress=progress)
        progress and progress(88, "Traçage des lignes source et des répétitions")
        self._capture_occurrences(info["id"])
        progress and progress(96, "Classification des occurrences des éléments communs")
        self._apply_occurrence_metrics(info["id"])
        progress and progress(100, "Comparaison RAW et occurrences terminées")
        return info

    def _capture_occurrences(self, comparison_id: str) -> None:
        with self.db.connect() as con:
            con.execute("DELETE FROM occurrences_comparaison_raw WHERE comparaison_id=?", [comparison_id])
            for side in ("A", "B"):
                ids = [r[0] for r in con.execute(
                    "SELECT execution_id FROM sources_comparaison_raw_periode WHERE comparaison_id=? AND cote=? AND execution_id IS NOT NULL",
                    [comparison_id, side],
                ).fetchall()]
                if not ids:
                    continue
                ph = ",".join("?" for _ in ids)
                con.execute(f"""INSERT INTO occurrences_comparaison_raw
                    SELECT ?,?,p.table_source,p.execution_id,p.ligne_paie_id,p.ligne_source,
                           p.matricule_normalise,p.nom_normalise,p.nom,p.prenom,p.institution_id,p.regime,
                           p.section,p.categorie,p.grade,p.unite_affectation,p.province,
                           COALESCE(p.remuneration_brute_calculee,0),COALESCE(p.montant_net,0)
                    FROM paie_standardisee p
                    WHERE p.execution_id IN ({ph})""", [comparison_id, side] + ids)

    def _apply_occurrence_metrics(self, comparison_id: str) -> None:
        with self.db.connect() as con:
            con.execute("""CREATE OR REPLACE TEMP TABLE occ_a AS
                SELECT matricule_normalise,nom_normalise,
                       COUNT(*) lignes,
                       GREATEST(COUNT(*)-1,0) repetitions,
                       COUNT(DISTINCT execution_id) executions,
                       STRING_AGG(CAST(ligne_source AS VARCHAR), ', ' ORDER BY execution_id,ligne_source) numeros,
                       COUNT(DISTINCT COALESCE(brut,0)) montants_distincts
                FROM occurrences_comparaison_raw
                WHERE comparaison_id=? AND cote='A'
                GROUP BY matricule_normalise,nom_normalise""", [comparison_id])
            con.execute("""CREATE OR REPLACE TEMP TABLE occ_b AS
                SELECT matricule_normalise,nom_normalise,
                       COUNT(*) lignes,
                       GREATEST(COUNT(*)-1,0) repetitions,
                       COUNT(DISTINCT execution_id) executions,
                       STRING_AGG(CAST(ligne_source AS VARCHAR), ', ' ORDER BY execution_id,ligne_source) numeros,
                       COUNT(DISTINCT COALESCE(brut,0)) montants_distincts
                FROM occurrences_comparaison_raw
                WHERE comparaison_id=? AND cote='B'
                GROUP BY matricule_normalise,nom_normalise""", [comparison_id])

            con.execute("""UPDATE resultats_comparaison_raw_periode r SET
                lignes_source_a=COALESCE(a.lignes,0),
                occurrences_a=COALESCE(a.repetitions,0),
                executions_a=COALESCE(a.executions,0),
                numeros_lignes_a=a.numeros,
                montants_distincts_a=COALESCE(a.montants_distincts,0)
                FROM occ_a a
                WHERE r.comparaison_id=?
                  AND COALESCE(r.matricule_a,'')=COALESCE(a.matricule_normalise,'')
                  AND COALESCE(r.nom_norm_a,'')=COALESCE(a.nom_normalise,'')""", [comparison_id])
            con.execute("""UPDATE resultats_comparaison_raw_periode r SET
                lignes_source_b=COALESCE(b.lignes,0),
                occurrences_b=COALESCE(b.repetitions,0),
                executions_b=COALESCE(b.executions,0),
                numeros_lignes_b=b.numeros,
                montants_distincts_b=COALESCE(b.montants_distincts,0)
                FROM occ_b b
                WHERE r.comparaison_id=?
                  AND COALESCE(r.matricule_b,'')=COALESCE(b.matricule_normalise,'')
                  AND COALESCE(r.nom_norm_b,'')=COALESCE(b.nom_normalise,'')""", [comparison_id])

            con.execute("""UPDATE resultats_comparaison_raw_periode SET
                ecart_lignes=lignes_source_a-lignes_source_b,
                situation_occurrences=CASE
                    WHEN statut<>'COMMUN_PAR_MATRICULE_ET_NOM' THEN NULL
                    WHEN lignes_source_a<=1 AND lignes_source_b<=1 THEN 'COMMUN_EXACT_1_VS_1'
                    WHEN lignes_source_a>1 AND lignes_source_b<=1 THEN 'COMMUN_EXACT_REPETE_A'
                    WHEN lignes_source_a<=1 AND lignes_source_b>1 THEN 'COMMUN_EXACT_REPETE_B'
                    ELSE 'COMMUN_EXACT_REPETE_A_ET_B' END,
                diagnostic=TRIM(CONCAT_WS(' ; ',NULLIF(diagnostic,''),
                    CASE WHEN statut='COMMUN_PAR_MATRICULE_ET_NOM' AND lignes_source_a>1
                         THEN CAST(lignes_source_a AS VARCHAR)||' lignes source A ('||CAST(occurrences_a AS VARCHAR)||' répétition(s))' END,
                    CASE WHEN statut='COMMUN_PAR_MATRICULE_ET_NOM' AND lignes_source_b>1
                         THEN CAST(lignes_source_b AS VARCHAR)||' lignes source B ('||CAST(occurrences_b AS VARCHAR)||' répétition(s))' END,
                    CASE WHEN montants_distincts_a>1 THEN 'Montants différents entre occurrences A' END,
                    CASE WHEN montants_distincts_b>1 THEN 'Montants différents entre occurrences B' END
                ))
                WHERE comparaison_id=?""", [comparison_id])

    def occurrence_summary(self, comparison_id: str) -> dict:
        with self.db.connect() as con:
            row = con.execute("""SELECT
                SUM(CASE WHEN statut='COMMUN_PAR_MATRICULE_ET_NOM' THEN 1 ELSE 0 END),
                SUM(CASE WHEN situation_occurrences='COMMUN_EXACT_1_VS_1' THEN 1 ELSE 0 END),
                SUM(CASE WHEN situation_occurrences='COMMUN_EXACT_REPETE_A' THEN 1 ELSE 0 END),
                SUM(CASE WHEN situation_occurrences='COMMUN_EXACT_REPETE_B' THEN 1 ELSE 0 END),
                SUM(CASE WHEN situation_occurrences='COMMUN_EXACT_REPETE_A_ET_B' THEN 1 ELSE 0 END),
                SUM(CASE WHEN occurrences_a>0 THEN 1 ELSE 0 END),
                SUM(CASE WHEN occurrences_b>0 THEN 1 ELSE 0 END),
                COALESCE(SUM(occurrences_a),0),COALESCE(SUM(occurrences_b),0)
                FROM resultats_comparaison_raw_periode WHERE comparaison_id=?""", [comparison_id]).fetchone()
        keys = ["communs_exacts","communs_1_vs_1","communs_repetes_a","communs_repetes_b",
                "communs_repetes_a_b","identites_repetees_a","identites_repetees_b","repetitions_a","repetitions_b"]
        return dict(zip(keys, [int(v or 0) for v in row]))

    def list_occurrence_details(self, comparison_id: str, side: str, matricule: str, nom_normalise: str):
        side = side.upper()
        if side not in {"A", "B"}:
            raise ValueError("Côté invalide.")
        with self.db.connect() as con:
            return con.execute("""SELECT table_source,execution_id,ligne_source,matricule_normalise,nom,prenom,
                       institution_id,regime,section,categorie,grade,unite_affectation,province,brut,net
                FROM occurrences_comparaison_raw
                WHERE comparaison_id=? AND cote=?
                  AND COALESCE(matricule_normalise,'')=COALESCE(?, '')
                  AND COALESCE(nom_normalise,'')=COALESCE(?, '')
                ORDER BY execution_id,ligne_source""", [comparison_id,side,matricule,nom_normalise]).fetchall()
