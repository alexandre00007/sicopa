import pytest

from controle_paie.database import Database
from controle_paie.sql_console import SqlConsoleService


def test_read_only_validator_accepts_select_and_with():
    assert SqlConsoleService.validate_read_only_query("SELECT 1") == "SELECT 1"
    query = "WITH x AS (SELECT 1 AS a) SELECT * FROM x"
    assert SqlConsoleService.validate_read_only_query(query) == query


@pytest.mark.parametrize("query", [
    "DELETE FROM raw_test",
    "UPDATE raw_test SET x=1",
    "DROP TABLE raw_test",
    "CREATE TABLE x AS SELECT 1",
    "ATTACH 'other.duckdb' AS other",
    "WITH x AS (SELECT 1) DELETE FROM raw_test",
    "SELECT 1; DELETE FROM raw_test",
])
def test_read_only_validator_blocks_writes(query):
    with pytest.raises(ValueError):
        SqlConsoleService.validate_read_only_query(query)


def test_console_lists_raw_tables_and_executes_select(tmp_path):
    db = Database(tmp_path / "sicorpa.duckdb")
    db.migrate()
    with db.connect() as con:
        con.execute("CREATE TABLE raw_demo (id INTEGER, libelle VARCHAR)")
        con.execute("INSERT INTO raw_demo VALUES (1,'A'),(2,'B')")
        con.execute("CREATE TABLE autre_table (id INTEGER)")

    service = SqlConsoleService(db)
    tables = service.list_raw_tables()
    assert ("raw_demo", 2) in tables
    assert all(name.startswith("raw_") for name, _ in tables)

    result = service.execute("SELECT id, libelle FROM raw_demo ORDER BY id", display_limit=10)
    assert result["columns"] == ["id", "libelle"]
    assert result["rows"] == [(1, "A"), (2, "B")]
    assert result["truncated"] is False


def test_console_applies_display_limit(tmp_path):
    db = Database(tmp_path / "sicorpa.duckdb")
    db.migrate()
    with db.connect() as con:
        con.execute("CREATE TABLE raw_demo (id INTEGER)")
        con.execute("INSERT INTO raw_demo SELECT * FROM range(5)")

    service = SqlConsoleService(db)
    result = service.execute("SELECT * FROM raw_demo ORDER BY id", display_limit=2)
    assert len(result["rows"]) == 2
    assert result["truncated"] is True
