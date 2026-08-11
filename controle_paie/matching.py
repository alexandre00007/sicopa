from __future__ import annotations

import uuid
from typing import Callable, Optional

from .database import Database


class MatchingService:
    def __init__(self, database: Database):
        self.db = database

    def run(self, institution_id: str, regime: str, quarter: str, year: int,
            progress: Optional[Callable[[int, str], None]] = None) -> str:
        execution_id = str(uuid.uuid4())
        progress and progress(10, "Préparation du rapprochement")
        with self.db.connect() as con:
            con.execute("DELETE FROM resultats_rapprochement WHERE institution_id=? AND regime=? AND trimestre=? AND annee=? AND statut_validation='A_VALIDER'", [institution_id, regime, quarter, year])
            params = [institution_id, regime, quarter, year]
            filter_sql, filter_params = self.db.payroll_filter_clause(institution_id, regime)
            # One final classification per payroll line: matricule first, then name, then missing.
            con.execute("""
                INSERT INTO resultats_rapprochement
                WITH p AS (
                    SELECT *, ROW_NUMBER() OVER (PARTITION BY matricule_normalise ORDER BY ligne_source) AS rn_mat
                    FROM paie_standardisee WHERE institution_id=? AND regime=? AND trimestre=? AND annee=? {filter_sql}
                ), classified AS (
                    SELECT p.*,
                        (SELECT MIN(d.ligne_declaratif_id) FROM declaratif_standardise d WHERE d.institution_id=p.institution_id AND d.regime=p.regime AND d.trimestre=p.trimestre AND d.annee=p.annee AND d.matricule_normalise NOT IN ('','NU') AND d.matricule_normalise=p.matricule_normalise) AS by_mat,
                        (SELECT MIN(d.ligne_declaratif_id) FROM declaratif_standardise d WHERE d.institution_id=p.institution_id AND d.regime=p.regime AND d.trimestre=p.trimestre AND d.annee=p.annee AND d.nom_normalise<>'' AND d.nom_normalise=p.nom_normalise) AS by_name
                    FROM p
                )
                SELECT uuid(), ?, institution_id, regime, trimestre, annee, ligne_paie_id,
                    COALESCE(by_mat, by_name),
                    CASE WHEN by_mat IS NOT NULL THEN 'MATRICULE' WHEN by_name IS NOT NULL THEN 'NOM' ELSE 'AUCUNE' END,
                    CASE WHEN by_mat IS NOT NULL THEN 1.0 WHEN by_name IS NOT NULL THEN 0.8 ELSE 0.0 END,
                    CASE WHEN rn_mat>1 AND matricule_normalise NOT IN ('','NU') THEN 'DOUBLON_MATRICULE'
                         WHEN by_mat IS NOT NULL THEN 'CONFORME_MATRICULE'
                         WHEN by_name IS NOT NULL THEN 'CONFORME_NOM'
                         WHEN matricule_normalise IN ('','NU') THEN 'MATRICULE_MANQUANT'
                         ELSE 'PAYE_NON_DECLARE' END,
                    remuneration_brute_calculee,
                    CASE WHEN rn_mat>1 AND matricule_normalise NOT IN ('','NU') THEN remuneration_brute_calculee
                         WHEN by_mat IS NULL AND by_name IS NULL THEN remuneration_brute_calculee ELSE 0 END,
                    0, 'A_VALIDER', NULL, NULL, NULL
                FROM classified
            """.format(filter_sql=filter_sql), params + filter_params + [execution_id])
            # Declarations that matched no payroll line.
            con.execute("""
                INSERT INTO resultats_rapprochement
                SELECT uuid(), ?, d.institution_id,d.regime,d.trimestre,d.annee,NULL,d.ligne_declaratif_id,
                       'AUCUNE',0,'DECLARE_NON_PAYE',0,0,0,'A_VALIDER',NULL,NULL,NULL
                FROM declaratif_standardise d
                WHERE d.institution_id=? AND d.regime=? AND d.trimestre=? AND d.annee=?
                  AND NOT EXISTS (SELECT 1 FROM resultats_rapprochement r WHERE r.execution_id=? AND r.ligne_declaratif_id=d.ligne_declaratif_id)
            """, [execution_id] + params + [execution_id])
        progress and progress(100, "Rapprochement terminé")
        return execution_id
