from __future__ import annotations

from tkinter import filedialog, messagebox, ttk

from .regime_comparison_folder_export import RegimeComparisonFolderExporter
from .sql_console_app import PayrollAppWithSqlConsole


class PayrollAppWithRegimeComparisonFolderExport(PayrollAppWithSqlConsole):
    """Application finale avec export complet des analyses de comparaison dans un dossier."""

    def _build_regime_comparison(self, parent):
        super()._build_regime_comparison(parent)
        self.regime_comparison_folder_exporter = RegimeComparisonFolderExporter(self.regime_comparison)

        actions = self.compare_export_button.master
        self.compare_export_folder_button = ttk.Button(
            actions,
            text="Exporter toutes les analyses dans un dossier",
            state="disabled",
            style="Primary.TButton",
            command=self._export_all_regime_comparison_analyses,
        )
        self.compare_export_folder_button.pack(side="right", padx=(0, 6))

    def _regime_comparison_completed(self, summary):
        super()._regime_comparison_completed(summary)
        if hasattr(self, "compare_export_folder_button"):
            self.compare_export_folder_button.configure(state="normal")

    def _show_regime_comparison_history(self):
        super()._show_regime_comparison_history()
        if self.compare_last_id and hasattr(self, "compare_export_folder_button"):
            self.compare_export_folder_button.configure(state="normal")

    def _export_all_regime_comparison_analyses(self):
        if not self.compare_last_id:
            messagebox.showwarning("Export", "Lancez ou rouvrez d'abord une comparaison.")
            return
        folder = filedialog.askdirectory(title="Choisir le dossier parent pour toutes les analyses")
        if not folder:
            return

        self._background(
            lambda: self.regime_comparison_folder_exporter.export_all(
                self.compare_last_id,
                folder,
                progress=self._progress,
            ),
            self._regime_comparison_folder_export_completed,
            operation="Export complet des analyses de comparaison de régimes",
        )

    def _regime_comparison_folder_export_completed(self, folder):
        messagebox.showinfo(
            "Export terminé",
            "Toutes les analyses de la comparaison ont été exportées dans :\n" + str(folder),
        )
