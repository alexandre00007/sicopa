from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from .performance_health_app import PayrollAppWithPerformanceHealth


class PayrollAppWithPerformanceContinuation(PayrollAppWithPerformanceHealth):
    """Suite Lot 3 : annulation cooperative + pagination serveur des resultats RAW."""

    def __init__(self, *args, **kwargs):
        self.rpc_page = 1
        self.rpc_page_size = 250
        super().__init__(*args, **kwargs)
        self._install_cancel_action()
        self._install_rpc_pagination()

    # ------------------------------------------------------------------
    # Annulation cooperative
    # ------------------------------------------------------------------
    def _install_cancel_action(self):
        if not hasattr(self, "performance_health_page"):
            return
        bar = ttk.Frame(self.performance_health_page)
        bar.pack(fill="x", pady=(0, 10))
        self.cancel_task_btn = ttk.Button(
            bar,
            text="Annuler le traitement en cours",
            style="Secondary.TButton",
            command=self._request_task_cancel,
        )
        self.cancel_task_btn.pack(side="left")
        self.cancel_task_status = tk.StringVar(
            value="Annulation cooperative : l'arret se fait au prochain point de progression sur."
        )
        ttk.Label(bar, textvariable=self.cancel_task_status, style="PageHint.TLabel").pack(side="left", padx=10)

    def _request_task_cancel(self):
        manager = getattr(self, "task_manager", None)
        if manager is None or not manager.cancellable:
            messagebox.showinfo("Annulation", "Aucun traitement annulable n'est actuellement en cours.")
            return
        operation = manager.active_operation or "Traitement"
        if not messagebox.askyesno(
            "Annuler le traitement",
            f"Demander l'arrêt de : {operation} ?\n\n"
            "L'arrêt sera appliqué au prochain point de progression sûr. Une requête DuckDB déjà engagée n'est pas interrompue brutalement.",
        ):
            return
        manager.request_cancel()
        self.cancel_task_status.set(f"Annulation demandée pour : {operation}")

    def _progress(self, value, text=""):
        manager = getattr(self, "task_manager", None)
        if manager is not None:
            manager.check_cancelled()
        return super()._progress(value, text)

    # ------------------------------------------------------------------
    # Pagination serveur Comparaison RAW
    # ------------------------------------------------------------------
    def _install_rpc_pagination(self):
        if not hasattr(self, "rpc_tree"):
            return
        frame = ttk.Frame(self.rpc_tree.master)
        frame.pack(fill="x", pady=(6, 0))
        self.rpc_prev_btn = ttk.Button(frame, text="◀ Page précédente", command=self._rpc_prev_page)
        self.rpc_prev_btn.pack(side="left")
        self.rpc_next_btn = ttk.Button(frame, text="Page suivante ▶", command=self._rpc_next_page)
        self.rpc_next_btn.pack(side="left", padx=6)
        ttk.Label(frame, text="Lignes/page :", style="PageHint.TLabel").pack(side="left", padx=(12, 4))
        self.rpc_page_size_var = tk.StringVar(value=str(self.rpc_page_size))
        size = ttk.Combobox(
            frame, textvariable=self.rpc_page_size_var,
            values=("100", "250", "500", "1000", "2000"), width=7, state="readonly",
        )
        size.pack(side="left")
        size.bind("<<ComboboxSelected>>", lambda _e: self._rpc_reset_page())
        self.rpc_page_label = tk.StringVar(value="Page 1 / 1")
        ttk.Label(frame, textvariable=self.rpc_page_label).pack(side="left", padx=12)

    def _rpc_reset_page(self):
        self.rpc_page = 1
        try:
            self.rpc_page_size = int(self.rpc_page_size_var.get())
        except Exception:
            self.rpc_page_size = 250
        self._rpc_refresh_results()

    def _rpc_prev_page(self):
        if self.rpc_page > 1:
            self.rpc_page -= 1
            self._rpc_refresh_results()

    def _rpc_next_page(self):
        total_pages = getattr(self, "rpc_total_pages", 1)
        if self.rpc_page < total_pages:
            self.rpc_page += 1
            self._rpc_refresh_results()

    def _rpc_refresh_results(self):
        if not getattr(self, "rpc_last_id", ""):
            return
        service = self.raw_period_comparison_service
        if not hasattr(service, "page_results_enriched"):
            return super()._rpc_refresh_results()

        selected = self.rpc_filter.get()
        status = "" if selected == "Tous" else selected
        try:
            page_size = int(getattr(self, "rpc_page_size_var", tk.StringVar(value="250")).get())
        except Exception:
            page_size = self.rpc_page_size
        data = service.page_results_enriched(
            self.rpc_last_id, status, page=self.rpc_page, page_size=page_size
        )
        self.rpc_page = data["page"]
        self.rpc_total_pages = data["total_pages"]
        self.rpc_tree.delete(*self.rpc_tree.get_children())
        for row in data["rows"]:
            vals = list(row)
            for index in (19,20,21,22,23,24):
                vals[index] = f"{float(vals[index] or 0):,.2f}".replace(",", " ")
            self.rpc_tree.insert("", "end", values=vals)

        if hasattr(self, "rpc_page_label"):
            self.rpc_page_label.set(
                f"Page {data['page']} / {data['total_pages']} — {data['total']:,} résultat(s)".replace(",", " ")
            )
            self.rpc_prev_btn.configure(state="normal" if data["page"] > 1 else "disabled")
            self.rpc_next_btn.configure(state="normal" if data["page"] < data["total_pages"] else "disabled")
        self.rpc_status.set(
            f"{len(data['rows'])} affiché(s) sur {data['total']:,} — page {data['page']}/{data['total_pages']}. "
            "L'export reste exhaustif et indépendant de la pagination.".replace(",", " ")
        )
