from __future__ import annotations

import uuid

from .identity_policy import (
    MATCH_AMBIGU_MATRICULE, MATCH_AMBIGU_NOM,
)
from .raw_period_comparison_fusion_aware import FusionAwareRawPeriodComparisonService


class PolicyRawPeriodComparisonService(FusionAwareRawPeriodComparisonService):
    """Matching RAW conforme à la politique centrale d'identité.

    Aucun MIN() n'est utilisé pour choisir une identité candidate. Si une clé
    retourne plusieurs candidats, le résultat reste ambigu et les valeurs B
    ne sont pas utilisées pour calculer des écarts.
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
        progress and progress(20, "Préparation des identités A et B")

        with self.db.connect() as con:
            con.execute("BEGIN")
            try:
                con.execute(
                    "INSERT INTO comparaisons_raw_periode VALUES (?,?,?,?,?,'EN_COURS',CURRENT_TIMESTAMP,NULL,NULL)",
                    [cmp_id, table_a, table_b, quarter, year],
                )
                for side, table, rows in (("A", table_a, ex_a), ("B", table_b, ex_b)):
                    for execution_id, institution, regime in rows:
                        con.execute("INSERT INTO sources_comparaison_raw_periode VALUES (?,?,?,?,?,?)",
                                    [cmp_id, side, table, execution_id, institution, regime])

                progress and progress(40, "Matching strict sans sélection arbitraire")
                params = ids_a + [quarter, year] + ids_b + [quarter, year] + [cmp_id]
                con.execute(f"""INSERT INTO resultats_comparaison_raw_periode (
                    comparaison_id,cle_resultat,statut,commun_matricule,commun_nom,
                    meme_matricule_nom_different,meme_nom_matricule_different,
                    matricule_a,matricule_b,nom_norm_a,nom_norm_b,nom_a,nom_b,prenom_a,prenom_b,
                    regime_a,regime_b,institution_a,institution_b,occurrences_a,occurrences_b,
                    brut_a,brut_b,net_a,net_b,ecart_brut,ecart_net,section_a,section_b,
                    categorie_a,categorie_b,grade_a,grade_b,unite_a,unite_b,province_a,province_b,
                    doublon_matricule_a,doublon_matricule_b,doublon_nom_a,doublon_nom_b,diagnostic
                )
                    WITH a0 AS (
                      SELECT matricule_normalise,nom_normalise,MIN(NULLIF(nom,'')) nom,MIN(NULLIF(prenom,'')) prenom,
                        STRING_AGG(DISTINCT COALESCE(regime,''), ', ') regime,
                        STRING_AGG(DISTINCT COALESCE(institution_id,''), ', ') institution,
                        COUNT(*) occ,SUM(COALESCE(remuneration_brute_calculee,0)) brut,SUM(COALESCE(montant_net,0)) net,
                        STRING_AGG(DISTINCT NULLIF(section,''), ', ') section,
                        STRING_AGG(DISTINCT NULLIF(categorie,''), ', ') categorie,
                        STRING_AGG(DISTINCT NULLIF(grade,''), ', ') grade,
                        STRING_AGG(DISTINCT NULLIF(unite_affectation,''), ', ') unite,
                        STRING_AGG(DISTINCT NULLIF(province,''), ', ') province
                      FROM paie_standardisee WHERE execution_id IN ({pha}) AND trimestre=? AND annee=?
                      GROUP BY matricule_normalise,nom_normalise
                    ), b0 AS (
                      SELECT matricule_normalise,nom_normalise,MIN(NULLIF(nom,'')) nom,MIN(NULLIF(prenom,'')) prenom,
                        STRING_AGG(DISTINCT COALESCE(regime,''), ', ') regime,
                        STRING_AGG(DISTINCT COALESCE(institution_id,''), ', ') institution,
                        COUNT(*) occ,SUM(COALESCE(remuneration_brute_calculee,0)) brut,SUM(COALESCE(montant_net,0)) net,
                        STRING_AGG(DISTINCT NULLIF(section,''), ', ') section,
                        STRING_AGG(DISTINCT NULLIF(categorie,''), ', ') categorie,
                        STRING_AGG(DISTINCT NULLIF(grade,''), ', ') grade,
                        STRING_AGG(DISTINCT NULLIF(unite_affectation,''), ', ') unite,
                        STRING_AGG(DISTINCT NULLIF(province,''), ', ') province
                      FROM paie_standardisee WHERE execution_id IN ({phb}) AND trimestre=? AND annee=?
                      GROUP BY matricule_normalise,nom_normalise
                    ), af AS (
                      SELECT a.*,
                        (SELECT COUNT(*) FROM b0 b WHERE COALESCE(a.matricule_normalise,'') NOT IN ('','NU')
                          AND COALESCE(a.nom_normalise,'')<>'' AND b.matricule_normalise=a.matricule_normalise
                          AND b.nom_normalise=a.nom_normalise) nb_exact,
                        (SELECT COUNT(*) FROM b0 b WHERE COALESCE(a.matricule_normalise,'') NOT IN ('','NU')
                          AND b.matricule_normalise=a.matricule_normalise) nb_mat,
                        (SELECT COUNT(*) FROM b0 b WHERE COALESCE(a.nom_normalise,'')<>''
                          AND b.nom_normalise=a.nom_normalise) nb_nom
                      FROM a0 a
                    ), chosen AS (
                      SELECT af.*,
                        CASE
                          WHEN nb_exact=1 THEN 'EXACT'
                          WHEN nb_mat>1 THEN 'AMBIGU_MATRICULE'
                          WHEN nb_mat=1 THEN 'MATRICULE_UNIQUE_NOM_DIFFERENT'
                          WHEN nb_nom>1 THEN 'AMBIGU_NOM'
                          WHEN nb_nom=1 THEN 'NOM_UNIQUE'
                          ELSE 'AUCUN' END match_type
                      FROM af
                    ), rows_a AS (
                      SELECT
                        CASE WHEN COALESCE(c.matricule_normalise,'') NOT IN ('','NU')
                          THEN 'A:M:'||c.matricule_normalise||':N:'||COALESCE(c.nom_normalise,'')
                          ELSE 'A:N:'||COALESCE(c.nom_normalise,'') END cle,
                        CASE
                          WHEN c.match_type='EXACT' THEN 'COMMUN_PAR_MATRICULE_ET_NOM'
                          WHEN c.match_type='AMBIGU_MATRICULE' THEN '{MATCH_AMBIGU_MATRICULE}'
                          WHEN c.match_type='MATRICULE_UNIQUE_NOM_DIFFERENT' THEN 'COMMUN_PAR_MATRICULE'
                          WHEN c.match_type='AMBIGU_NOM' THEN '{MATCH_AMBIGU_NOM}'
                          WHEN c.match_type='NOM_UNIQUE' THEN 'COMMUN_PAR_NOM'
                          ELSE 'UNIQUEMENT_A' END statut,
                        c.nb_mat>0 commun_matricule,c.nb_nom>0 commun_nom,
                        c.match_type='MATRICULE_UNIQUE_NOM_DIFFERENT' mat_nom_diff,
                        c.match_type='NOM_UNIQUE' AND COALESCE(c.matricule_normalise,'') NOT IN ('','NU')
                          AND COALESCE(b.matricule_normalise,'')<>COALESCE(c.matricule_normalise,'') nom_mat_diff,
                        c.matricule_normalise,c.nom_normalise,c.nom,c.prenom,c.regime,c.institution,c.occ,c.brut,c.net,
                        c.section,c.categorie,c.grade,c.unite,c.province,
                        b.matricule_normalise b_matricule,b.nom_normalise b_nom_norm,b.nom b_nom,b.prenom b_prenom,
                        b.regime b_regime,b.institution b_institution,b.occ b_occ,b.brut b_brut,b.net b_net,
                        b.section b_section,b.categorie b_categorie,b.grade b_grade,b.unite b_unite,b.province b_province,
                        c.match_type
                      FROM chosen c
                      LEFT JOIN b0 b ON
                        (c.match_type='EXACT' AND b.matricule_normalise=c.matricule_normalise AND b.nom_normalise=c.nom_normalise)
                        OR (c.match_type='MATRICULE_UNIQUE_NOM_DIFFERENT' AND b.matricule_normalise=c.matricule_normalise)
                        OR (c.match_type='NOM_UNIQUE' AND b.nom_normalise=c.nom_normalise)
                    ), rows_b_only AS (
                      SELECT 'B:'||COALESCE(NULLIF(b.matricule_normalise,''),'N:'||COALESCE(b.nom_normalise,'')) cle,
                        'UNIQUEMENT_B' statut,FALSE commun_matricule,FALSE commun_nom,FALSE mat_nom_diff,FALSE nom_mat_diff,
                        NULL matricule_normalise,NULL nom_normalise,NULL nom,NULL prenom,NULL regime,NULL institution,
                        0 occ,0 brut,0 net,NULL section,NULL categorie,NULL grade,NULL unite,NULL province,
                        b.matricule_normalise b_matricule,b.nom_normalise b_nom_norm,b.nom b_nom,b.prenom b_prenom,
                        b.regime b_regime,b.institution b_institution,b.occ b_occ,b.brut b_brut,b.net b_net,
                        b.section b_section,b.categorie b_categorie,b.grade b_grade,b.unite b_unite,b.province b_province,
                        'AUCUN' match_type
                      FROM b0 b WHERE NOT EXISTS (
                        SELECT 1 FROM a0 a WHERE
                          (COALESCE(a.matricule_normalise,'') NOT IN ('','NU') AND a.matricule_normalise=b.matricule_normalise)
                          OR (COALESCE(a.nom_normalise,'')<>'' AND a.nom_normalise=b.nom_normalise)
                      )
                    ), u AS (SELECT * FROM rows_a UNION ALL BY NAME SELECT * FROM rows_b_only)
                    SELECT ?,cle,statut,commun_matricule,commun_nom,mat_nom_diff,nom_mat_diff,
                      matricule_normalise,b_matricule,nom_normalise,b_nom_norm,nom,b_nom,prenom,b_prenom,
                      regime,b_regime,institution,b_institution,occ,b_occ,
                      brut,CASE WHEN match_type IN ('EXACT','MATRICULE_UNIQUE_NOM_DIFFERENT','NOM_UNIQUE') THEN COALESCE(b_brut,0) ELSE 0 END,
                      net,CASE WHEN match_type IN ('EXACT','MATRICULE_UNIQUE_NOM_DIFFERENT','NOM_UNIQUE') THEN COALESCE(b_net,0) ELSE 0 END,
                      CASE WHEN match_type IN ('EXACT','MATRICULE_UNIQUE_NOM_DIFFERENT','NOM_UNIQUE') THEN COALESCE(brut,0)-COALESCE(b_brut,0) ELSE 0 END,
                      CASE WHEN match_type IN ('EXACT','MATRICULE_UNIQUE_NOM_DIFFERENT','NOM_UNIQUE') THEN COALESCE(net,0)-COALESCE(b_net,0) ELSE 0 END,
                      section,b_section,categorie,b_categorie,grade,b_grade,unite,b_unite,province,b_province,
                      occ>1,COALESCE(b_occ,0)>1,
                      (SELECT COUNT(*) FROM a0 ax WHERE ax.nom_normalise=u.nom_normalise)>1,
                      (SELECT COUNT(*) FROM b0 bx WHERE bx.nom_normalise=u.b_nom_norm)>1,
                      TRIM(CONCAT_WS(' ; ',
                        CASE WHEN match_type='EXACT' THEN 'Correspondance exacte : même matricule et même nom normalisés' END,
                        CASE WHEN match_type='AMBIGU_MATRICULE' THEN 'Plusieurs candidats B pour ce matricule : aucun candidat choisi' END,
                        CASE WHEN match_type='MATRICULE_UNIQUE_NOM_DIFFERENT' THEN 'Même matricule avec nom différent : identité à vérifier' END,
                        CASE WHEN match_type='AMBIGU_NOM' THEN 'Plusieurs candidats B pour ce nom : aucun candidat choisi' END,
                        CASE WHEN match_type='NOM_UNIQUE' THEN 'Correspondance par nom unique seulement' END,
                        CASE WHEN nom_mat_diff THEN 'Même nom avec matricule différent' END
                      ))
                    FROM u""", params)

                progress and progress(85, "Finalisation de la comparaison")
                con.execute("UPDATE comparaisons_raw_periode SET statut='TERMINE',termine_le=CURRENT_TIMESTAMP WHERE comparaison_id=?", [cmp_id])
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise

        progress and progress(100, "Comparaison RAW terminée")
        return self.get_comparison(cmp_id)
