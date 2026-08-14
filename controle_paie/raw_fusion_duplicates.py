from __future__ import annotations

from .raw_fusion_period import PeriodAwareRawFusionService


class DuplicateAwareRawFusionService(PeriodAwareRawFusionService):
    """Enrichit l'analyse de fusion avec doublons par matricule/nom et réanalyse."""

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

    def _source_executions(self, table_names, quarter, year):
        placeholders = ",".join("?" for _ in table_names)
        with self.db.connect() as con:
            return con.execute(f"""SELECT DISTINCT table_destination,execution_id,institution_id,regime
                FROM journal_executions
                WHERE table_destination IN ({placeholders})
                  AND type_operation='IMPORT_ACCESS'
                  AND trimestre=? AND annee=?
                  AND statut IN ('TERMINE','TERMINE_AVEC_AVERTISSEMENTS')
                  AND execution_id IS NOT NULL""", table_names + [quarter, int(year)]).fetchall()

    def create_fusion(self, table_names, quarter, year, suffix="", progress=None):
        info = super().create_fusion(table_names, quarter, year, suffix, progress=progress)
        progress and progress(92, "Recherche des doublons par matricule et par nom")
        self._compute_duplicates(info["id"])
        progress and progress(100, "Fusion et analyse multi-régimes terminées")
        return info

    def _execution_ids(self, fusion_id):
        with self.db.connect() as con:
            return [r[0] for r in con.execute(
                "SELECT DISTINCT execution_id FROM sources_fusion_raw WHERE fusion_id=? AND execution_id IS NOT NULL",
                [fusion_id],
            ).fetchall()]

    def _compute_duplicates(self, fusion_id: str) -> None:
        execution_ids = self._execution_ids(fusion_id)
        if not execution_ids:
            return
        ph = ",".join("?" for _ in execution_ids)
        with self.db.connect() as con:
            con.execute("DELETE FROM resultats_fusion_doublons WHERE fusion_id=?", [fusion_id])
            con.execute(f"""INSERT INTO resultats_fusion_doublons
                WITH base AS (
                    SELECT matricule_normalise,nom_normalise
                    FROM paie_standardisee WHERE execution_id IN ({ph})
                ), mat_counts AS (
                    SELECT matricule_normalise,COUNT(*) n FROM base
                    WHERE COALESCE(matricule_normalise,'') NOT IN ('','NU')
                    GROUP BY matricule_normalise
                ), nom_counts AS (
                    SELECT nom_normalise,COUNT(*) n FROM base
                    WHERE COALESCE(nom_normalise,'')<>'' GROUP BY nom_normalise
                )
                SELECT ?,r.person_key,COALESCE(mc.n,0)>1,COALESCE(nc.n,0)>1,
                       COALESCE(mc.n,0),COALESCE(nc.n,0)
                FROM resultats_fusion_multi r
                LEFT JOIN mat_counts mc ON mc.matricule_normalise=r.matricule_normalise
                LEFT JOIN nom_counts nc ON nc.nom_normalise=r.nom_normalise
                WHERE r.fusion_id=?""", execution_ids + [fusion_id, fusion_id])

    def reanalyze(self, fusion_id: str, progress=None) -> dict:
        info = self.get_fusion(fusion_id)
        execution_ids = self._execution_ids(fusion_id)
        if not execution_ids:
            raise ValueError("Aucune exécution source n'est disponible pour réanalyser cette fusion.")
        progress and progress(10, "Préparation de la réanalyse")
        ph = ",".join("?" for _ in execution_ids)
        quarter, year = info["quarter"], int(info["year"])
        with self.db.connect() as con:
            con.execute("BEGIN")
            try:
                con.execute("DELETE FROM resultats_fusion_multi WHERE fusion_id=?", [fusion_id])
                con.execute("DELETE FROM resultats_fusion_doublons WHERE fusion_id=?", [fusion_id])
                progress and progress(35, "Recalcul des agents et régimes")
                con.execute(f"""INSERT INTO resultats_fusion_multi
                    WITH base AS (
                        SELECT p.*,CASE WHEN COALESCE(matricule_normalise,'') NOT IN ('','NU')
                          THEN 'M:'||matricule_normalise WHEN COALESCE(nom_normalise,'')<>''
                          THEN 'N:'||nom_normalise ELSE 'L:'||ligne_paie_id END person_key
                        FROM paie_standardisee p
                        WHERE execution_id IN ({ph}) AND trimestre=? AND annee=?
                    ), per_regime AS (
                        SELECT person_key,regime,COUNT(*) n FROM base GROUP BY person_key,regime
                    ), stats AS (
                        SELECT b.person_key,MIN(NULLIF(b.matricule_normalise,'')) matricule_normalise,
                          MIN(NULLIF(b.nom_normalise,'')) nom_normalise,MIN(NULLIF(b.nom,'')) nom,
                          MIN(NULLIF(b.prenom,'')) prenom,
                          STRING_AGG(DISTINCT COALESCE(b.regime,''), ', ' ORDER BY COALESCE(b.regime,'')) regimes,
                          STRING_AGG(DISTINCT COALESCE(b.institution_id,''), ', ' ORDER BY COALESCE(b.institution_id,'')) institutions,
                          COUNT(DISTINCT b.regime) nb_regimes,COUNT(DISTINCT b.institution_id) nb_institutions,
                          COUNT(*) occurrences,SUM(COALESCE(b.remuneration_brute_calculee,0)) masse_brute,
                          SUM(COALESCE(b.montant_net,0)) masse_net,SUM(COALESCE(b.remuneration_base,0)) remuneration_base,
                          SUM(COALESCE(b.transport,0)) transport,SUM(COALESCE(b.prime,0)) prime,
                          SUM(COALESCE(b.logement,0)) logement,SUM(COALESCE(b.pension_rente,0)) pension_rente,
                          SUM(COALESCE(b.autres_remunerations,0)) autres_remunerations,SUM(COALESCE(b.retenues,0)) retenues,
                          STRING_AGG(DISTINCT NULLIF(b.section,''), ', ' ORDER BY NULLIF(b.section,'')) sections,
                          STRING_AGG(DISTINCT NULLIF(b.categorie,''), ', ' ORDER BY NULLIF(b.categorie,'')) categories,
                          STRING_AGG(DISTINCT NULLIF(b.grade,''), ', ' ORDER BY NULLIF(b.grade,'')) grades,
                          STRING_AGG(DISTINCT NULLIF(b.unite_affectation,''), ', ' ORDER BY NULLIF(b.unite_affectation,'')) unites,
                          STRING_AGG(DISTINCT NULLIF(b.province,''), ', ' ORDER BY NULLIF(b.province,'')) provinces,
                          COUNT(DISTINCT COALESCE(b.nom_normalise,'')) noms_distincts,MAX(pr.n) max_occ_regime
                        FROM base b JOIN per_regime pr ON pr.person_key=b.person_key AND pr.regime=b.regime
                        GROUP BY b.person_key
                    )
                    SELECT ?,person_key,matricule_normalise,nom_normalise,nom,prenom,regimes,institutions,
                      nb_regimes,nb_institutions,occurrences,masse_brute,masse_net,remuneration_base,transport,prime,
                      logement,pension_rente,autres_remunerations,retenues,sections,categories,grades,unites,provinces,
                      nb_regimes>1,max_occ_regime>1,noms_distincts>1,
                      CASE WHEN noms_distincts>1 THEN 'IDENTITE_INCOHERENTE'
                        WHEN nb_regimes>=3 THEN 'TROIS_REGIMES_OU_PLUS'
                        WHEN nb_regimes=2 THEN 'DEUX_REGIMES'
                        WHEN max_occ_regime>1 THEN 'PAIEMENT_MULTIPLE_MEME_REGIME'
                        WHEN nb_institutions>1 THEN 'PLUSIEURS_INSTITUTIONS' ELSE 'UN_SEUL_REGIME' END,
                      TRIM(CONCAT_WS(' ; ',CASE WHEN nb_regimes>1 THEN CAST(nb_regimes AS VARCHAR)||' régimes' END,
                        CASE WHEN max_occ_regime>1 THEN 'Plusieurs paiements dans un même régime' END,
                        CASE WHEN nb_institutions>1 THEN CAST(nb_institutions AS VARCHAR)||' institutions' END,
                        CASE WHEN noms_distincts>1 THEN 'Même clé associée à plusieurs identités' END))
                    FROM stats""", execution_ids + [quarter, year, fusion_id])
                con.execute("UPDATE fusions_raw SET statut='TERMINE',termine_le=CURRENT_TIMESTAMP WHERE fusion_id=?", [fusion_id])
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
        progress and progress(80, "Recherche des doublons matricule et nom")
        self._compute_duplicates(fusion_id)
        progress and progress(100, "Réanalyse terminée")
        return self.get_fusion(fusion_id)

    def list_results(self, fusion_id: str, status: str = "", limit: int = 3000) -> list[tuple]:
        condition = "r.fusion_id=?"; params = [fusion_id]
        if status == "DOUBLON_MATRICULE": condition += " AND COALESCE(d.doublon_matricule,FALSE)"
        elif status == "DOUBLON_NOM": condition += " AND COALESCE(d.doublon_nom,FALSE)"
        elif status: condition += " AND r.statut=?"; params.append(status)
        params.append(max(1,min(int(limit),10000)))
        with self.db.connect() as con:
            return con.execute(f"""SELECT r.statut,r.matricule_normalise,r.nom,r.prenom,r.regimes,r.nb_regimes,r.nb_institutions,
                r.occurrences,r.masse_brute,r.masse_net,r.sections,r.categories,r.grades,r.unites_affectation,r.provinces,
                r.paiement_multi_regime,r.paiement_multiple_meme_regime,r.identite_incoherente,
                TRIM(CONCAT_WS(' ; ',NULLIF(r.diagnostic,''),
                  CASE WHEN COALESCE(d.doublon_matricule,FALSE) THEN 'Doublon matricule ('||CAST(d.occurrences_matricule AS VARCHAR)||' occurrences)' END,
                  CASE WHEN COALESCE(d.doublon_nom,FALSE) THEN 'Doublon nom ('||CAST(d.occurrences_nom AS VARCHAR)||' occurrences)' END))
                FROM resultats_fusion_multi r LEFT JOIN resultats_fusion_doublons d
                  ON d.fusion_id=r.fusion_id AND d.person_key=r.person_key
                WHERE {condition} ORDER BY r.nb_regimes DESC,r.occurrences DESC,r.masse_brute DESC LIMIT ?""", params).fetchall()

    def summary(self, fusion_id: str) -> list[tuple]:
        rows = list(super().summary(fusion_id))
        with self.db.connect() as con:
            extra = con.execute("""SELECT 'DOUBLON_MATRICULE',COUNT(*),COALESCE(SUM(r.occurrences),0),
                       COALESCE(SUM(r.masse_brute),0),COALESCE(SUM(r.masse_net),0)
                    FROM resultats_fusion_doublons d JOIN resultats_fusion_multi r USING(fusion_id,person_key)
                    WHERE d.fusion_id=? AND d.doublon_matricule
                    UNION ALL SELECT 'DOUBLON_NOM',COUNT(*),COALESCE(SUM(r.occurrences),0),
                       COALESCE(SUM(r.masse_brute),0),COALESCE(SUM(r.masse_net),0)
                    FROM resultats_fusion_doublons d JOIN resultats_fusion_multi r USING(fusion_id,person_key)
                    WHERE d.fusion_id=? AND d.doublon_nom""", [fusion_id,fusion_id]).fetchall()
        return rows + [row for row in extra if int(row[1] or 0)>0]

    def delete_fusion(self, fusion_id: str) -> None:
        with self.db.connect() as con:
            con.execute("DELETE FROM resultats_fusion_doublons WHERE fusion_id=?", [fusion_id])
        return super().delete_fusion(fusion_id)
