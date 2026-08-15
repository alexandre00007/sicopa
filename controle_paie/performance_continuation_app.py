from __future__ import annotations

import logging
import math
import queue
import tkinter as tk
from tkinter import messagebox, ttk

from .cancellation import TaskCancelledError
from .errors import explain_error
from .performance_health_app import PayrollAppWithPerformanceHealth


class PayrollAppWithPerformanceContinuation(PayrollAppWithPerformanceHealth):
    """Suite Lot 3 : annulation cooperative + pagination serveur des gros listings."""

    def __init__(self, *args, **kwargs):
        self.rpc_page = 1
        self.rpc_page_size = 250
        self.raw_fusion_page = 1
        self.raw_fusion_page_size = 250
        self.compare_page = 1
        self.compare_page_size = 250
        super().__init__(*args, **kwargs)
        self._install_cancel_action()
        self._install_rpc_pagination()
        self._install_fusion_pagination()
        self._install_regime_pagination()

    # ------------------------------------------------------------------
    # Annulation cooperative
    # ------------------------------------------------------------------
    def _install_cancel_action(self):
        if not hasattr(self, "performance_health_page"):
            return
        bar = ttk.Frame(self.performance_health_page)
        bar.pack(fill="x", pady=(0, 10))
        self.cancel_task_btn = ttk.Button(
            bar, text="Annuler le traitement en cours", style="Secondary.TButton",
            command=self._request_task_cancel,
        )
        self.cancel_task_btn.pack(side="left")
        self.cancel_task_status = tk.StringVar(
            value="Annulation coopérative : l'arrêt se fait au prochain point de progression sûr."
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

    def _background(self, task, success, refresh_data=False, operation=""):
        """Même moteur asynchrone que l'UI de base, avec un événement ANNULE distinct."""
        if self.busy:
            messagebox.showwarning("Traitement en cours", "Attendez la fin du traitement actuel avant d'en lancer un autre.")
            return False
        if not operation:
            operation = (self.generation_title.get() if self.generation_window
                         and self.generation_window.winfo_exists() else "Traitement SICORPA")
        self.busy = True
        self._set_busy_ui(True)
        self.status.set("Traitement en cours…")
        self.progress.stop()
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)

        def worker():
            try:
                self.events.put(("success", (success, task(), refresh_data)))
            except TaskCancelledError as exc:
                logging.info("Traitement annulé par l'utilisateur : %s", operation)
                self.events.put(("cancelled", (exc, operation)))
            except Exception as exc:
                logging.exception("Échec d’un traitement en arrière-plan")
                import traceback
                self.events.put(("error", (exc, traceback.format_exc(), operation)))

        import threading
        threading.Thread(target=worker, daemon=True).start()
        return True

    def _poll_events(self):
        """Traite ANNULE séparément d'ERREUR et restaure systématiquement TaskManager."""
        try:
            processed = 0
            while True:
                kind, payload = self.events.get_nowait()
                processed += 1
                if kind == "progress":
                    value, text = payload
                    self.status.set(text)
                    if value < 0:
                        self.progress.stop(); self.progress.configure(mode="indeterminate"); self.progress.start(12)
                    else:
                        self.progress.stop(); self.progress.configure(mode="determinate"); self.progress["value"] = value
                    self._update_generation_dialog(value, text)
                elif kind == "success":
                    callback, result, refresh_data = payload
                    self.busy = False; self._set_busy_ui(False); self.status.set("Prêt")
                    self.progress.stop(); self.progress.configure(mode="determinate"); self.progress["value"] = 100
                    if refresh_data:
                        try:
                            self._refresh_dashboard(); self._refresh_explorer_tables()
                        except Exception:
                            logging.exception("Échec du rafraîchissement de l’interface")
                    try:
                        callback(result)
                    except Exception as exc:
                        import traceback
                        logging.exception("Échec de la finalisation d’un traitement")
                        self._show_explicit_error(exc, "Finalisation du traitement", traceback.format_exc())
                elif kind == "cancelled":
                    _error, operation = payload
                    self.busy = False; self._set_busy_ui(False); self.status.set("Annulé")
                    self.progress.stop(); self.progress.configure(mode="determinate"); self.progress["value"] = 0
                    manager = getattr(self, "task_manager", None)
                    if manager is not None:
                        manager.handle_failure()
                    if hasattr(self, "cancel_task_status"):
                        self.cancel_task_status.set(f"ANNULE — {operation}")
                    if self.generation_window and self.generation_window.winfo_exists():
                        self.generation_bar.stop(); self.generation_bar.configure(mode="determinate"); self.generation_bar["value"] = 0
                        self.generation_title.set("Traitement annulé")
                        self.generation_status.set(f"ANNULE — {operation}")
                        self.generation_close.configure(state="normal")
                        self.generation_window.protocol("WM_DELETE_WINDOW", self.generation_window.destroy)
                    logging.info("ANNULE — %s", operation)
                else:
                    error, traceback_text, operation = payload
                    self.busy = False; self._set_busy_ui(False); self.status.set("Erreur")
                    self.progress.stop(); self.progress.configure(mode="determinate")
                    manager = getattr(self, "task_manager", None)
                    if manager is not None:
                        manager.handle_failure()
                    report = explain_error(error, traceback_text, operation)
                    self._generation_failed(report.summary)
                    self._show_explicit_error(error, operation, traceback_text)
                if processed >= 100:
                    break
        except queue.Empty:
            pass
        self.after(10 if not self.events.empty() else 100, self._poll_events)

    # ------------------------------------------------------------------
    # Helpers pagination
    # ------------------------------------------------------------------
    @staticmethod
    def _page_bounds(total: int, page: int, page_size: int):
        page_size = max(25, min(int(page_size), 2000))
        total_pages = max(1, math.ceil(int(total or 0) / page_size))
        page = max(1, min(int(page), total_pages))
        return page, page_size, total_pages, (page - 1) * page_size

    def _pagination_bar(self, parent, prev_cmd, next_cmd, reset_cmd, size_var, label_var):
        frame = ttk.Frame(parent)
        frame.pack(fill="x", pady=(6, 0))
        prev = ttk.Button(frame, text="◀ Page précédente", command=prev_cmd)
        prev.pack(side="left")
        nxt = ttk.Button(frame, text="Page suivante ▶", command=next_cmd)
        nxt.pack(side="left", padx=6)
        ttk.Label(frame, text="Lignes/page :", style="PageHint.TLabel").pack(side="left", padx=(12, 4))
        size = ttk.Combobox(frame, textvariable=size_var, values=("100", "250", "500", "1000", "2000"), width=7, state="readonly")
        size.pack(side="left")
        size.bind("<<ComboboxSelected>>", lambda _e: reset_cmd())
        ttk.Label(frame, textvariable=label_var).pack(side="left", padx=12)
        return prev, nxt

    # ------------------------------------------------------------------
    # Comparaison RAW
    # ------------------------------------------------------------------
    def _install_rpc_pagination(self):
        if not hasattr(self, "rpc_tree"):
            return
        self.rpc_page_size_var = tk.StringVar(value=str(self.rpc_page_size))
        self.rpc_page_label = tk.StringVar(value="Page 1 / 1")
        self.rpc_prev_btn, self.rpc_next_btn = self._pagination_bar(
            self.rpc_tree.master, self._rpc_prev_page, self._rpc_next_page, self._rpc_reset_page,
            self.rpc_page_size_var, self.rpc_page_label,
        )

    def _rpc_reset_page(self):
        self.rpc_page = 1
        self.rpc_page_size = int(self.rpc_page_size_var.get() or 250)
        self._rpc_refresh_results()

    def _rpc_prev_page(self):
        if self.rpc_page > 1:
            self.rpc_page -= 1; self._rpc_refresh_results()

    def _rpc_next_page(self):
        if self.rpc_page < getattr(self, "rpc_total_pages", 1):
            self.rpc_page += 1; self._rpc_refresh_results()

    def _rpc_refresh_results(self):
        if not getattr(self, "rpc_last_id", ""):
            return
        service = self.raw_period_comparison_service
        if not hasattr(service, "page_results_enriched"):
            return super()._rpc_refresh_results()
        selected = self.rpc_filter.get(); status = "" if selected == "Tous" else selected
        data = service.page_results_enriched(self.rpc_last_id, status, self.rpc_page, int(self.rpc_page_size_var.get()))
        self.rpc_page, self.rpc_total_pages = data["page"], data["total_pages"]
        self.rpc_tree.delete(*self.rpc_tree.get_children())
        for row in data["rows"]:
            vals = list(row)
            for index in (19,20,21,22,23,24): vals[index] = f"{float(vals[index] or 0):,.2f}".replace(",", " ")
            self.rpc_tree.insert("", "end", values=vals)
        self.rpc_page_label.set(f"Page {data['page']} / {data['total_pages']} — {data['total']:,} résultat(s)".replace(",", " "))
        self.rpc_prev_btn.configure(state="normal" if data["page"] > 1 else "disabled")
        self.rpc_next_btn.configure(state="normal" if data["page"] < data["total_pages"] else "disabled")
        self.rpc_status.set(f"{len(data['rows'])} affiché(s) sur {data['total']:,} — page {data['page']}/{data['total_pages']}. Export exhaustif.".replace(",", " "))

    # ------------------------------------------------------------------
    # Fusion multi-regimes
    # ------------------------------------------------------------------
    def _install_fusion_pagination(self):
        if not hasattr(self, "raw_fusion_results"):
            return
        self.raw_fusion_page_size_var = tk.StringVar(value=str(self.raw_fusion_page_size))
        self.raw_fusion_page_label = tk.StringVar(value="Page 1 / 1")
        self.raw_fusion_prev_btn, self.raw_fusion_next_btn = self._pagination_bar(
            self.raw_fusion_results.master, self._fusion_prev_page, self._fusion_next_page, self._fusion_reset_page,
            self.raw_fusion_page_size_var, self.raw_fusion_page_label,
        )

    def _fusion_reset_page(self):
        self.raw_fusion_page = 1; self._refresh_raw_fusion_results()
    def _fusion_prev_page(self):
        if self.raw_fusion_page > 1: self.raw_fusion_page -= 1; self._refresh_raw_fusion_results()
    def _fusion_next_page(self):
        if self.raw_fusion_page < getattr(self, "raw_fusion_total_pages", 1): self.raw_fusion_page += 1; self._refresh_raw_fusion_results()

    def _refresh_raw_fusion_results(self):
        if not getattr(self, "raw_fusion_last_id", "") or not hasattr(self, "raw_fusion_page_label"):
            return super()._refresh_raw_fusion_results()
        selected = self.raw_fusion_filter.get(); status = "" if selected == "Tous" else selected
        cond = "fusion_id=?"; params = [self.raw_fusion_last_id]
        if status: cond += " AND statut=?"; params.append(status)
        page_size = int(self.raw_fusion_page_size_var.get())
        with self.db.connect() as con:
            total = int(con.execute(f"SELECT COUNT(*) FROM resultats_fusion_multi WHERE {cond}", params).fetchone()[0])
            page, page_size, total_pages, offset = self._page_bounds(total, self.raw_fusion_page, page_size)
            rows = con.execute(f"""SELECT statut,matricule_normalise,nom,prenom,regimes,nb_regimes,nb_institutions,
                occurrences,masse_brute,masse_net,sections,categories,grades,unites_affectation,provinces,
                paiement_multi_regime,paiement_multiple_meme_regime,identite_incoherente,diagnostic
                FROM resultats_fusion_multi WHERE {cond}
                ORDER BY nb_regimes DESC,occurrences DESC,masse_brute DESC LIMIT ? OFFSET ?""", params + [page_size, offset]).fetchall()
        self.raw_fusion_page, self.raw_fusion_total_pages = page, total_pages
        self.raw_fusion_results.delete(*self.raw_fusion_results.get_children())
        for row in rows:
            values=list(row); values[8]=f"{float(values[8] or 0):,.2f}".replace(","," "); values[9]=f"{float(values[9] or 0):,.2f}".replace(","," ")
            self.raw_fusion_results.insert("","end",values=values)
        self.raw_fusion_page_label.set(f"Page {page}/{total_pages} — {total:,} agent(s)".replace(",", " "))
        self.raw_fusion_prev_btn.configure(state="normal" if page > 1 else "disabled")
        self.raw_fusion_next_btn.configure(state="normal" if page < total_pages else "disabled")
        self.raw_fusion_status.set(f"{len(rows)} agent(s) affiché(s) sur {total:,} — filtre {selected}.".replace(",", " "))

    # ------------------------------------------------------------------
    # Comparaison regime vs regime
    # ------------------------------------------------------------------
    def _install_regime_pagination(self):
        if not hasattr(self, "compare_result_tree"):
            return
        self.compare_page_size_var = tk.StringVar(value=str(self.compare_page_size))
        self.compare_page_label = tk.StringVar(value="Page 1 / 1")
        self.compare_prev_btn, self.compare_next_btn = self._pagination_bar(
            self.compare_result_tree.master, self._compare_prev_page, self._compare_next_page, self._compare_reset_page,
            self.compare_page_size_var, self.compare_page_label,
        )

    def _compare_reset_page(self):
        self.compare_page = 1; self._refresh_regime_comparison_results()
    def _compare_prev_page(self):
        if self.compare_page > 1: self.compare_page -= 1; self._refresh_regime_comparison_results()
    def _compare_next_page(self):
        if self.compare_page < getattr(self, "compare_total_pages", 1): self.compare_page += 1; self._refresh_regime_comparison_results()

    def _refresh_regime_comparison_results(self):
        if not getattr(self, "compare_last_id", "") or not hasattr(self, "compare_page_label"):
            return super()._refresh_regime_comparison_results()
        selected = self.compare_result_filter.get()
        status = "" if selected == "Tous" else "DOUBLE_PAIEMENT" if selected == "Payés dans les deux" else selected
        cond = "comparaison_id=?"; params = [self.compare_last_id]
        if status == "DOUBLE_PAIEMENT": cond += " AND double_paiement"
        elif status: cond += " AND statut=?"; params.append(status)
        page_size = int(self.compare_page_size_var.get())
        with self.db.connect() as con:
            total = int(con.execute(f"SELECT COUNT(*) FROM resultats_comparaison_regimes WHERE {cond}", params).fetchone()[0])
            page, page_size, total_pages, offset = self._page_bounds(total, self.compare_page, page_size)
            rows = con.execute(f"""SELECT statut,cle_type,COALESCE(matricule_a,matricule_b,''),
                    COALESCE(NULLIF(nom_a,''),nom_b,''),occurrences_a,occurrences_b,
                    remuneration_a,remuneration_b,ecart_remuneration,net_a,net_b,ecart_net,ecart_pourcentage,
                    COALESCE(grade_a,''),COALESCE(grade_b,''),COALESCE(categorie_a,''),COALESCE(categorie_b,''),
                    COALESCE(affectation_a,''),COALESCE(affectation_b,''),diagnostic
                FROM resultats_comparaison_regimes WHERE {cond}
                ORDER BY CASE WHEN statut='COMMUN_IDENTIQUE' THEN 1 ELSE 0 END,ABS(ecart_remuneration) DESC,nom_a,nom_b
                LIMIT ? OFFSET ?""", params + [page_size, offset]).fetchall()
        self.compare_page, self.compare_total_pages = page, total_pages
        self.compare_result_tree.delete(*self.compare_result_tree.get_children())
        for row in rows:
            values = list(row)
            for index in [6,7,8,9,10,11]: values[index] = f"{float(values[index] or 0):,.2f}".replace(",", " ")
            values[12] = f"{float(values[12] or 0):.2f}%"
            self.compare_result_tree.insert("", "end", values=values)
        self.compare_page_label.set(f"Page {page}/{total_pages} — {total:,} résultat(s)".replace(",", " "))
        self.compare_prev_btn.configure(state="normal" if page > 1 else "disabled")
        self.compare_next_btn.configure(state="normal" if page < total_pages else "disabled")
        self.compare_status.set(f"{len(rows)} affiché(s) sur {total:,} pour « {selected} » — page {page}/{total_pages}.".replace(",", " "))
