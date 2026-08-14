from controle_paie.database import Database
from controle_paie.matching_deletion import MatchingDeletionService


def test_delete_matching_run_preserves_payroll_and_declaration(tmp_path):
    db = Database(tmp_path / "sicorpa.duckdb")
    db.migrate()
    institution_id = db.add_institution("TEST", "Institution test")

    with db.connect() as con:
        con.execute("""INSERT INTO paie_standardisee
            (ligne_paie_id,execution_id,institution_id,regime,trimestre,annee,matricule_source)
            VALUES ('p1','pay-1',?,'CNSS','T1',2026,'001')""", [institution_id])
        con.execute("""INSERT INTO declaratif_standardise
            (ligne_declaratif_id,execution_id,institution_id,regime,trimestre,annee,matricule_source)
            VALUES ('d1','decl-1',?,'CNSS','T1',2026,'001')""", [institution_id])
        con.execute("""INSERT INTO resultats_rapprochement
            (rapprochement_id,execution_id,institution_id,regime,trimestre,annee,
             ligne_paie_id,ligne_declaratif_id,statut_rapprochement,statut_validation,impact_confirme)
            VALUES ('r1','match-1',?,'CNSS','T1',2026,'p1','d1','CONFORME_MATRICULE','VALIDE',125)""", [institution_id])

    service = MatchingDeletionService(db)
    info = service.get_run("match-1")
    assert info["rows"] == 1
    assert info["validated"] == 1

    result = service.delete_run("match-1")
    assert result["deleted"] == 1

    with db.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM resultats_rapprochement").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM paie_standardisee").fetchone()[0] == 1
        assert con.execute("SELECT COUNT(*) FROM declaratif_standardise").fetchone()[0] == 1
