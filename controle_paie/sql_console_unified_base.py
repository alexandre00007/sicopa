from __future__ import annotations

from .flexible_access_app import PayrollAppWithFlexibleAccess
from .sql_console import SqlConsoleService
from .sql_console_app import PayrollAppWithSqlConsole as LegacySqlConsole


class PayrollAppWithUnifiedSqlConsole(PayrollAppWithFlexibleAccess):
    """Raccorde la console SQL historique au-dessus de la chaîne fonctionnelle consolidée."""

    def __init__(self, *args, **kwargs):
        self.sql_console_service = None
        self.sql_last_query = ""
        self.sql_history = []
        super().__init__(*args, **kwargs)
        self.sql_console_service = SqlConsoleService(self.db)

    def _build_ui(self):
        super()._build_ui()
        self.sql_console_service = SqlConsoleService(self.db)
        self._add_sql_console_tab()

    _add_sql_console_tab = LegacySqlConsole._add_sql_console_tab
    _build_sql_console = LegacySqlConsole._build_sql_console
    _refresh_sql_tables = LegacySqlConsole._refresh_sql_tables
    _sql_table_selected = LegacySqlConsole._sql_table_selected
    _insert_selected_sql_table = LegacySqlConsole._insert_selected_sql_table
    _sql_insert_select_template = LegacySqlConsole._sql_insert_select_template
    _run_sql_query = LegacySqlConsole._run_sql_query
    _append_sql_history = LegacySqlConsole._append_sql_history
    _reload_sql_history = LegacySqlConsole._reload_sql_history
    _export_sql_excel = LegacySqlConsole._export_sql_excel
    _export_sql_csv = LegacySqlConsole._export_sql_csv
