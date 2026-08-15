from __future__ import annotations

from .raw_fusion_scalable_app import PayrollAppWithScalableRawFusion
from .sql_console import SqlConsoleService
from .sql_console_app import PayrollAppWithSqlConsole as LegacySqlConsole


class PayrollAppWithUnifiedSqlConsole(PayrollAppWithScalableRawFusion):
    """Raccorde une seule console SQL canonique au-dessus de la chaîne consolidée."""

    SQL_TAB_LABEL = "Console SQL"

    def __init__(self, *args, **kwargs):
        self.sql_console_service = None
        self.sql_last_query = ""
        self.sql_history = []
        super().__init__(*args, **kwargs)
        self.sql_console_service = SqlConsoleService(self.db)

    def _build_ui(self):
        super()._build_ui()
        self.sql_console_service = SqlConsoleService(self.db)
        self._remove_duplicate_sql_tabs()
        self._add_sql_console_tab()
        self._normalize_sql_tab_label()

    def _remove_duplicate_sql_tabs(self):
        """Retire les anciennes variantes SQL avant de créer la console canonique."""
        notebook = getattr(self, "notebook", None)
        if notebook is None:
            return
        for tab_id in list(notebook.tabs()):
            try:
                label = str(notebook.tab(tab_id, "text") or "").strip().lower()
            except Exception:
                continue
            is_sql = (
                "sql" in label
                and any(token in label for token in ("requ", "console", "éditeur", "editeur"))
            )
            if is_sql:
                try:
                    notebook.forget(tab_id)
                except Exception:
                    pass

    def _normalize_sql_tab_label(self):
        notebook = getattr(self, "notebook", None)
        page = getattr(self, "sql_console_page", None)
        if notebook is None or page is None:
            return
        shell = getattr(self, "_tab_shells", {}).get("sql_console_page")
        if shell is None:
            return
        try:
            notebook.tab(shell, text=self.SQL_TAB_LABEL)
        except Exception:
            pass

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
