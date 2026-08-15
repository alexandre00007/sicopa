from pathlib import Path

from controle_paie.database import Database
from controle_paie.raw_period_comparison_versioned import VersionedRawPeriodComparisonService


def _insert(con, line_id, exec_id, institution, regime, mat, name, gross, source_line):
    con.execute("""INSERT INTO paie_standardisee
        (ligne_paie_id,execution_id,institution_id,regime,trimestre,annee,table_source,
         matricule_source,matricule_normalise,nom,prenom,nom_normalise,
         remuneration_brute_calculee,montant_net,ligne_source)
        VALUES (?,?,?,?, 'T1',2026,?,?,?,?,?,?,?, ?, ?)""",
        [line_id,exec_id,institution,regime,'TEST',mat,mat,name,'',name.upper().replace(' ',''),gross,gross,source_line])


def test_occurrence_means_repeated_lines_after_first_source_line(tmp_path: Path):
    db = Database(tmp_path / 'occurrences.duckdb')
    db.migrate()
    service = VersionedRawPeriodComparisonService(db)

    with db.connect() as con:
        # Le schema enrichi contient les 42 colonnes historiques + 10 colonnes
        # d'occurrences. L'analyse doit rester compatible grâce à un INSERT
        # avec liste explicite de colonnes.
        schema = con.execute("PRAGMA table_info('resultats_comparaison_raw_periode')").fetchall()
        assert len(schema) == 52

        con.execute('CREATE TABLE raw_a(dummy INTEGER)')
        con.execute('CREATE TABLE raw_b(dummy INTEGER)')
        con.execute("""INSERT INTO journal_executions
            (execution_id,type_operation,table_destination,institution_id,regime,trimestre,annee,statut)
            VALUES ('EA','IMPORT_ACCESS','raw_a','IA','RA','T1',2026,'TERMINE'),
                   ('EB','IMPORT_ACCESS','raw_b','IB','RB','T1',2026,'TERMINE')""")
        _insert(con,'A1','EA','IA','RA','001','ALPHA',100,10)
        _insert(con,'A2','EA','IA','RA','001','ALPHA',100,20)
        _insert(con,'A3','EA','IA','RA','001','ALPHA',120,30)
        _insert(con,'B1','EB','IB','RB','001','ALPHA',100,5)

    info = service.analyze('raw_a','raw_b','T1',2026)
    rows = service.list_results_enriched(info['id'])
    row = next(r for r in rows if r[1] == '001')

    assert row[0] == 'COMMUN_PAR_MATRICULE_ET_NOM'
    assert row[13] == 2  # repetitions A = 3 lignes - premiere occurrence
    assert row[14] == 0  # repetitions B = 1 ligne - premiere occurrence
    assert row[15] == 3  # lignes physiques A
    assert row[16] == 1  # lignes physiques B
    assert row[17] == 2  # ecart lignes A-B
    assert row[18] == 'COMMUN_EXACT_REPETE_A'
    assert row[39] == 2  # deux montants bruts distincts cote A

    details_a = service.list_occurrence_details(info['id'],'A','001','ALPHA')
    assert [d[2] for d in details_a] == [10,20,30]


def test_common_exact_one_vs_one_stays_exact_without_repetition(tmp_path: Path):
    db = Database(tmp_path / 'one_vs_one.duckdb')
    db.migrate()
    service = VersionedRawPeriodComparisonService(db)
    with db.connect() as con:
        con.execute('CREATE TABLE raw_a(dummy INTEGER)')
        con.execute('CREATE TABLE raw_b(dummy INTEGER)')
        con.execute("""INSERT INTO journal_executions
            (execution_id,type_operation,table_destination,institution_id,regime,trimestre,annee,statut)
            VALUES ('EA','IMPORT_ACCESS','raw_a','IA','RA','T1',2026,'TERMINE'),
                   ('EB','IMPORT_ACCESS','raw_b','IB','RB','T1',2026,'TERMINE')""")
        _insert(con,'A1','EA','IA','RA','777','OMEGA',500,7)
        _insert(con,'B1','EB','IB','RB','777','OMEGA',500,9)

    info = service.analyze('raw_a','raw_b','T1',2026)
    row = next(r for r in service.list_results_enriched(info['id']) if r[1] == '777')
    assert row[0] == 'COMMUN_PAR_MATRICULE_ET_NOM'
    assert row[13] == 0 and row[14] == 0
    assert row[15] == 1 and row[16] == 1
    assert row[18] == 'COMMUN_EXACT_1_VS_1'
