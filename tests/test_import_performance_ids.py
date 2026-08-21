import pandas as pd

from controle_paie.standardization import standardize_declaration, standardize_payroll


def test_payroll_fast_ids_are_unique_and_deterministic():
    raw = pd.DataFrame({
        "Matricule": ["001", "002", "003"],
        "Nom": ["A", "B", "C"],
    })
    metadata = {
        "execution_id": "exec-123",
        "institution_id": "inst",
        "regime": "R",
        "trimestre": "T1",
        "annee": 2026,
        "table_source": "raw_test",
    }
    standard = standardize_payroll(raw, metadata)
    assert list(standard["ligne_paie_id"]) == [
        "exec-123:P:1", "exec-123:P:2", "exec-123:P:3"
    ]
    assert standard["ligne_paie_id"].is_unique


def test_declaration_fast_ids_are_unique_and_deterministic():
    raw = pd.DataFrame({
        "Matricule": ["001", "002"],
        "Nom": ["A", "B"],
    })
    metadata = {
        "execution_id": "exec-456",
        "institution_id": "inst",
        "regime": "R",
        "trimestre": "T1",
        "annee": 2026,
        "fichier_source": "x.xlsx",
        "feuille_source": "Feuil1",
    }
    standard = standardize_declaration(raw, metadata)
    assert list(standard["ligne_declaratif_id"]) == [
        "exec-456:D:1", "exec-456:D:2"
    ]
    assert standard["ligne_declaratif_id"].is_unique
