from __future__ import annotations

import uuid

from .regime_comparison_runtime import RegimeComparisonService as RuntimeRegimeComparisonService


class StrictRegimeComparisonService(RuntimeRegimeComparisonService):
    """Comparaison regime vs regime avec identite stricte et ambiguite explicite."""

    STATUSES = [
        "COMMUN_IDENTIQUE",
        "COMMUN_PAR_NOM_PROBABLE",
        "ECART_FINANCIER",
        "ECART_ADMINISTRATIF",
        "ECART_FINANCIER_ET_ADMIN",
        "PAIEMENT_MULTIPLE",
        "DOUBLE_PAIEMENT_POTENTIEL",
        "IDENTITE_INCOHERENTE",
        "NOM_MATRICULE_DIFFERENT",
        "MATCH_AMBIGU_MATRICULE",
        "MATCH_AMBIGU_NOM",
        "UNIQUEMENT_REGIME_A",
        "UNIQUEMENT_REGIME_B",
    ]

    def run(self, institution_a: str, regime_a: str, institution_b: str, regime_b: str,
            quarter: str, year: int, threshold_amount: float = 0,
            threshold_percent: float = 0, progress=None) -> dict:
        if not all([institution_a, regime_a, institution_b, regime_b, quarter]):
            raise ValueError("Institution, régime et période sont obligatoires pour les deux côtés.")
        year = int(year)
        amount = float(threshold_amount or 0)
        percent = float(threshold_percent or 0)
        threshold_amount = amount if amount > 0 else 1e-9
        threshold_percent = percent if percent > 0 else 1e-9
        if institution_a == institution_b and regime_a == regime_b:
            raise ValueError("Choisissez deux périmètres différents à comparer.")

        rows_a = self.available_count(institution_a, regime_a, quarter, year)
        rows_b = self.available_count(institution_b, regime_b, quarter, year)
        if not rows_a:
            raise ValueError("Aucune donnée de paie n'est disponible pour le régime A.")
        if not rows_b:
            raise ValueError("Aucune donnée de paie n'est disponible pour le régime B.")

        comparison_id = str(uuid.uuid4())
        progress and progress(5, "Préparation de la comparaison stricte des régimes")
        with self.db.connect() as con:
            con.execute("""INSERT INTO comparaisons_regimes
                (comparaison_id,institution_a,regime_a,institution_b,regime_b,trimestre,annee,
                 seuil_montant,seuil_pourcentage,statut,lignes_a,lignes_b)
                VALUES (?,?,?,?,?,?,?,?,?,'EN_COURS',?,?)""",
                [comparison_id,institution_a,regime_a,institution_b,regime_b,quarter,year,
                 amount,percent,rows_a,rows_b])
            con.execute("BEGIN")
            try:
                progress and progress(20, "Agrégation par matricule + nom normalisés")
                for side, institution, regime in (("a", institution_a, regime_a), ("b", institution_b, regime_b)):
                    con.execute(f"""CREATE OR REPLACE TEMP TABLE cmp_{side} AS
                        SELECT matricule_normalise,nom_normalise,
                          MIN(matricule_source) matricule_source,
                          MIN(TRIM(COALESCE(nom,'') || ' ' || COALESCE(prenom,''))) nom_complet,
                          COUNT(*) occurrences,
                          SUM(COALESCE(remuneration_brute_calculee,0)) remuneration,
                          SUM(COALESCE(montant_net,0)) net,
                          STRING_AGG(DISTINCT NULLIF(grade,''), ', ') grade,
                          STRING_AGG(DISTINCT NULLIF(categorie,''), ', ') categorie,
                          STRING_AGG(DISTINCT NULLIF(unite_affectation,''), ', ') affectation,
                          STRING_AGG(DISTINCT NULLIF(province,''), ', ') province
                        FROM paie_standardisee
                        WHERE institution_id=? AND regime=? AND trimestre=? AND annee=?
                          AND (COALESCE(matricule_normalise,'') NOT IN ('','NU') OR COALESCE(nom_normalise,'')<>'')
                        GROUP BY matricule_normalise,nom_normalise""", [institution,regime,quarter,year])

                progress and progress(45, "Matching strict des identités")
                con.execute("""CREATE OR REPLACE TEMP TABLE cmp_pairs AS
                    WITH af AS (
                      SELECT a.*,
                        (SELECT COUNT(*) FROM cmp_b b WHERE COALESCE(a.matricule_normalise,'') NOT IN ('','NU')
                          AND b.matricule_normalise=a.matricule_normalise) nb_mat,
                        (SELECT COUNT(*) FROM cmp_b b WHERE COALESCE(a.nom_normalise,'')<>''
                          AND b.nom_normalise=a.nom_normalise) nb_nom,
                        EXISTS(SELECT 1 FROM cmp_b b WHERE COALESCE(a.matricule_normalise,'') NOT IN ('','NU')
                          AND COALESCE(a.nom_normalise,'')<>'' AND b.matricule_normalise=a.matricule_normalise
                          AND b.nom_normalise=a.nom_normalise) exact_match
                      FROM cmp_a a
                    ), chosen AS (
                      SELECT af.*,
                        CASE
                          WHEN exact_match THEN 'EXACT'
                          WHEN nb_mat>1 THEN 'AMBIGU_MATRICULE'
                          WHEN nb_mat=1 THEN 'MATRICULE_INCOHERENT'
                          WHEN nb_nom>1 THEN 'AMBIGU_NOM'
                          WHEN nb_nom=1 AND COALESCE(matricule_normalise,'') IN ('','NU') THEN 'NOM_PROBABLE'
                          WHEN nb_nom=1 AND COALESCE(matricule_normalise,'') NOT IN ('','NU') THEN 'NOM_MATRICULE_DIFFERENT'
                          ELSE 'AUCUN' END match_type
                      FROM af
                    )
                    SELECT c.*,
                      b.matricule_source b_matricule_source,b.matricule_normalise b_matricule_normalise,
                      b.nom_complet b_nom_complet,b.nom_normalise b_nom_normalise,b.occurrences b_occurrences,
                      b.remuneration b_remuneration,b.net b_net,b.grade b_grade,b.categorie b_categorie,
                      b.affectation b_affectation,b.province b_province
                    FROM chosen c
                    LEFT JOIN cmp_b b ON
                      (c.match_type='EXACT' AND b.matricule_normalise=c.matricule_normalise AND b.nom_normalise=c.nom_normalise)
                      OR (c.match_type='MATRICULE_INCOHERENT' AND b.matricule_normalise=c.matricule_normalise)
                      OR (c.match_type IN ('NOM_PROBABLE','NOM_MATRICULE_DIFFERENT') AND b.nom_normalise=c.nom_normalise)
                """)

                con.execute("""INSERT INTO resultats_comparaison_regimes
                    SELECT uuid(),?,
                      CASE WHEN p.match_type='EXACT' THEN 'MATRICULE+NOM'
                           WHEN p.match_type IN ('NOM_PROBABLE','NOM_MATRICULE_DIFFERENT','AMBIGU_NOM') THEN 'NOM'
                           WHEN p.match_type IN ('AMBIGU_MATRICULE','MATRICULE_INCOHERENT') THEN 'MATRICULE'
                           ELSE 'AUCUNE' END,
                      CASE WHEN COALESCE(p.matricule_normalise,'') NOT IN ('','NU') THEN 'M:'||p.matricule_normalise||':N:'||COALESCE(p.nom_normalise,'')
                           ELSE 'N:'||COALESCE(p.nom_normalise,'') END,
                      p.matricule_source,p.b_matricule_source,p.matricule_normalise,p.b_matricule_normalise,
                      p.nom_complet,p.b_nom_complet,p.nom_normalise,p.b_nom_normalise,
                      p.occurrences,CASE WHEN p.match_type IN ('EXACT','NOM_PROBABLE','MATRICULE_INCOHERENT','NOM_MATRICULE_DIFFERENT') THEN COALESCE(p.b_occurrences,0) ELSE 0 END,
                      p.remuneration,CASE WHEN p.match_type IN ('EXACT','NOM_PROBABLE') THEN COALESCE(p.b_remuneration,0) ELSE 0 END,
                      p.net,CASE WHEN p.match_type IN ('EXACT','NOM_PROBABLE') THEN COALESCE(p.b_net,0) ELSE 0 END,
                      CASE WHEN p.match_type IN ('EXACT','NOM_PROBABLE') THEN p.remuneration-COALESCE(p.b_remuneration,0) ELSE 0 END,
                      CASE WHEN p.match_type IN ('EXACT','NOM_PROBABLE') THEN p.net-COALESCE(p.b_net,0) ELSE 0 END,
                      CASE WHEN p.match_type IN ('EXACT','NOM_PROBABLE') THEN
                        100.0*ABS(p.remuneration-COALESCE(p.b_remuneration,0))/GREATEST(ABS(p.remuneration),ABS(COALESCE(p.b_remuneration,0)),1)
                        ELSE 0 END,
                      p.grade,CASE WHEN p.match_type IN ('EXACT','NOM_PROBABLE') THEN p.b_grade ELSE NULL END,
                      p.categorie,CASE WHEN p.match_type IN ('EXACT','NOM_PROBABLE') THEN p.b_categorie ELSE NULL END,
                      p.affectation,CASE WHEN p.match_type IN ('EXACT','NOM_PROBABLE') THEN p.b_affectation ELSE NULL END,
                      p.province,CASE WHEN p.match_type IN ('EXACT','NOM_PROBABLE') THEN p.b_province ELSE NULL END,
                      FALSE,FALSE,FALSE,
                      CASE
                        WHEN p.match_type='AMBIGU_MATRICULE' THEN 'MATCH_AMBIGU_MATRICULE'
                        WHEN p.match_type='AMBIGU_NOM' THEN 'MATCH_AMBIGU_NOM'
                        WHEN p.match_type='MATRICULE_INCOHERENT' THEN 'IDENTITE_INCOHERENTE'
                        WHEN p.match_type='NOM_MATRICULE_DIFFERENT' THEN 'NOM_MATRICULE_DIFFERENT'
                        WHEN p.match_type='NOM_PROBABLE' THEN 'COMMUN_PAR_NOM_PROBABLE'
                        WHEN p.match_type='AUCUN' THEN 'UNIQUEMENT_REGIME_A'
                        ELSE 'EN_COURS' END,
                      CASE
                        WHEN p.match_type='AMBIGU_MATRICULE' THEN 'Plusieurs identités du régime B portent ce matricule : aucun candidat choisi'
                        WHEN p.match_type='AMBIGU_NOM' THEN 'Plusieurs identités du régime B portent ce nom : aucun candidat choisi'
                        WHEN p.match_type='MATRICULE_INCOHERENT' THEN 'Même matricule mais nom normalisé différent : identité non confirmée'
                        WHEN p.match_type='NOM_MATRICULE_DIFFERENT' THEN 'Même nom normalisé mais matricule différent : identité non confirmée'
                        WHEN p.match_type='NOM_PROBABLE' THEN 'Correspondance probable par nom seul ; identité non certifiée par matricule'
                        WHEN p.match_type='AUCUN' THEN 'Absent du régime B selon les clés strictes'
                        ELSE 'Correspondance exacte : même matricule et même nom normalisés' END
                    FROM cmp_pairs p""", [comparison_id])

                con.execute("""INSERT INTO resultats_comparaison_regimes
                    SELECT uuid(),?,'AUCUNE',
                      CASE WHEN COALESCE(b.matricule_normalise,'') NOT IN ('','NU') THEN 'M:'||b.matricule_normalise||':N:'||COALESCE(b.nom_normalise,'') ELSE 'N:'||COALESCE(b.nom_normalise,'') END,
                      NULL,b.matricule_source,NULL,b.matricule_normalise,NULL,b.nom_complet,NULL,b.nom_normalise,
                      0,b.occurrences,0,b.remuneration,0,b.net,0,0,0,NULL,b.grade,NULL,b.categorie,NULL,b.affectation,NULL,b.province,
                      FALSE,FALSE,FALSE,'UNIQUEMENT_REGIME_B','Absent du régime A selon les clés strictes'
                    FROM cmp_b b
                    WHERE NOT EXISTS (
                      SELECT 1 FROM cmp_pairs p
                      WHERE (p.match_type='EXACT' AND p.matricule_normalise=b.matricule_normalise AND p.nom_normalise=b.nom_normalise)
                         OR (p.match_type='MATRICULE_INCOHERENT' AND p.matricule_normalise=b.matricule_normalise)
                         OR (p.match_type IN ('NOM_PROBABLE','NOM_MATRICULE_DIFFERENT') AND p.nom_normalise=b.nom_normalise)
                    )""", [comparison_id])

                progress and progress(70, "Classification des écarts sur identités fiables")
                con.execute("""UPDATE resultats_comparaison_regimes SET
                    ecart_financier = CASE WHEN statut='EN_COURS' AND occurrences_a>0 AND occurrences_b>0
                      THEN ABS(ecart_remuneration)>=? OR ABS(ecart_net)>=? OR ABS(ecart_pourcentage)>=? ELSE FALSE END,
                    ecart_administratif = CASE WHEN statut='EN_COURS' AND occurrences_a>0 AND occurrences_b>0
                      THEN COALESCE(grade_a,'')<>COALESCE(grade_b,'') OR COALESCE(categorie_a,'')<>COALESCE(categorie_b,'')
                        OR COALESCE(affectation_a,'')<>COALESCE(affectation_b,'') OR COALESCE(province_a,'')<>COALESCE(province_b,'')
                      ELSE FALSE END
                    WHERE comparaison_id=?""", [threshold_amount,threshold_amount,threshold_percent,comparison_id])

                con.execute("""UPDATE resultats_comparaison_regimes SET
                    double_paiement = CASE
                      WHEN statut='EN_COURS' AND occurrences_a>0 AND occurrences_b>0
                        AND remuneration_a<>0 AND remuneration_b<>0 THEN TRUE ELSE FALSE END,
                    diagnostic=TRIM(CONCAT_WS(' ; ',NULLIF(diagnostic,''),
                      CASE WHEN statut='EN_COURS' AND occurrences_a>0 AND occurrences_b>0
                        AND remuneration_a<>0 AND remuneration_b<>0 THEN 'Double paiement potentiel inter-régimes : identité exacte et rémunération présente des deux côtés' END,
                      CASE WHEN occurrences_a>1 THEN 'Occurrences multiples dans le régime A' END,
                      CASE WHEN occurrences_b>1 THEN 'Occurrences multiples dans le régime B' END,
                      CASE WHEN ecart_financier THEN 'Écart financier supérieur au seuil' END,
                      CASE WHEN ecart_administratif THEN 'Informations administratives différentes' END)),
                    statut=CASE
                      WHEN statut<>'EN_COURS' THEN statut
                      WHEN occurrences_a>1 OR occurrences_b>1 THEN 'PAIEMENT_MULTIPLE'
                      WHEN ecart_financier AND ecart_administratif THEN 'ECART_FINANCIER_ET_ADMIN'
                      WHEN ecart_financier THEN 'ECART_FINANCIER'
                      WHEN ecart_administratif THEN 'ECART_ADMINISTRATIF'
                      ELSE 'COMMUN_IDENTIQUE' END
                    WHERE comparaison_id=?""", [comparison_id])

                con.execute("""UPDATE resultats_comparaison_regimes SET statut='DOUBLE_PAIEMENT_POTENTIEL'
                    WHERE comparaison_id=? AND double_paiement AND statut='COMMUN_IDENTIQUE'""", [comparison_id])

                summary = con.execute("""SELECT
                    SUM(CASE WHEN occurrences_a>0 AND occurrences_b>0 AND cle_type='MATRICULE+NOM'
                      AND statut NOT IN ('MATCH_AMBIGU_MATRICULE','MATCH_AMBIGU_NOM','IDENTITE_INCOHERENTE','NOM_MATRICULE_DIFFERENT') THEN 1 ELSE 0 END),
                    SUM(CASE WHEN occurrences_a>0 AND occurrences_b=0 THEN 1 ELSE 0 END),
                    SUM(CASE WHEN occurrences_b>0 AND occurrences_a=0 THEN 1 ELSE 0 END),
                    SUM(CASE WHEN double_paiement THEN 1 ELSE 0 END),
                    SUM(CASE WHEN ecart_financier THEN 1 ELSE 0 END),
                    SUM(CASE WHEN ecart_administratif THEN 1 ELSE 0 END),
                    SUM(remuneration_a),SUM(remuneration_b)
                    FROM resultats_comparaison_regimes WHERE comparaison_id=?""", [comparison_id]).fetchone()
                con.execute("""UPDATE comparaisons_regimes SET statut='TERMINE',communs=?,uniquement_a=?,uniquement_b=?,
                    doubles=?,ecarts_financiers=?,ecarts_admin=?,masse_a=?,masse_b=?,termine_le=CURRENT_TIMESTAMP
                    WHERE comparaison_id=?""", [*(int(v or 0) for v in summary[:6]),summary[6] or 0,summary[7] or 0,comparison_id])
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                con.execute("UPDATE comparaisons_regimes SET statut='ERREUR',termine_le=CURRENT_TIMESTAMP WHERE comparaison_id=?", [comparison_id])
                raise

        progress and progress(100, "Comparaison stricte des régimes terminée")
        return self.get_summary(comparison_id)
