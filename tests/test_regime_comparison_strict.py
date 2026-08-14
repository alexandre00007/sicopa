from controle_paie.database import Database
from controle_paie.regime_comparison_strict import StrictRegimeComparisonService


def _insert_payroll(con, line_id, execution_id, institution_id, regime, matricule, name,
                    gross=100, net=90, grade="G1", category="C1", assignment="U1", province="P1"):
    con.execute(
        """INSERT INTO paie_standardisee
           (ligne_paie_id,execution_id,institution_id,regime,trimestre,annee,table_source,
            matricule_source,matricule_normalise,nom,prenom,nom_normalise,grade,categorie,
            unite_affectation,province,remuneration_brute_calculee,montant_net,ligne_source)
           VALUES (?,?,?,?, 'T1',2026,'TEST',?,?,?,?,?,?,?,?,?,?,?,1)""",
        [line_id, execution_id, institution_id, regime, matricule, matricule,
         name, "", name.upper().replace(" ", ""), grade, category, assignment, province, gross, net],
    )


def test_exact_identity_is_only_certain_common_and_potential_double_payment(tmp_path):
    db = Database(tmp_path / "strict_regime.duckdb")
    db.migrate()
    institution = db.add_institution("TEST", "Institution Test")
    with db.connect() as con:
        _insert_payroll(con, "a1", "ea", institution, "REG_A", "001", "ALPHA", 100, 90)
        _insert_payroll(con, "b1", "eb", institution, "REG_B", "001", "ALPHA", 110, 95)

    service = StrictRegimeComparisonService(db)
    summary = service.run(institution, "REG_A", institution, "REG_B", "T1", 2026)
    rows = service.list_results(summary["id"])

    assert summary["common"] == 1
    assert summary["double"] == 1
    assert rows[0][0] in {"ECART_FINANCIER", "ECART_FINANCIER_ET_ADMIN", "DOUBLE_PAIEMENT_POTENTIEL"}
    with db.connect() as con:
        row = con.execute("SELECT cle_type,double_paiement FROM resultats_comparaison_regimes WHERE comparaison_id=?", [summary["id"]]).fetchone()
    assert row == ("MATRICULE+NOM", True)


def test_same_matricule_different_name_is_not_common_and_not_double_payment(tmp_path):
    db = Database(tmp_path / "mat_conflict.duckdb")
    db.migrate()
    institution = db.add_institution("TEST", "Institution Test")
    with db.connect() as con:
        _insert_payroll(con, "a1", "ea", institution, "REG_A", "010", "ALPHA")
        _insert_payroll(con, "b1", "eb", institution, "REG_B", "010", "OMEGA")

    service = StrictRegimeComparisonService(db)
    summary = service.run(institution, "REG_A", institution, "REG_B", "T1", 2026)
    rows = service.list_results(summary["id"])

    assert summary["common"] == 0
    assert summary["double"] == 0
    assert any(row[0] == "IDENTITE_INCOHERENTE" for row in rows)


def test_same_name_different_matricule_is_explicit_identity_anomaly(tmp_path):
    db = Database(tmp_path / "name_conflict.duckdb")
    db.migrate()
    institution = db.add_institution("TEST", "Institution Test")
    with db.connect() as con:
        _insert_payroll(con, "a1", "ea", institution, "REG_A", "020", "KABILA JEAN")
        _insert_payroll(con, "b1", "eb", institution, "REG_B", "999", "KABILA JEAN")

    service = StrictRegimeComparisonService(db)
    summary = service.run(institution, "REG_A", institution, "REG_B", "T1", 2026)
    rows = service.list_results(summary["id"])

    assert summary["common"] == 0
    assert summary["double"] == 0
    assert any(row[0] == "NOM_MATRICULE_DIFFERENT" for row in rows)


def test_multiple_names_for_same_b_matricule_is_ambiguous_without_arbitrary_choice(tmp_path):
    db = Database(tmp_path / "ambiguous_mat.duckdb")
    db.migrate()
    institution = db.add_institution("TEST", "Institution Test")
    with db.connect() as con:
        _insert_payroll(con, "a1", "ea", institution, "REG_A", "100", "ALPHA")
        _insert_payroll(con, "b1", "eb", institution, "REG_B", "100", "BETA")
        _insert_payroll(con, "b2", "eb", institution, "REG_B", "100", "GAMMA")

    service = StrictRegimeComparisonService(db)
    summary = service.run(institution, "REG_A", institution, "REG_B", "T1", 2026)
    rows = service.list_results(summary["id"])

    ambiguous = next(row for row in rows if row[0] == "MATCH_AMBIGU_MATRICULE")
    assert summary["common"] == 0
    assert summary["double"] == 0
    assert summary["only_a"] == 0
    assert summary["only_b"] == 0
    assert ambiguous[7] == 0  # Brut B neutralisé : aucun candidat choisi arbitrairement.
