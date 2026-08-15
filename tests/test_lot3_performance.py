from pathlib import Path

from controle_paie.database import Database
from controle_paie.explorer import DataExplorerService
from controle_paie.performance_health import PerformanceHealthService
from controle_paie.task_manager import TaskManager


class DummyControl:
    def __init__(self, state):
        self._state = state

    def cget(self, key):
        assert key == "state"
        return self._state

    def configure(self, **kwargs):
        if "state" in kwargs:
            self._state = kwargs["state"]


class DummyApp:
    def _background(self, task, success, refresh_data=False, operation=""):
        success(task())
        return True

    def _open_generation_dialog(self, *args, **kwargs):
        return None


def test_task_manager_restores_original_control_states():
    a = DummyControl("normal")
    b = DummyControl("disabled")
    c = DummyControl("readonly")
    manager = TaskManager(DummyApp())
    started = manager.run(lambda: 1, lambda result: None, operation="test", controls=[a, b, c])
    assert started is True
    assert a._state == "normal"
    assert b._state == "disabled"
    assert c._state == "readonly"


def test_explorer_server_side_pagination(tmp_path: Path):
    db = Database(tmp_path / "test.duckdb")
    db.migrate()
    with db.connect() as con:
        con.execute("CREATE TABLE demo AS SELECT i AS id, CASE WHEN i%2=0 THEN 'A' ELSE 'B' END AS grp FROM range(0,1050) t(i)")
    service = DataExplorerService(db)
    page = service.page("demo", "grp", "égal à", "A", page=2, page_size=100)
    assert page["total"] == 525
    assert page["total_pages"] == 6
    assert page["page"] == 2
    assert page["offset"] == 100
    assert len(page["rows"]) == 100


def test_performance_health_snapshot_and_checkpoint(tmp_path: Path):
    db = Database(tmp_path / "test.duckdb")
    db.migrate()
    with db.connect() as con:
        con.execute("CREATE TABLE raw_demo(id INTEGER)")
        con.execute("INSERT INTO raw_demo VALUES (1),(2)")
    service = PerformanceHealthService(db)
    snapshot = service.snapshot()
    assert snapshot["raw_tables"] >= 1
    assert snapshot["tables"] >= 1
    assert snapshot["memory_limit_mb"] >= 512
    result = service.checkpoint()
    assert result["operation"] == "CHECKPOINT"
