from __future__ import annotations

import uuid

from .raw_period_comparison_fusion_aware import FusionAwareRawPeriodComparisonService


class StrictRawPeriodComparisonService(FusionAwareRawPeriodComparisonService):
    """Comparaison RAW avec classification stricte des correspondances d'identite.

    COMMUN_PAR_MATRICULE_ET_NOM exige qu'une meme ligne agregee de B porte
    simultanement le meme matricule normalise et le meme nom normalise que A.
    """

    def analyze(self, table_a: str, table_b: str, quarter: str, year: int, progress=None):
        quarter = str(quarter).upper().strip()
        year = int(year)
        if table_a == table_b:
            raise ValueError("Sélectionnez deux tables RAW différentes.")
        if quarter not in {"T1", "T2", "T3", "T4"}:
            raise ValueError("Trimestre invalide.")

        progress and progress(5, "Vérification des sources et de la période")
        ex_a = self._executions(table_a, quarter, year)
        ex_b = self._executions(table_b, quarter, year)
        if not ex_a:
            raise ValueError(f"Aucune exécution exploitable pour {table_a} en {quarter} {year}.")
        if not ex_b:
            raise ValueError(f"Aucune exécution exploitable pour {table_b} en {quarter} {year}.")

        cmp_id = str(uuid.uuid4())
        ids_a = [r[0] for r in ex_a]
        ids_b = [r[0] for r in ex_b]
        pha = ",".join("?" for _ in ids_a)
        phb = ",".join("?" for _ in ids_b)
        progress and progress(20, "Préparation des agents A et B")

        with self.db.connect() as con:
            con.execute("BEGIN")
            try:
                con.execute(
                    "INSERT INTO comparaisons_raw_periode VALUES (?,?,?,?,?,'EN_COURS',CURRENT_TIMESTAMP,NULL,NULL)",
                    [cmp_id, table_a, table_b, quarter, year],
                )
                for side, table, rows in (("A", table_a, ex_a), ("B", table_b, ex_b)):
                    for execution_id, institution, regime in rows:
                        con.execute(
                            "INSERT INTO sources_comparaison_raw_periode VALUES (?,?,?,?,?,?)",
                            [cmp_id, side, table, execution_id, institution, regime],
                        )

                progress and progress(40, "Matching strict par matricule et par nom")
                params = ids_a + [quarter, year] + ids_b + [quarter, year] + [cmp_id]
                con.execute(
                    f"""INSERT INTO resultats_comparaison_raw_periode
                    WITH a0 AS (
                      SELECT matricule_normalise,nom_normalise,
                        MIN(NULLIF(nom,'')) nom,MIN(NULLIF(prenom,'')) prenom,
                        STRING_AGG(DISTINCT COALESCE(regime,''), ', ') regime,
                        STRING_AGG(DISTINCT COALESCE(institution_id,''), ', ') institution,
                        COUNT(*) occ,
                        SUM(COALESCE(remuneration_brute_calculee,0)) brut,
                        SUM(COALESCE(montant_net,0)) net,
                        STRING_AGG(DISTINCT NULLIF(section,''), ', ') section,
                        STRING_AGG(DISTINCT NULLIF(categorie,''), ', ') categorie,
                        STRING_AGG(DISTINCT NULLIF(grade,''), ', ') grade,
                        STRING_AGG(DISTINCT NULLIF(unite_affectation,''), ', ') unite,
                        STRING_AGG(DISTINCT NULLIF(province,''), ', ') province
                      FROM paie_standardisee
                      WHERE execution_id IN ({pha}) AND trimestre=? AND annee=?
                      GROUP BY matricule_normalise,nom_normalise
                    ), b0 AS (
                      SELECT matricule_normalise,nom_normalise,
                        MIN(NULLIF(nom,'')) nom,MIN(NULLIF(prenom,'')) prenom,
                        STRING_AGG(DISTINCT COALESCE(regime,''), ', ') regime,
                        STRING_AGG(DISTINCT COALESCE(institution_id,''), ', ') institution,
                        COUNT(*) occ,
                        SUM(COALESCE(remuneration_brute_calculee,0)) brut,
                        SUM(COALESCE(montant_net,0)) net,
                        STRING_AGG(DISTINCT NULLIF(section,''), ', ') section,
                        STRING_AGG(DISTINCT NULLIF(categorie,''), ', ') categorie,
                        STRING_AGG(DISTINCT NULLIF(grade,''), ', ') grade,
                        STRING_AGG(DISTINCT NULLIF(unite_affectation,''), ', ') unite,
                        STRING_AGG(DISTINCT NULLIF(province,''), ', ') province
                      FROM paie_standardisee
                      WHERE execution_id IN ({phb}) AND trimestre=? AND annee=?
                      GROUP BY matricule_normalise,nom_normalise
                    ), a_flags AS (
                      SELECT a.*,
                        EXISTS(
                          SELECT 1 FROM b0 b
                          WHERE COALESCE(a.matricule_normalise,'') NOT IN ('','NU')
                            AND COALESCE(a.nom_normalise,'')<>''
                            AND b.matricule_normalise=a.matricule_normalise
                            AND b.nom_normalise=a.nom_normalise
                        ) m_exact,
                        EXISTS(
                          SELECT 1 FROM b0 b
                          WHERE COALESCE(a.matricule_normalise,'') NOT IN ('','NU')
                            AND b.matricule_normalise=a.matricule_normalise
                        ) m_mat,
                        EXISTS(
                          SELECT 1 FROM b0 b
                          WHERE COALESCE(a.nom_normalise,'')<>''
                            AND b.nom_normalise=a.nom_normalise
                        ) m_nom
                      FROM a0 a
                    ), matched_a AS (
                      SELECT a.*,
                        CASE
                          WHEN a.m_exact THEN a.matricule_normalise
                          WHEN a.m_mat THEN a.matricule_normalise
                          WHEN a.m_nom THEN (
                            SELECT MIN(b.matricule_normalise) FROM b0 b
                            WHERE b.nom_normalise=a.nom_normalise
                          )
                        END bmat,
                        CASE
                          WHEN a.m_exact THEN a.nom_normalise
                          WHEN a.m_mat THEN (
                            SELECT MIN(b.nom_normalise) FROM b0 b
                            WHERE b.matricule_normalise=a.matricule_normalise
                          )
                          WHEN a.m_nom THEN a.nom_normalise
                        END bnom
                      FROM a_flags a
                    ), rows_a AS (
                      SELECT
                        CASE WHEN COALESCE(a.matricule_normalise,'') NOT IN ('','NU')
                             THEN 'A:M:'||a.matricule_normalise||':N:'||COALESCE(a.nom_normalise,'')
                             ELSE 'A:N:'||COALESCE(a.nom_normalise,'') END cle,
                        CASE WHEN a.m_exact THEN 'COMMUN_PAR_MATRICULE_ET_NOM'
                             WHEN a.m_mat THEN 'COMMUN_PAR_MATRICULE'
                             WHEN a.m_nom THEN 'COMMUN_PAR_NOM'
                             ELSE 'UNIQUEMENT_A' END statut,
                        a.m_mat commun_matricule,
                        a.m_nom commun_nom,
                        (a.m_mat AND NOT a.m_exact AND COALESCE(a.nom_normalise,'')<>''
                          AND EXISTS(
                            SELECT 1 FROM b0 x
                            WHERE x.matricule_normalise=a.matricule_normalise
                              AND COALESCE(x.nom_normalise,'')<>COALESCE(a.nom_normalise,'')
                          )) mat_nom_diff,
                        (a.m_nom AND NOT a.m_exact AND COALESCE(a.matricule_normalise,'') NOT IN ('','NU')
                          AND EXISTS(
                            SELECT 1 FROM b0 x
                            WHERE x.nom_normalise=a.nom_normalise
                              AND COALESCE(x.matricule_normalise,'')<>COALESCE(a.matricule_normalise,'')
                          )) nom_mat_diff,
                        a.m_exact,
                        a.matricule_normalise,a.nom_normalise,a.nom,a.prenom,a.regime,a.institution,a.occ,a.brut,a.net,
                        a.section,a.categorie,a.grade,a.unite,a.province,
                        b.matricule_normalise b_matricule,b.nom_normalise b_nom_norm,b.nom b_nom,b.prenom b_prenom,
                        b.regime b_regime,b.institution b_institution,b.occ b_occ,b.brut b_brut,b.net b_net,
                        b.section b_section,b.categorie b_categorie,b.grade b_grade,b.unite b_unite,b.province b_province
                      FROM matched_a a
                      LEFT JOIN b0 b
                        ON b.matricule_normalise=a.bmat AND b.nom_normalise=a.bnom
                    ), rows_b_only AS (
                      SELECT
                        'B:'||COALESCE(NULLIF(b.matricule_normalise,''),'N:'||COALESCE(b.nom_normalise,'')) cle,
                        'UNIQUEMENT_B' statut,
                        FALSE commun_matricule,FALSE commun_nom,FALSE mat_nom_diff,FALSE nom_mat_diff,FALSE m_exact,
                        NULL matricule_normalise,NULL nom_normalise,NULL nom,NULL prenom,NULL regime,NULL institution,
                        0 occ,0 brut,0 net,NULL section,NULL categorie,NULL grade,NULL unite,NULL province,
                        b.matricule_normalise b_matricule,b.nom_normalise b_nom_norm,b.nom b_nom,b.prenom b_prenom,
                        b.regime b_regime,b.institution b_institution,b.occ b_occ,b.brut b_brut,b.net b_net,
                        b.section b_section,b.categorie b_categorie,b.grade b_grade,b.unite b_unite,b.province b_province
                      FROM b0 b
                      WHERE NOT EXISTS (
                        SELECT 1 FROM a0 a
                        WHERE (COALESCE(a.matricule_normalise,'') NOT IN ('','NU') AND a.matricule_normalise=b.matricule_normalise)
                           OR (COALESCE(a.nom_normalise,'')<>'' AND a.nom_normalise=b.nom_normalise)
                      )
                    ), u AS (
                      SELECT * FROM rows_a
                      UNION ALL BY NAME
                      SELECT * FROM rows_b_only
                    )
                    SELECT ?,cle,statut,commun_matricule,commun_nom,mat_nom_diff,nom_mat_diff,
                      matricule_normalise,b_matricule,nom_normalise,b_nom_norm,nom,b_nom,prenom,b_prenom,
                      regime,b_regime,institution,b_institution,occ,b_occ,brut,b_brut,net,b_net,
                      COALESCE(brut,0)-COALESCE(b_brut,0),COALESCE(net,0)-COALESCE(b_net,0),
                      section,b_section,categorie,b_categorie,grade,b_grade,unite,b_unite,province,b_province,
                      occ>1,b_occ>1,
                      (SELECT COUNT(*) FROM a0 ax WHERE ax.nom_normalise=u.nom_normalise)>1,
                      (SELECT COUNT(*) FROM b0 bx WHERE bx.nom_normalise=u.b_nom_norm)>1,
                      TRIM(CONCAT_WS(' ; ',
                        CASE WHEN m_exact THEN 'Correspondance exacte : même matricule et même nom normalisés' END,
                        CASE WHEN commun_matricule AND NOT m_exact THEN 'Présent dans A et B par matricule uniquement' END,
                        CASE WHEN commun_nom AND NOT m_exact THEN 'Présent dans A et B par nom uniquement' END,
                        CASE WHEN mat_nom_diff THEN 'Même matricule avec nom différent' END,
                        CASE WHEN nom_mat_diff THEN 'Même nom avec matricule différent' END,
                        CASE WHEN COALESCE(brut,0)<>COALESCE(b_brut,0) AND (commun_matricule OR commun_nom) THEN 'Écart brut' END,
                        CASE WHEN COALESCE(section,'')<>COALESCE(b_section,'') AND (commun_matricule OR commun_nom) THEN 'Section différente' END,
                        CASE WHEN COALESCE(unite,'')<>COALESCE(b_unite,'') AND (commun_matricule OR commun_nom) THEN 'Unité d’affectation différente' END
                      ))
                    FROM u""",
                    params,
                )

                progress and progress(80, "Calcul des écarts et doublons")
                con.execute(
                    "UPDATE comparaisons_raw_periode SET statut='TERMINE',termine_le=CURRENT_TIMESTAMP WHERE comparaison_id=?",
                    [cmp_id],
                )
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise

        progress and progress(100, "Comparaison RAW terminée")
        return self.get_comparison(cmp_id)
