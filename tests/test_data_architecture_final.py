from pathlib import Path

from controle_paie.data_architecture import migrate_governance
from controle_paie.data_architecture_finalize import (
    FINAL_DATA_SCHEMA_VERSION,
    assert_schema_health,
    finalize_data_architecture,
    schema_health,
)
from controle_paie.database import Database


def make_db(tmp_path: Path):
    db = Database(tmp_path / "test-final.duckdb")
    db.migrate()
    migrate_governance(db)
    return db


def test_final_migration_adds_occurrence_schema_and_is_idempotent(tmp_path):
    db = make_db(tmp_path)
    finalize_data_architecture(db)
    finalize_data_architecture(db)
    with db.connect() as con:
        versions = con.execute("SELECT version FROM migrations_sicorpa ORDER BY version").fetchall()
        columns = {row[0] for row in con.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name='resultats_comparaison_raw_periode'"
        ).fetchall()}
        occurrence_table = con.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name='occurrences_comparaison_raw'"
        ).fetchone()[0]
    assert (FINAL_DATA_SCHEMA_VERSION,) in versions
    assert occurrence_table == 1
    assert {"lignes_source_a", "lignes_source_b", "situation_occurrences", "ecart_lignes"}.issubset(columns)


def test_final_migration_preserves_existing_raw_comparison_data(tmp_path):
    db = make_db(tmp_path)
    with db.connect() as con:
        con.execute("""INSERT INTO comparaisons_raw_periode
            (comparaison_id,table_a,table_b,trimestre,annee,statut)
            VALUES ('cmp-old','raw_a','raw_b','T1',2026,'TERMINE')""")
        con.execute("""INSERT INTO resultats_comparaison_raw_periode
            (comparaison_id,cle_resultat,statut,matricule_a,nom_norm_a)
            VALUES ('cmp-old','k1','COMMUN_PAR_MATRICULE_ET_NOM','M1','ALPHA')""")
    finalize_data_architecture(db)
    with db.connect() as con:
        comparison = con.execute("SELECT table_a,table_b FROM comparaisons_raw_periode WHERE comparaison_id='cmp-old'").fetchone()
        result = con.execute("SELECT matricule_a,nom_norm_a FROM resultats_comparaison_raw_periode WHERE comparaison_id='cmp-old'").fetchone()
    assert comparison == ("raw_a", "raw_b")
    assert result == ("M1", "ALPHA")


def test_schema_health_is_green_after_finalization(tmp_path):
    db = make_db(tmp_path)
    finalize_data_architecture(db)
    health = assert_schema_health(db)
    assert health["ok"] is True
    assert health["version"] >= FINAL_DATA_SCHEMA_VERSION
    assert health["missing_tables"] == []
    assert health["missing_columns"] == []


def test_schema_health_detects_missing_final_schema(tmp_path):
    db = make_db(tmp_path)
    health = schema_health(db)
    assert health["ok"] is False
    assert "occurrences_comparaison_raw" in health["missing_tables"] or health["missing_columns"]
