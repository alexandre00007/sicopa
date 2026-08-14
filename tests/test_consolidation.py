import duckdb
from openpyxl import load_workbook

from controle_paie.agent_identity import normalize_matricule, normalize_name, person_key
from controle_paie.export_streaming import write_query_xlsx


def test_agent_identity_is_canonical_and_stable():
    assert normalize_matricule(" 00-123 /A ") == "00123A"
    assert normalize_name("Kábila ", " Jean-Pierre") == "KABIL AJEANPIERRE".replace(" ", "")
    assert person_key("00-123", "KABILAJEAN") == "M:00123"
    assert person_key("NU", "KABILA JEAN") == "N:KABIL AJEAN".replace(" ", "")


def test_streaming_excel_exports_all_rows(tmp_path):
    con = duckdb.connect()
    con.execute("CREATE TABLE t AS SELECT i AS id, 'Agent ' || i::VARCHAR AS nom FROM range(0, 12050) x(i)")
    path = tmp_path / "export.xlsx"
    count = write_query_xlsx(con, path, "SELECT * FROM t ORDER BY id")
    assert count == 12050
    wb = load_workbook(path, read_only=True)
    ws = wb[wb.sheetnames[0]]
    assert ws.max_row == 12051
    assert ws.cell(2, 1).value == 0
    assert ws.cell(12051, 1).value == 12049
