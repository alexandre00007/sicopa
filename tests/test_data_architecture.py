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
    assert versions == [(1,)]
    assert {"catalogue_raw", "qualite_imports", "journal_traitements"}.issubset(tables)


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
    # La lecture ordinaire utilise bien le cache; un refresh explicite le remet a jour.
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
