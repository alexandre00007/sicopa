from pathlib import Path

from controle_paie.data_architecture import (
    DataQualityService,
    RawCatalogService,
    TreatmentJournalService,
    migrate_governance,
)
from controle_paie.database import Database


def make_db(tmp_path: Path):
    db = Database(tmp_path / "test.duckdb")
    db.migrate()
    migrate_governance(db)
    return db


def test_governance_migration_is_idempotent(tmp_path):
    db = make_db(tmp_path)
    migrate_governance(db)
    with db.connect() as con:
        versions = con.execute("SELECT version FROM migrations_sicorpa ORDER BY version").fetchall()
        tables = {r[0] for r in con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='main'").fetchall()}
    assert versions == [(1,), (2,)]
    assert {
        "catalogue_raw", "qualite_imports", "journal_traitements",
        "comparaisons_regimes", "resultats_comparaison_regimes",
        "comparaisons_raw_periode", "sources_comparaison_raw_periode",
        "resultats_comparaison_raw_periode", "fusions_raw",
        "sources_fusion_raw", "resultats_fusion_multi", "versions_analyses",
    }.issubset(tables)


def test_migration_v2_preserves_existing_legacy_tables_and_rows(tmp_path):
    db = Database(tmp_path / "legacy.duckdb")
    db.migrate()
    with db.connect() as con:
        con.execute("""CREATE TABLE comparaisons_raw_periode (
            comparaison_id VARCHAR PRIMARY KEY, table_a VARCHAR NOT NULL, table_b VARCHAR NOT NULL,
            trimestre VARCHAR NOT NULL, annee INTEGER NOT NULL, statut VARCHAR NOT NULL,
            cree_le TIMESTAMP DEFAULT CURRENT_TIMESTAMP, termine_le TIMESTAMP, dossier_export VARCHAR)""")
        con.execute("""INSERT INTO comparaisons_raw_periode
            (comparaison_id,table_a,table_b,trimestre,annee,statut)
            VALUES ('legacy-cmp','raw_a','raw_b','T1',2026,'TERMINE')""")
        con.execute("""CREATE TABLE fusions_raw (
            fusion_id VARCHAR PRIMARY KEY, table_fusion VARCHAR NOT NULL, trimestre VARCHAR NOT NULL,
            annee INTEGER NOT NULL, statut VARCHAR NOT NULL, lignes_fusion BIGINT DEFAULT 0,
            nombre_sources BIGINT DEFAULT 0, nombre_regimes BIGINT DEFAULT 0,
            cree_le TIMESTAMP DEFAULT CURRENT_TIMESTAMP, termine_le TIMESTAMP, dossier_export VARCHAR)""")
        con.execute("""INSERT INTO fusions_raw
            (fusion_id,table_fusion,trimestre,annee,statut,lignes_fusion)
            VALUES ('legacy-fusion','raw_multi_regimes_T1_2026','T1',2026,'TERMINE',42)""")
    migrate_governance(db)
    migrate_governance(db)
    with db.connect() as con:
        cmp_row = con.execute("SELECT table_a,table_b,statut FROM comparaisons_raw_periode WHERE comparaison_id='legacy-cmp'").fetchone()
        fusion_row = con.execute("SELECT table_fusion,lignes_fusion FROM fusions_raw WHERE fusion_id='legacy-fusion'").fetchone()
        versions = con.execute("SELECT version FROM migrations_sicorpa ORDER BY version").fetchall()
    assert cmp_row == ("raw_a", "raw_b", "TERMINE")
    assert fusion_row == ("raw_multi_regimes_T1_2026", 42)
    assert versions == [(1,), (2,)]


def test_quality_counts_only_repeated_usable_keys(tmp_path):
    db = make_db(tmp_path)
    execution_id = "exec-quality"
    with db.connect() as con:
        con.execute("""INSERT INTO journal_executions
            (execution_id,type_operation,table_destination,statut,date_fin)
            VALUES (?, 'IMPORT_ACCESS', 'raw_demo', 'TERMINE', CURRENT_TIMESTAMP)""", [execution_id])
        con.execute("""INSERT INTO paie_standardisee
            (ligne_paie_id,execution_id,matricule_normalise,nom_normalise)
            VALUES
            ('1',?,'M1','ALPHA'),
            ('2',?,'M1','ALPHA'),
            ('3',?,'','BETA'),
            ('4',?,'NU','')""", [execution_id] * 4)
    result = DataQualityService(db).calculate(execution_id)
    with db.connect() as con:
        row = con.execute("""SELECT lignes,matricules_exploitables,noms_exploitables,
            matricules_dupliques,noms_dupliques,niveau FROM qualite_imports WHERE execution_id=?""",
            [execution_id]).fetchone()
    assert row[:5] == (4, 2, 3, 1, 1)
    assert result["score"] > 0
    assert row[5] in {"EXCELLENTE", "ACCEPTABLE", "LIMITEE", "FAIBLE"}


def test_catalog_caches_raw_count_and_metadata(tmp_path):
    db = make_db(tmp_path)
    with db.connect() as con:
        con.execute("CREATE TABLE raw_demo(id INTEGER, execution_id VARCHAR, trimestre VARCHAR, annee INTEGER)")
        con.execute("INSERT INTO raw_demo VALUES (1,'e1','T1',2026),(2,'e1','T1',2026),(3,'e1','T1',2026)")
        con.execute("""INSERT INTO journal_executions
            (execution_id,type_operation,table_destination,regime,trimestre,annee,statut,date_fin)
            VALUES ('e1','IMPORT_ACCESS','raw_demo','REGIME_X','T1',2026,'TERMINE',CURRENT_TIMESTAMP)""")
    catalog = RawCatalogService(db)
    catalog.refresh()
    assert catalog.list() == [("raw_demo", 3)]
    with db.connect() as con:
        con.execute("INSERT INTO raw_demo VALUES (4,'e1','T1',2026)")
    assert catalog.list() == [("raw_demo", 3)]
    catalog.refresh()
    assert catalog.list() == [("raw_demo", 4)]


def test_treatment_journal_success_and_failure(tmp_path):
    db = make_db(tmp_path)
    journal = TreatmentJournalService(db)
    ok = journal.start("Analyse test")
    journal.finish(ok, {"comparison_id": "cmp-1", "rows": 12})
    ko = journal.start("Analyse erreur")
    journal.fail(ko, ValueError("boom"))
    with db.connect() as con:
        rows = con.execute("SELECT operation,statut,lignes,objet_id,message FROM journal_traitements ORDER BY date_debut").fetchall()
    assert rows[0][0:4] == ("Analyse test", "TERMINE", 12, "cmp-1")
    assert rows[1][0:2] == ("Analyse erreur", "ERREUR")
    assert "boom" in rows[1][4]
