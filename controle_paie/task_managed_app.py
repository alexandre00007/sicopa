from __future__ import annotations

from tkinter import filedialog, messagebox

from .raw_period_comparison_fusion_aware_app import PayrollAppWithFusionAwareRawPeriodComparison
from .task_manager import TaskManager


class PayrollAppWithTaskManager(PayrollAppWithFusionAwareRawPeriodComparison):
    """Active la gestion centralisee des traitements asynchrones sensibles."""

    def __init__(self, *args, **kwargs):
        self.task_manager = None
        super().__init__(*args, **kwargs)
        self.task_manager = TaskManager(self)

    def _tm(self) -> TaskManager:
        if self.task_manager is None:
            self.task_manager = TaskManager(self)
        return self.task_manager

    def _generation_failed(self, summary):
        try:
            self._tm().handle_failure()
        finally:
            return super()._generation_failed(summary)

    def _find_button_by_text(self, text):
        def walk(widget):
            for child in widget.winfo_children():
                try:
                    if child.winfo_class() in {"TButton", "Button"} and str(child.cget("text")) == text:
                        return child
                except Exception:
                    pass
                found = walk(child)
                if found is not None:
                    return found
            return None
        return walk(self)

    # ------------------------------------------------------------------
    # Comparaison RAW par periode
    # ------------------------------------------------------------------
    def _rpc_analyze(self):
        a = self.rpc_table_a.get().strip()
        b = self.rpc_table_b.get().strip()
        q = self.rpc_quarter.get()
        y = self.rpc_year.get()
        if not a or not b:
            messagebox.showwarning("Comparaison RAW", "Selectionnez les tables A et B.")
            return
        self._tm().run(
            lambda: self.raw_period_comparison_service.analyze(a, b, q, int(y), progress=self._progress),
            self._rpc_analysis_done,
            operation="Comparaison RAW par periode",
            controls=[self.rpc_analyze_btn, self.rpc_reanalyze_btn],
            loader_title="Comparaison RAW par periode",
            loader_detail=f"{a} <-> {b} - {q} {y}\nMatching par matricule et par nom, ecarts et doublons.",
        )

    def _rpc_reanalyze(self):
        if not self.rpc_last_id:
            messagebox.showwarning("Reanalyse", "Aucune comparaison chargee.")
            return
        info = self.raw_period_comparison_service.get_comparison(self.rpc_last_id)
        if not messagebox.askyesno(
            "Reanalyser",
            f"Recalculer {info['table_a']} <-> {info['table_b']} pour {info['quarter']} {info['year']} ?",
        ):
            return
        self._tm().run(
            lambda: self.raw_period_comparison_service.reanalyze(self.rpc_last_id, progress=self._progress),
            self._rpc_analysis_done,
            operation="Reanalyse comparaison RAW",
            controls=[self.rpc_analyze_btn, self.rpc_reanalyze_btn],
            loader_title="Reanalyse RAW",
            loader_detail=f"{info['table_a']} <-> {info['table_b']} - {info['quarter']} {info['year']}",
        )

    def _rpc_export(self):
        if not self.rpc_last_id:
            messagebox.showwarning("Export", "Aucune comparaison chargee.")
            return
        folder = filedialog.askdirectory(title="Choisir le dossier parent de l'export RAW")
        if not folder:
            return
        export_button = self._find_button_by_text("Exporter toutes les analyses")
        self._tm().run(
            lambda: self.raw_period_comparison_service.export_all(self.rpc_last_id, folder, progress=self._progress),
            self._rpc_export_done,
            operation="Export comparaison RAW",
            controls=[export_button],
            loader_title="Export comparaison RAW",
            loader_detail="Creation des analyses et annexes RAW completes A/B.",
        )

    # ------------------------------------------------------------------
    # Fusion & analyse multi-regimes
    # ------------------------------------------------------------------
    def _run_raw_fusion(self):
        tables = self._selected_raw_fusion_tables()
        if len(tables) < 2:
            messagebox.showwarning("Fusion RAW", "Selectionnez au moins deux tables RAW.")
            return
        quarter = self.raw_fusion_quarter.get()
        year = self.raw_fusion_year.get()
        suffix = self.raw_fusion_suffix.get().strip()
        run_button = self._find_button_by_text("Fusionner et analyser")
        self._tm().run(
            lambda: self.raw_fusion_service.create_fusion(
                tables, quarter, int(year), suffix, progress=self._progress
            ),
            self._raw_fusion_completed_with_loader,
            operation="Fusion RAW multi-regimes",
            controls=[run_button, getattr(self, "raw_reanalyze_button", None)],
            loader_title="Fusion & analyse multi-regimes",
            loader_detail=(
                f"{len(tables)} tables RAW - {quarter} {year}\n"
                "Fusion, analyse, doublons et matrice en arriere-plan."
            ),
        )

    def _reanalyze_current_raw_fusion(self):
        if getattr(self, "busy", False):
            messagebox.showwarning("Traitement en cours", "Attendez la fin du traitement actuel.")
            return
        if not getattr(self, "raw_fusion_last_id", ""):
            messagebox.showwarning("Reanalyse", "Lancez ou rouvrez d'abord une fusion.")
            return
        info = self.raw_fusion_service.get_fusion(self.raw_fusion_last_id)
        if not messagebox.askyesno(
            "Reanalyser",
            f"Recalculer toutes les analyses de {info['table']} ?\n\n"
            "La table RAW fusionnee restera intacte.",
        ):
            return
        run_button = self._find_button_by_text("Fusionner et analyser")
        self._progress(5, "Initialisation de la reanalyse")
        self._tm().run(
            lambda: self.raw_fusion_service.reanalyze(self.raw_fusion_last_id, progress=self._progress),
            self._raw_reanalysis_completed,
            operation="Reanalyse fusion multi-regimes",
            controls=[getattr(self, "raw_reanalyze_button", None), run_button],
            loader_title="Reanalyse multi-regimes",
            loader_detail=(
                f"Table : {info['table']}\n"
                "Recalcul des agents, regimes, institutions, masses, identites et doublons."
            ),
        )

    def _export_raw_fusion(self):
        if not self.raw_fusion_last_id:
            messagebox.showwarning("Export", "Lancez ou rouvrez d'abord une fusion.")
            return
        folder = filedialog.askdirectory(title="Choisir le dossier parent pour l'export multi-regimes")
        if not folder:
            return
        info = self.raw_fusion_service.get_fusion(self.raw_fusion_last_id)
        export_button = self._find_button_by_text("Exporter tout dans un dossier")
        self._tm().run(
            lambda: self.raw_fusion_service.export_all(self.raw_fusion_last_id, folder, progress=self._progress),
            self._raw_export_completed,
            operation="Export fusion multi-regimes",
            controls=[export_button],
            loader_title="Export des analyses multi-regimes",
            loader_detail=(
                f"Table : {info['table']}\n"
                "Creation de la synthese, des annexes, doublons et matrice."
            ),
        )
