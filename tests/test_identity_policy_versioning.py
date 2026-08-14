from pathlib import Path

from controle_paie.database import Database
from controle_paie.identity_policy import (
    ABSENT, IDENTITE_INCOHERENTE, MATCH_AMBIGU_MATRICULE,
    MATCH_EXACT, MATCH_NOM_PROBABLE, decide_identity,
)
from controle_paie.raw_period_comparison_versioned import VersionedRawPeriodComparisonService


def test_identity_policy_is_strict_and_never_selects_ambiguous_candidate():
    assert decide_identity(usable_matricule=True, usable_name=True,
                           exact_candidates=1, matricule_candidates=1, name_candidates=1).status == MATCH_EXACT
    assert decide_identity(usable_matricule=True, usable_name=True,
                           exact_candidates=0, matricule_candidates=2, name_candidates=1).status == MATCH_AMBIGU_MATRICULE
    assert decide_identity(usable_matricule=True, usable_name=True,
                           exact_candidates=0, matricule_candidates=1, name_candidates=0).status == IDENTITE_INCOHERENTE
    assert decide_identity(usable_matricule=False, usable_name=True,
                           exact_candidates=0, matricule_candidates=0, name_candidates=1).status == MATCH_NOM_PROBABLE
    assert decide_identity(usable_matricule=False, usable_name=False,
                           exact_candidates=0, matricule_candidates=0, name_candidates=0).status == ABSENT


def _insert_payroll(con, line_id, exec_id, institution, regime, mat, name):
    con.execute("""INSERT INTO paie_standardisee
        (ligne_paie_id,execution_id,institution_id,regime,trimestre,annee,table_source,
         matricule_source,matricule_normalise,nom,prenom,nom_normalise,
         remuneration_brute_calculee,montant_net,ligne_source)
        VALUES (?,?,?,?, 'T1',2026,?,?,?,?,?,?,0,0,1)""",
        [line_id, exec_id, institution, regime, "TEST", mat, mat, name, "", name.upper().replace(" ", "")])


def test_raw_reanalysis_preserves_previous_analysis_and_creates_next_version(tmp_path: Path):
    db = Database(tmp_path / "versioning.duckdb")
    db.migrate()
    svc = VersionedRawPeriodComparisonService(db)
    with db.connect() as con:
        con.execute("CREATE TABLE raw_a(dummy INTEGER)")
        con.execute("CREATE TABLE raw_b(dummy INTEGER)")
        con.execute("""INSERT INTO journal_executions
            (execution_id,type_operation,table_destination,institution_id,regime,trimestre,annee,statut)
            VALUES ('EA','IMPORT_ACCESS','raw_a','IA','RA','T1',2026,'TERMINE'),
                   ('EB','IMPORT_ACCESS','raw_b','IB','RB','T1',2026,'TERMINE')""")
        _insert_payroll(con, 'A1', 'EA', 'IA', 'RA', '001', 'ALPHA')
        _insert_payroll(con, 'B1', 'EB', 'IB', 'RB', '001', 'ALPHA')

    first = svc.analyze('raw_a', 'raw_b', 'T1', 2026)
    second = svc.reanalyze(first['id'])

    assert second['id'] != first['id']
    assert svc.get_comparison(first['id'])['id'] == first['id']
    assert svc.get_comparison(second['id'])['id'] == second['id']

    with db.connect() as con:
        versions = con.execute("""SELECT analyse_id,analyse_parent_id,numero_version,action
            FROM versions_analyses WHERE type_analyse='COMPARAISON_RAW_PERIODE'
            ORDER BY numero_version""").fetchall()
    assert versions[0][0] == first['id']
    assert versions[0][2] == 1
    assert versions[1][0] == second['id']
    assert versions[1][1] == first['id']
    assert versions[1][2] == 2
    assert versions[1][3] == 'REANALYSE'
