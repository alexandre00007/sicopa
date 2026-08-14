from pathlib import Path

from controle_paie.database import Database
from controle_paie.raw_period_comparison_strict_ambiguity import AmbiguityAwareRawPeriodComparisonService


def _insert_payroll(con, line_id, execution_id, institution, regime, matricule, nom, prenom, nom_norm):
    con.execute("""INSERT INTO paie_standardisee
        (ligne_paie_id,execution_id,institution_id,regime,trimestre,annee,table_source,
         matricule_source,matricule_normalise,nom,prenom,nom_normalise,
         section,categorie,grade,unite_affectation,province,
         remuneration_base,transport,prime,logement,pension_rente,autres_remunerations,retenues,
         montant_net,remuneration_brute_calculee)
        VALUES (?,?,?,?,? ,2026,?,?,?,?,?,?, '', '', '', '', '', 0,0,0,0,0,0,0,0,0)""",
        [line_id, execution_id, institution, regime, "T1", execution_id, matricule, matricule, nom, prenom, nom_norm],
    )


def _setup(tmp_path: Path):
    db = Database(str(tmp_path / "strict_consistency.duckdb"))
    db.migrate()
    svc = AmbiguityAwareRawPeriodComparisonService(db)
    with db.connect() as con:
        con.execute("""INSERT INTO journal_executions
            (execution_id,type_operation,table_destination,institution_id,regime,trimestre,annee,statut)
            VALUES
            ('EA','IMPORT_ACCESS','raw_a','A','R1','T1',2026,'TERMINE'),
            ('EB','IMPORT_ACCESS','raw_b','B','R2','T1',2026,'TERMINE')""")
        con.execute("CREATE TABLE raw_a(dummy INTEGER)")
        con.execute("CREATE TABLE raw_b(dummy INTEGER)")
    return db, svc


def test_crossed_matches_do_not_inflate_exact_kpi(tmp_path: Path):
    db, svc = _setup(tmp_path)
    with db.connect() as con:
        _insert_payroll(con, "A1", "EA", "A", "R1", "M001", "JEAN", "KABILA", "JEANKABILA")
        _insert_payroll(con, "B1", "EB", "B", "R2", "M001", "PIERRE", "MBUYI", "PIERREMBUYI")
        _insert_payroll(con, "B2", "EB", "B", "R2", "M999", "JEAN", "KABILA", "JEANKABILA")

    info = svc.analyze("raw_a", "raw_b", "T1", 2026)
    _, metrics = svc.summary(info["id"])
    assert metrics[0] == 1
    assert metrics[1] == 1
    assert metrics[2] == 0


def test_multiple_names_for_same_b_matricule_are_ambiguous(tmp_path: Path):
    db, svc = _setup(tmp_path)
    with db.connect() as con:
        _insert_payroll(con, "A1", "EA", "A", "R1", "M001", "ALAIN", "KABILA", "ALAINKABILA")
        _insert_payroll(con, "B1", "EB", "B", "R2", "M001", "PIERRE", "MBUYI", "PIERREMBUYI")
        _insert_payroll(con, "B2", "EB", "B", "R2", "M001", "JEAN", "MUTOMBO", "JEANMUTOMBO")

    info = svc.analyze("raw_a", "raw_b", "T1", 2026)
    row = next(r for r in svc.list_results(info["id"]) if r[1] == "M001")
    assert row[0] == "MATCH_AMBIGU_MATRICULE"
    assert row[2] is None
    assert row[16] == 0
    assert "plusieurs identites B" in row[-1]
