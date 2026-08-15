from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from .data_architecture_final_app import PayrollAppWithFinalDataArchitecture
from .performance_health import PerformanceHealthService


class PayrollAppWithPerformanceHealth(PayrollAppWithFinalDataArchitecture):
    """Lot 3 : sante DuckDB, maintenance prudente et indicateurs performance."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.performance_health_service = PerformanceHealthService(
            self.db, getattr(self, "raw_catalog_service", None)
        )
        self._add_performance_health_tab()
        self._refresh_performance_health()

    def _add_performance_health_tab(self):
        outer, body = self._make_scrollable_tab()
        self.performance_health_page = body
        self._tab_shells["performance_health_page"] = outer
        self.notebook.add(outer, text="  Santé & Maintenance  ")
        self._page_heading(
            body,
            "Santé, performance & maintenance",
            "Surveillez DuckDB, les fichiers temporaires et l'état des traitements sans charger les gros volumes en mémoire.",
        )

        actions = ttk.Frame(body)
        actions.pack(fill="x", pady=(0, 12))
        ttk.Button(actions, text="Actualiser", style="Primary.TButton",
                   command=self._refresh_performance_health).pack(side="left")
        ttk.Button(actions, text="CHECKPOINT DuckDB", style="Secondary.TButton",
                   command=self._run_checkpoint).pack(side="left", padx=6)
        ttk.Button(actions, text="Rafraîchir catalogue RAW", style="Secondary.TButton",
                   command=self._refresh_catalog_health).pack(side="left", padx=6)
        ttk.Button(actions, text="Nettoyer temporaires anciens", style="Secondary.TButton",
                   command=self._cleanup_old_temp).pack(side="left", padx=6)

        self.performance_health_status = tk.StringVar(value="")
        ttk.Label(body, textvariable=self.performance_health_status, style="PageHint.TLabel").pack(fill="x", pady=(0, 10))

        metrics = ttk.LabelFrame(body, text="État DuckDB", style="Section.TLabelframe", padding=12)
        metrics.pack(fill="x", pady=(0, 12))
        self.performance_health_vars = {}
        labels = [
            ("database_size_text", "Taille base"),
            ("temp_size_text", "Temporaires"),
            ("raw_tables", "Tables RAW"),
            ("tables", "Tables DuckDB"),
            ("threads", "Threads"),
            ("memory_limit_mb", "Limite mémoire (Mo)"),
            ("running_treatments", "Traitements en cours"),
            ("errors_7d", "Erreurs 7 jours"),
        ]
        for i, (key, title) in enumerate(labels):
            box = ttk.Frame(metrics)
            box.grid(row=i // 4, column=i % 4, sticky="nsew", padx=6, pady=6)
            metrics.columnconfigure(i % 4, weight=1)
            ttk.Label(box, text=title, style="PageHint.TLabel").pack(anchor="w")
            var = tk.StringVar(value="-")
            self.performance_health_vars[key] = var
            ttk.Label(box, textvariable=var).pack(anchor="w")

        paths = ttk.LabelFrame(body, text="Emplacements", style="Section.TLabelframe", padding=12)
        paths.pack(fill="x")
        self.performance_db_path = tk.StringVar(value="")
        self.performance_temp_path = tk.StringVar(value="")
        ttk.Label(paths, text="Base DuckDB :", style="PageHint.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(paths, textvariable=self.performance_db_path).grid(row=0, column=1, sticky="w", padx=8)
        ttk.Label(paths, text="Répertoire temporaire :", style="PageHint.TLabel").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Label(paths, textvariable=self.performance_temp_path).grid(row=1, column=1, sticky="w", padx=8, pady=(6, 0))

    def _refresh_performance_health(self):
        if not hasattr(self, "performance_health_service"):
            return
        try:
            snapshot = self.performance_health_service.snapshot()
            for key, var in getattr(self, "performance_health_vars", {}).items():
                var.set(str(snapshot.get(key, "-")))
            if hasattr(self, "performance_db_path"):
                self.performance_db_path.set(snapshot.get("database_path", ""))
                self.performance_temp_path.set(snapshot.get("temp_path", ""))
            if hasattr(self, "performance_health_status"):
                self.performance_health_status.set("État actualisé.")
        except Exception as exc:
            if hasattr(self, "performance_health_status"):
                self.performance_health_status.set(f"Erreur de diagnostic : {exc}")

    def _run_checkpoint(self):
        try:
            result = self.performance_health_service.checkpoint()
            self._refresh_performance_health()
            self.performance_health_status.set(f"CHECKPOINT terminé en {result['seconds']} s.")
        except Exception as exc:
            messagebox.showerror("Maintenance", str(exc))

    def _refresh_catalog_health(self):
        try:
            count = self.performance_health_service.refresh_catalog()
            self._refresh_performance_health()
            self.performance_health_status.set(f"Catalogue RAW actualisé : {count} table(s).")
        except Exception as exc:
            messagebox.showerror("Catalogue RAW", str(exc))

    def _cleanup_old_temp(self):
        if not messagebox.askyesno(
            "Nettoyage des temporaires",
            "Supprimer uniquement les fichiers temporaires DuckDB âgés de plus de 24 heures ?",
        ):
            return
        try:
            result = self.performance_health_service.cleanup_orphan_temp_files(24)
            self._refresh_performance_health()
            self.performance_health_status.set(
                f"{result['files']} fichier(s) supprimé(s), {result.get('bytes_text', '0 o')} libéré(s)."
            )
        except Exception as exc:
            messagebox.showerror("Nettoyage", str(exc))
