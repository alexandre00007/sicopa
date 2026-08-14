from __future__ import annotations

from .raw_period_comparison_strict import StrictRawPeriodComparisonService


class AmbiguityAwareRawPeriodComparisonService(StrictRawPeriodComparisonService):
    """Ajoute une barriere stricte contre les choix arbitraires d'identite.

    Une correspondance par matricule ou par nom n'est exploitable que si elle
    designe un candidat unique du cote B. Sinon le resultat est marque ambigu
    et les valeurs B sont neutralisees pour interdire les comparaisons
    financieres ou administratives sur une identite non resolue.
    """

    def analyze(self, table_a: str, table_b: str, quarter: str, year: int, progress=None):
        info = super().analyze(table_a, table_b, quarter, year, progress=progress)
        progress and progress(88, "Controle strict des correspondances ambigues")
        self._mark_ambiguous_matches(info["id"])
        progress and progress(100, "Comparaison RAW stricte terminee")
        return self.get_comparison(info["id"])

    def _mark_ambiguous_matches(self, comparison_id: str) -> None:
        with self.db.connect() as con:
            # Matricule present dans B mais associe a plusieurs identites distinctes.
            con.execute("""UPDATE resultats_comparaison_raw_periode r SET
                    statut='MATCH_AMBIGU_MATRICULE',
                    matricule_b=NULL,nom_norm_b=NULL,nom_b=NULL,prenom_b=NULL,
                    regime_b=NULL,institution_b=NULL,occurrences_b=0,
                    brut_b=0,net_b=0,ecart_brut=0,ecart_net=0,
                    section_b=NULL,categorie_b=NULL,grade_b=NULL,unite_b=NULL,province_b=NULL,
                    diagnostic=TRIM(CONCAT_WS(' ; ',NULLIF(diagnostic,''),
                        'Match bloque : plusieurs identites B partagent ce matricule'))
                WHERE comparaison_id=? AND statut='COMMUN_PAR_MATRICULE'
                  AND COALESCE(matricule_a,'') NOT IN ('','NU')
                  AND (
                    SELECT COUNT(DISTINCT COALESCE(NULLIF(p.nom_normalise,''),'#VIDE#'))
                    FROM paie_standardisee p
                    WHERE p.execution_id IN (
                        SELECT execution_id FROM sources_comparaison_raw_periode
                        WHERE comparaison_id=r.comparaison_id AND cote='B' AND execution_id IS NOT NULL
                    )
                      AND p.matricule_normalise=r.matricule_a
                  ) > 1""", [comparison_id])

            # Nom present dans B mais associe a plusieurs matricules distincts.
            con.execute("""UPDATE resultats_comparaison_raw_periode r SET
                    statut='MATCH_AMBIGU_NOM',
                    matricule_b=NULL,nom_norm_b=NULL,nom_b=NULL,prenom_b=NULL,
                    regime_b=NULL,institution_b=NULL,occurrences_b=0,
                    brut_b=0,net_b=0,ecart_brut=0,ecart_net=0,
                    section_b=NULL,categorie_b=NULL,grade_b=NULL,unite_b=NULL,province_b=NULL,
                    diagnostic=TRIM(CONCAT_WS(' ; ',NULLIF(diagnostic,''),
                        'Match bloque : plusieurs matricules B partagent ce nom'))
                WHERE comparaison_id=? AND statut='COMMUN_PAR_NOM'
                  AND COALESCE(nom_norm_a,'')<>''
                  AND (
                    SELECT COUNT(DISTINCT COALESCE(NULLIF(p.matricule_normalise,''),'#VIDE#'))
                    FROM paie_standardisee p
                    WHERE p.execution_id IN (
                        SELECT execution_id FROM sources_comparaison_raw_periode
                        WHERE comparaison_id=r.comparaison_id AND cote='B' AND execution_id IS NOT NULL
                    )
                      AND p.nom_normalise=r.nom_norm_a
                  ) > 1""", [comparison_id])
