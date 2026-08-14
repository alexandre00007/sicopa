from __future__ import annotations

import uuid
from typing import Callable, Optional

from .database import Database


class MatchingService:
    """Rapprochement paie/declaratif avec refus des correspondances ambigues."""

    def __init__(self, database: Database):
        self.db = database

    def run(self, institution_id: str, regime: str, quarter: str, year: int,
            progress: Optional[Callable[[int, str], None]] = None,
            impact_formula_id: str = "") -> str:
        execution_id = str(uuid.uuid4())
        progress and progress(10, "Préparation du rapprochement")
        if impact_formula_id:
            self.db.selected_impact_formula(impact_formula_id, institution_id, regime, quarter, year)

        filter_sql, filter_params = self.db.payroll_filter_clause(institution_id, regime)
        rubrics = ["DOUBLON_MATRICULE", "CONFORME_MATRICULE", "CONFORME_NOM", "MATRICULE_MANQUANT", "PAYE_NON_DECLARE"]
        formulas = {
            rubric: self.db.impact_sql(
                institution_id, regime, quarter, year, rubric, "", "rn_mat", formula_id=impact_formula_id
            )
            for rubric in rubrics
        }

        def expr(rubric):
            return formulas[rubric][0]

        def fid(rubric):
            return "'" + str(formulas[rubric][1]["id"]).replace("'", "''") + "'"

        # Les correspondances ambigues ne recoivent aucun impact automatique.
        impact_case = f"""CASE
            WHEN rn_mat>1 AND matricule_normalise NOT IN ('','NU') THEN {expr('DOUBLON_MATRICULE')}
            WHEN mat_candidates>1 THEN 0
            WHEN by_mat IS NOT NULL THEN {expr('CONFORME_MATRICULE')}
            WHEN name_candidates>1 THEN 0
            WHEN by_name IS NOT NULL THEN {expr('CONFORME_NOM')}
            WHEN matricule_normalise IN ('','NU') THEN {expr('MATRICULE_MANQUANT')}
            ELSE {expr('PAYE_NON_DECLARE')} END"""
        formula_case = f"""CASE
            WHEN rn_mat>1 AND matricule_normalise NOT IN ('','NU') THEN {fid('DOUBLON_MATRICULE')}
            WHEN mat_candidates>1 THEN NULL
            WHEN by_mat IS NOT NULL THEN {fid('CONFORME_MATRICULE')}
            WHEN name_candidates>1 THEN NULL
            WHEN by_name IS NOT NULL THEN {fid('CONFORME_NOM')}
            WHEN matricule_normalise IN ('','NU') THEN {fid('MATRICULE_MANQUANT')}
            ELSE {fid('PAYE_NON_DECLARE')} END"""
        mass_expr, _ = self.db.impact_sql(institution_id, regime, quarter, year, "*", "", "rn_mat")

        with self.db.connect() as con:
            params = [institution_id, regime, quarter, year]
            con.execute("BEGIN")
            try:
                con.execute(
                    "DELETE FROM resultats_rapprochement WHERE institution_id=? AND regime=? AND trimestre=? AND annee=? AND statut_validation='A_VALIDER'",
                    params,
                )
                progress and progress(35, "Indexation stricte des identifiants déclaratifs")
                con.execute(
                    f"""
                    INSERT INTO resultats_rapprochement (
                        rapprochement_id,execution_id,institution_id,regime,trimestre,annee,
                        ligne_paie_id,ligne_declaratif_id,methode_correspondance,score_correspondance,
                        statut_rapprochement,masse_financiere_controlee,impact_potentiel,impact_confirme,
                        statut_validation,commentaire_validation,date_validation,validateur,formule_impact_id
                    )
                    WITH p AS (
                        SELECT *,ROW_NUMBER() OVER(PARTITION BY matricule_normalise ORDER BY ligne_source) rn_mat
                        FROM paie_standardisee
                        WHERE institution_id=? AND regime=? AND trimestre=? AND annee=? {filter_sql}
                    ),
                    d_mat AS (
                        SELECT matricule_normalise,
                               CASE WHEN COUNT(*)=1 THEN MIN(ligne_declaratif_id) END by_mat,
                               COUNT(*) mat_candidates
                        FROM declaratif_standardise
                        WHERE institution_id=? AND regime=? AND trimestre=? AND annee=?
                          AND matricule_normalise NOT IN ('','NU')
                        GROUP BY matricule_normalise
                    ),
                    d_name AS (
                        SELECT nom_normalise,
                               CASE WHEN COUNT(*)=1 THEN MIN(ligne_declaratif_id) END by_name,
                               COUNT(*) name_candidates
                        FROM declaratif_standardise
                        WHERE institution_id=? AND regime=? AND trimestre=? AND annee=?
                          AND nom_normalise<>''
                        GROUP BY nom_normalise
                    ),
                    classified AS (
                        SELECT p.*,
                               dm.by_mat,COALESCE(dm.mat_candidates,0) mat_candidates,
                               dn.by_name,COALESCE(dn.name_candidates,0) name_candidates
                        FROM p
                        LEFT JOIN d_mat dm USING(matricule_normalise)
                        LEFT JOIN d_name dn USING(nom_normalise)
                    )
                    SELECT uuid(),?,institution_id,regime,trimestre,annee,ligne_paie_id,
                        CASE
                            WHEN mat_candidates>1 THEN NULL
                            WHEN by_mat IS NOT NULL THEN by_mat
                            WHEN name_candidates>1 THEN NULL
                            ELSE by_name
                        END,
                        CASE
                            WHEN mat_candidates>1 THEN 'AMBIGU_MATRICULE'
                            WHEN by_mat IS NOT NULL THEN 'MATRICULE'
                            WHEN name_candidates>1 THEN 'AMBIGU_NOM'
                            WHEN by_name IS NOT NULL THEN 'NOM'
                            ELSE 'AUCUNE'
                        END,
                        CASE WHEN by_mat IS NOT NULL THEN 1.0 WHEN by_name IS NOT NULL THEN 0.8 ELSE 0.0 END,
                        CASE
                            WHEN rn_mat>1 AND matricule_normalise NOT IN ('','NU') THEN 'DOUBLON_MATRICULE'
                            WHEN mat_candidates>1 THEN 'MATCH_AMBIGU_MATRICULE'
                            WHEN by_mat IS NOT NULL THEN 'CONFORME_MATRICULE'
                            WHEN name_candidates>1 THEN 'MATCH_AMBIGU_NOM'
                            WHEN by_name IS NOT NULL THEN 'CONFORME_NOM'
                            WHEN matricule_normalise IN ('','NU') THEN 'MATRICULE_MANQUANT'
                            ELSE 'PAYE_NON_DECLARE'
                        END,
                        {mass_expr},{impact_case},0,'A_VALIDER',
                        CASE
                            WHEN mat_candidates>1 THEN 'Plusieurs lignes déclaratives portent ce matricule : validation manuelle obligatoire.'
                            WHEN name_candidates>1 AND by_mat IS NULL THEN 'Plusieurs lignes déclaratives portent ce nom : validation manuelle obligatoire.'
                            ELSE NULL
                        END,
                        NULL,NULL,{formula_case}
                    FROM classified
                    """,
                    params + filter_params + params + params + [execution_id],
                )

                progress and progress(85, "Identification prudente des déclarés non payés")
                con.execute(
                    """INSERT INTO resultats_rapprochement (
                        rapprochement_id,execution_id,institution_id,regime,trimestre,annee,
                        ligne_paie_id,ligne_declaratif_id,methode_correspondance,score_correspondance,
                        statut_rapprochement,masse_financiere_controlee,impact_potentiel,impact_confirme,
                        statut_validation,commentaire_validation,date_validation,validateur,formule_impact_id
                    )
                    SELECT uuid(),?,d.institution_id,d.regime,d.trimestre,d.annee,NULL,d.ligne_declaratif_id,
                           'AUCUNE',0,'DECLARE_NON_PAYE',0,0,0,'A_VALIDER',NULL,NULL,NULL,NULL
                    FROM declaratif_standardise d
                    WHERE d.institution_id=? AND d.regime=? AND d.trimestre=? AND d.annee=?
                      AND NOT EXISTS (
                          SELECT 1 FROM resultats_rapprochement r
                          WHERE r.execution_id=? AND r.ligne_declaratif_id=d.ligne_declaratif_id
                      )
                      AND NOT EXISTS (
                          SELECT 1 FROM paie_standardisee p
                          WHERE p.institution_id=d.institution_id AND p.regime=d.regime
                            AND p.trimestre=d.trimestre AND p.annee=d.annee
                            AND (
                                (COALESCE(d.matricule_normalise,'') NOT IN ('','NU') AND p.matricule_normalise=d.matricule_normalise)
                                OR (COALESCE(d.nom_normalise,'')<>'' AND p.nom_normalise=d.nom_normalise)
                            )
                      )""",
                    [execution_id] + params + [execution_id],
                )
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise

        progress and progress(100, "Rapprochement strict terminé")
        return execution_id
