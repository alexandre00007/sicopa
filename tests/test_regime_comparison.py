from controle_paie.database import Database
from controle_paie.regime_comparison_runtime import RegimeComparisonService


def _insert_payroll(con, line_id, execution_id, institution_id, regime, matricule, name,
                    gross, net, grade="G1", category="C1", assignment="U1", province="P1"):
    con.execute(
        """INSERT INTO paie_standardisee
           (ligne_paie_id,execution_id,institution_id,regime,trimestre,annee,table_source,
            matricule_source,matricule_normalise,nom,prenom,nom_normalise,grade,categorie,
            unite_affectation,province,remuneration_brute_calculee,montant_net,ligne_source)
           VALUES (?,?,?,?, 'T1',2026,'TEST',?,?,?,?,?,?,?,?,?,?,?,1)""",
        [line_id, execution_id, institution_id, regime, matricule, matricule,
         name, "", name.upper().replace(" ", ""), grade, category, assignment, province, gross, net],
    )


def test_regime_comparison_classifies_presence_financial_and_admin_differences(tmp_path):
    db = Database(tmp_path / "sicorpa.duckdb")
    db.migrate()
    institution = db.add_institution("TEST", "Institution Test")
    with db.connect() as con:
        _insert_payroll(con, "a1", "ea", institution, "REG_A", "001", "ALPHA", 100, 90)
        _insert_payroll(con, "b1", "eb", institution, "REG_B", "001", "ALPHA", 100, 90)
        _insert_payroll(con, "a2", "ea", institution, "REG_A", "002", "BETA", 200, 180)
        _insert_payroll(con, "b2", "eb", institution, "REG_B", "002", "BETA", 250, 220)
        _insert_payroll(con, "a3", "ea", institution, "REG_A", "003", "GAMMA", 300, 280, grade="G1")
        _insert_payroll(con, "b3", "eb", institution, "REG_B", "003", "GAMMA", 300, 280, grade="G2")
        _insert_payroll(con, "a4", "ea", institution, "REG_A", "004", "DELTA", 400, 370)
        _insert_payroll(con, "b5", "eb", institution, "REG_B", "005", "EPSILON", 500, 460)

    service = RegimeComparisonService(db)
    summary = service.run(institution, "REG_A", institution, "REG_B", "T1", 2026)

    assert summary["common"] == 3
    assert summary["only_a"] == 1
    assert summary["only_b"] == 1
    assert summary["financial"] == 1
    assert summary["administrative"] == 1

    statuses = [row[0] for row in service.list_results(summary["id"])]
    assert "COMMUN_IDENTIQUE" in statuses
    assert "ECART_FINANCIER" in statuses
    assert "ECART_ADMINISTRATIF" in statuses
    assert "UNIQUEMENT_REGIME_A" in statuses
    assert "UNIQUEMENT_REGIME_B" in statuses


def test_regime_comparison_detects_multiple_payment_and_identity_conflict(tmp_path):
    db = Database(tmp_path / "sicorpa.duckdb")
    db.migrate()
    institution = db.add_institution("TEST", "Institution Test")
    with db.connect() as con:
        _insert_payroll(con, "a1", "ea", institution, "REG_A", "010", "ALPHA", 100, 90)
        _insert_payroll(con, "a2", "ea", institution, "REG_A", "010", "ALPHA", 100, 90)
        _insert_payroll(con, "b1", "eb", institution, "REG_B", "010", "ALPHA", 100, 90)
        _insert_payroll(con, "a3", "ea", institution, "REG_A", "020", "BETA", 100, 90)
        _insert_payroll(con, "b2", "eb", institution, "REG_B", "020", "OMEGA", 100, 90)

    service = RegimeComparisonService(db)
    summary = service.run(institution, "REG_A", institution, "REG_B", "T1", 2026)
    statuses = [row[0] for row in service.list_results(summary["id"])]

    assert "PAIEMENT_MULTIPLE" in statuses
    assert "IDENTITE_INCOHERENTE" in statuses
    assert summary["common"] == 2
