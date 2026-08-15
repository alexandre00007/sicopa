from __future__ import annotations

from tkinter import filedialog, messagebox, ttk

from .raw_period_occurrence_app import PayrollAppWithRawOccurrenceDetails
from .reliable_package_services import (
    ReliableListingGroupAnalysisService,
    ReliableMultiRegimeAnalysisService,
    ReliableReportService,
)


class PayrollAppWithReliableExports(PayrollAppWithRawOccurrenceDetails):
    """Point d'entrée final avec publication atomique et exports gros volumes."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.multi_analysis = ReliableMultiRegimeAnalysisService(self.db)
        self.listing_analysis = ReliableListingGroupAnalysisService(self.db)
        self.reports = ReliableReportService(self.db)

    def _build_ui(self):
        super()._build_ui()
        self._install_sql_parquet_export()

    def _install_sql_parquet_export(self):
        if not hasattr(self, "sql_result_tree"):
            return
        result_box = self.sql_result_tree.master.master
        bar = ttk.Frame(result_box)
        bar.pack(fill="x", pady=(0, 4))
        ttk.Label(
            bar,
            text="Très gros résultat : utilisez Parquet pour conserver les types et réduire la taille du fichier.",
            style="PageHint.TLabel",
        ).pack(side="left")
        ttk.Button(
            bar,
            text="Exporter Parquet",
            style="Secondary.TButton",
            command=self._export_sql_parquet,
        ).pack(side="right")

    def _export_sql_parquet(self):
        if not getattr(self, "sql_last_query", ""):
            messagebox.showwarning("Export SQL", "Exécutez d'abord une requête valide.")
            return
        target = filedialog.asksaveasfilename(
            defaultextension=".parquet",
            filetypes=[("Parquet", "*.parquet")],
        )
        if not target:
            return
        try:
            path = self.sql_console_service.export_parquet(self.sql_last_query, target)
        except Exception as exc:
            messagebox.showerror("Export SQL", str(exc))
            return
        messagebox.showinfo("Export SQL", f"Résultat exporté :\n{path}")
