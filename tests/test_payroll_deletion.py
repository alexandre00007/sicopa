import pytest

from controle_paie.database import Database
from controle_paie.payroll_deletion import PayrollDeletionService


def _seed_scope(db: Database, *, execution_id="exec-paie", with_matching=False):
    institution_id = db.add_institution("TEST", "Institution test")
    with db.connect() as con:
        con.execute(
            """INSERT INTO paie_standardisee
               (ligne_paie_id,execution_id,institution_id,regime,trimestre,annee,table_source,matricule_source)
               VALUES ('paie-1',?,?,?,?,?,'Tab_TEST','001')""",
            [execution_id, institution_id, "CNSS", "T1", 2026],
        )
        con.execute(
            """INSERT INTO declaratif_standardise
               (ligne_declaratif_id,execution_id,institution_id,regime,trimestre,annee,matricule_source)
               VALUES ('decl-1','exec-decl',?,'CNSS','T1',2026,'001')""",
            [institution_id],
        )
        con.execute("CREATE TABLE raw_test (execution_id VARCHAR, valeur VARCHAR)")
        con.execute("INSERT INTO raw_test VALUES (?, 'ligne brute')", [execution_id])
        con.execute(
            """INSERT INTO journal_executions
               (execution_id,type_operation,fichier_source,table_source,table_destination,institution_id,
                regime,trimestre,annee,mode_chargement,lignes_lues,lignes_chargees,statut,date_fin)
               VALUES (?,'IMPORT_ACCESS','test.accdb','Tab_TEST','raw_test',?,'CNSS','T1',2026,
                       'append',1,1,'TERMINE',CURRENT_TIMESTAMP)""",
            [execution_id, institution_id],
        )
        if with_matching:
            con.execute(
                """INSERT INTO resultats_rapprochement
                   (rapprochement_id,execution_id,institution_id,regime,trimestre,annee,ligne_paie_id)
                   VALUES ('r-1','match-1',?,'CNSS','T1',2026,'paie-1')""",
                [institution_id],
            )
    return institution_id


def test_delete_payroll_scope_removes_payroll_and_raw_but_preserves_declaration(tmp_path):
    db = Database(tmp_path / "sicorpa.duckdb")
    db.migrate()
    institution_id = _seed_scope(db)
    service = PayrollDeletionService(db)

    result = service.delete_scope(institution_id, "CNSS", "T1", 2026)

    assert result["rows"] == 1
    with db.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM paie_standardisee").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM raw_test").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM declaratif_standardise").fetchone()[0] == 1
        status = con.execute(
            "SELECT statut FROM journal_executions WHERE execution_id='exec-paie'"
        ).fetchone()[0]
        assert status == "SUPPRIME"


def test_delete_payroll_scope_is_blocked_when_matching_uses_payroll(tmp_path):
    db = Database(tmp_path / "sicorpa.duckdb")
    db.migrate()
    institution_id = _seed_scope(db, with_matching=True)
    service = PayrollDeletionService(db)

    with pytest.raises(ValueError, match="Suppression bloquee"):
        service.delete_scope(institution_id, "CNSS", "T1", 2026)

    with db.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM paie_standardisee").fetchone()[0] == 1
        assert con.execute("SELECT COUNT(*) FROM raw_test").fetchone()[0] == 1
        assert con.execute("SELECT COUNT(*) FROM declaratif_standardise").fetchone()[0] == 1
