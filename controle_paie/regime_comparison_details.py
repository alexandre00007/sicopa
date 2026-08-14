from __future__ import annotations


DETAIL_HEADERS = [
    "Statut", "Clé de rapprochement", "Type de clé", "Diagnostic",
    "Matricule A", "Matricule normalisé A", "Nom A", "Prénom A", "Nom normalisé A",
    "Section A", "Catégorie A", "Grade A", "Unité d'affectation A", "Province A",
    "Occurrences A", "Rémunération base A", "Transport A", "Prime A", "Logement A",
    "Pension / rente A", "Autres rémunérations A", "Retenues A", "Montant net A",
    "Rémunération brute calculée A", "Table source A", "Exécutions A", "Composantes supplémentaires A",
    "Matricule B", "Matricule normalisé B", "Nom B", "Prénom B", "Nom normalisé B",
    "Section B", "Catégorie B", "Grade B", "Unité d'affectation B", "Province B",
    "Occurrences B", "Rémunération base B", "Transport B", "Prime B", "Logement B",
    "Pension / rente B", "Autres rémunérations B", "Retenues B", "Montant net B",
    "Rémunération brute calculée B", "Table source B", "Exécutions B", "Composantes supplémentaires B",
    "Écart rémunération brute", "Écart montant net", "Écart %", "Payé dans les deux",
]


def list_detailed_results(service, comparison_id: str, status: str = "", limit: int = 10000) -> list[tuple]:
    """Retourne une annexe A/B enrichie avec les colonnes standardisées disponibles dans la paie."""
    summary = service.get_summary(comparison_id)
    params = [
        summary["institution_a"], summary["regime_a"], summary["quarter"], int(summary["year"]),
        summary["institution_b"], summary["regime_b"], summary["quarter"], int(summary["year"]),
        comparison_id,
    ]
    status_clause = ""
    if status:
        if status == "DOUBLE_PAIEMENT":
            status_clause = " AND r.double_paiement"
        else:
            status_clause = " AND r.statut=?"
            params.append(status)
    params.append(max(1, min(int(limit), 50000)))

    with service.db.connect() as con:
        return con.execute(f"""
            WITH pa AS (
                SELECT
                    CASE WHEN COALESCE(matricule_normalise,'') NOT IN ('','NU')
                         THEN 'M:' || matricule_normalise ELSE 'N:' || COALESCE(nom_normalise,'') END cle_match,
                    MIN(matricule_source) matricule_source,
                    MIN(matricule_normalise) matricule_normalise,
                    MIN(nom) nom, MIN(prenom) prenom, MIN(nom_normalise) nom_normalise,
                    MIN(section) section, MIN(categorie) categorie, MIN(grade) grade,
                    MIN(unite_affectation) unite_affectation, MIN(province) province,
                    COUNT(*) occurrences,
                    SUM(COALESCE(remuneration_base,0)) remuneration_base,
                    SUM(COALESCE(transport,0)) transport,
                    SUM(COALESCE(prime,0)) prime,
                    SUM(COALESCE(logement,0)) logement,
                    SUM(COALESCE(pension_rente,0)) pension_rente,
                    SUM(COALESCE(autres_remunerations,0)) autres_remunerations,
                    SUM(COALESCE(retenues,0)) retenues,
                    SUM(COALESCE(montant_net,0)) montant_net,
                    SUM(COALESCE(remuneration_brute_calculee,0)) remuneration_brute_calculee,
                    STRING_AGG(DISTINCT COALESCE(table_source,''), ' | ') table_source,
                    STRING_AGG(DISTINCT COALESCE(execution_id,''), ' | ') executions,
                    STRING_AGG(DISTINCT COALESCE(composantes_supplementaires_json,'{{}}'), ' | ') composantes_supplementaires
                FROM paie_standardisee
                WHERE institution_id=? AND regime=? AND trimestre=? AND annee=?
                  AND (COALESCE(matricule_normalise,'') NOT IN ('','NU') OR COALESCE(nom_normalise,'')<>'')
                GROUP BY 1
            ), pb AS (
                SELECT
                    CASE WHEN COALESCE(matricule_normalise,'') NOT IN ('','NU')
                         THEN 'M:' || matricule_normalise ELSE 'N:' || COALESCE(nom_normalise,'') END cle_match,
                    MIN(matricule_source) matricule_source,
                    MIN(matricule_normalise) matricule_normalise,
                    MIN(nom) nom, MIN(prenom) prenom, MIN(nom_normalise) nom_normalise,
                    MIN(section) section, MIN(categorie) categorie, MIN(grade) grade,
                    MIN(unite_affectation) unite_affectation, MIN(province) province,
                    COUNT(*) occurrences,
                    SUM(COALESCE(remuneration_base,0)) remuneration_base,
                    SUM(COALESCE(transport,0)) transport,
                    SUM(COALESCE(prime,0)) prime,
                    SUM(COALESCE(logement,0)) logement,
                    SUM(COALESCE(pension_rente,0)) pension_rente,
                    SUM(COALESCE(autres_remunerations,0)) autres_remunerations,
                    SUM(COALESCE(retenues,0)) retenues,
                    SUM(COALESCE(montant_net,0)) montant_net,
                    SUM(COALESCE(remuneration_brute_calculee,0)) remuneration_brute_calculee,
                    STRING_AGG(DISTINCT COALESCE(table_source,''), ' | ') table_source,
                    STRING_AGG(DISTINCT COALESCE(execution_id,''), ' | ') executions,
                    STRING_AGG(DISTINCT COALESCE(composantes_supplementaires_json,'{{}}'), ' | ') composantes_supplementaires
                FROM paie_standardisee
                WHERE institution_id=? AND regime=? AND trimestre=? AND annee=?
                  AND (COALESCE(matricule_normalise,'') NOT IN ('','NU') OR COALESCE(nom_normalise,'')<>'')
                GROUP BY 1
            )
            SELECT
                r.statut, r.cle_match, r.cle_type, r.diagnostic,
                pa.matricule_source, pa.matricule_normalise, pa.nom, pa.prenom, pa.nom_normalise,
                pa.section, pa.categorie, pa.grade, pa.unite_affectation, pa.province,
                COALESCE(pa.occurrences,0), pa.remuneration_base, pa.transport, pa.prime, pa.logement,
                pa.pension_rente, pa.autres_remunerations, pa.retenues, pa.montant_net,
                pa.remuneration_brute_calculee, pa.table_source, pa.executions, pa.composantes_supplementaires,
                pb.matricule_source, pb.matricule_normalise, pb.nom, pb.prenom, pb.nom_normalise,
                pb.section, pb.categorie, pb.grade, pb.unite_affectation, pb.province,
                COALESCE(pb.occurrences,0), pb.remuneration_base, pb.transport, pb.prime, pb.logement,
                pb.pension_rente, pb.autres_remunerations, pb.retenues, pb.montant_net,
                pb.remuneration_brute_calculee, pb.table_source, pb.executions, pb.composantes_supplementaires,
                r.ecart_remuneration, r.ecart_net, r.ecart_pourcentage, r.double_paiement
            FROM resultats_comparaison_regimes r
            LEFT JOIN pa ON pa.cle_match=r.cle_match
            LEFT JOIN pb ON pb.cle_match=r.cle_match
            WHERE r.comparaison_id=? {status_clause}
            ORDER BY CASE WHEN r.statut='COMMUN_IDENTIQUE' THEN 1 ELSE 0 END,
                     ABS(COALESCE(r.ecart_remuneration,0)) DESC, COALESCE(pa.nom,pb.nom)
            LIMIT ?
        """, params).fetchall()
