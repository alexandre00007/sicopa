from pathlib import Path

from controle_paie.database import Database
from controle_paie.raw_period_comparison_strict import StrictRawPeriodComparisonService


def test_crossed_matricule_and_name_is_not_exact(tmp_path: Path):
    db = Database(str(tmp_path / "strict.duckdb"))
    db.migrate()
    svc = StrictRawPeriodComparisonService(db)

    with db.connect() as con:
        con.execute("""INSERT INTO journal_executions
            (execution_id,type_operation,table_destination,institution_id,regime,trimestre,annee,statut)
            VALUES
            ('EA','IMPORT_ACCESS','raw_a','A','R1','T1',2026,'TERMINE'),
            ('EB','IMPORT_ACCESS','raw_b','B','R2','T1',2026,'TERMINE')""")
        con.execute("CREATE TABLE raw_a(dummy INTEGER)")
        con.execute("CREATE TABLE raw_b(dummy INTEGER)")

        # A: M001 / JEAN KABILA
        con.execute("""INSERT INTO paie_standardisee
            (ligne_paie_id,execution_id,institution_id,regime,trimestre,annee,table_source,
             matricule_source,matricule_normalise,nom,prenom,nom_normalise,
             section,categorie,grade,unite_affectation,province,
             remuneration_base,transport,prime,logement,pension_rente,autres_remunerations,retenues,montant_net,remuneration_brute_calculee)
            VALUES ('A1','EA','A','R1','T1',2026,'raw_a','M001','M001','JEAN','KABILA','JEANKABILA',
                    '','','','','',0,0,0,0,0,0,0,0,0)""")

        # B1 partage le matricule mais pas le nom.
        con.execute("""INSERT INTO paie_standardisee
            (ligne_paie_id,execution_id,institution_id,regime,trimestre,annee,table_source,
             matricule_source,matricule_normalise,nom,prenom,nom_normalise,
             section,categorie,grade,unite_affectation,province,
             remuneration_base,transport,prime,logement,pension_rente,autres_remunerations,retenues,montant_net,remuneration_brute_calculee)
            VALUES ('B1','EB','B','R2','T1',2026,'raw_b','M001','M001','PIERRE','MBUYI','PIERREMBUYI',
                    '','','','','',0,0,0,0,0,0,0,0,0)""")

        # B2 partage le nom mais pas le matricule.
        con.execute("""INSERT INTO paie_standardisee
            (ligne_paie_id,execution_id,institution_id,regime,trimestre,annee,table_source,
             matricule_source,matricule_normalise,nom,prenom,nom_normalise,
             section,categorie,grade,unite_affectation,province,
             remuneration_base,transport,prime,logement,pension_rente,autres_remunerations,retenues,montant_net,remuneration_brute_calculee)
            VALUES ('B2','EB','B','R2','T1',2026,'raw_b','M999','M999','JEAN','KABILA','JEANKABILA',
                    '','','','','',0,0,0,0,0,0,0,0,0)""")

    info = svc.analyze('raw_a', 'raw_b', 'T1', 2026)
    rows = svc.list_results(info['id'])
    a_row = next(row for row in rows if row[1] == 'M001')

    assert a_row[0] != 'COMMUN_PAR_MATRICULE_ET_NOM'
    assert a_row[0] == 'COMMUN_PAR_MATRICULE'
    assert a_row[7] is True
    assert a_row[8] is True
