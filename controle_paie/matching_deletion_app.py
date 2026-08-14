from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from .matching_deletion import MatchingDeletionService
from .raw_fusion_period_app import PayrollAppWithPeriodAwareRawFusion
from .runtime import backup_database


class PayrollAppWithMatchingDeletion(PayrollAppWithPeriodAwareRawFusion):
    """Ajoute un historique des rapprochements avec suppression sécurisée."""

    def _build_matching(self):
        super()._build_matching()
        self.matching_deletion = MatchingDeletionService(self.db)
        tab = ttk.Frame(self.matching_tabs, padding=12)
        self.matching_tabs.add(tab, text="  Historique & suppression  ")
        self._build_matching_deletion(tab)

    def _build_matching_deletion(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)

        top = ttk.Frame(parent)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(
            top,
            text="Supprime uniquement les résultats du rapprochement sélectionné. Les données de paie et déclaratives restent intactes.",
            style="PageHint.TLabel",
        ).pack(side="left")
        ttk.Button(top, text="Actualiser", style="Secondary.TButton", command=self._refresh_matching_history).pack(side="right")

        frame = ttk.Frame(parent)
        frame.grid(row=1, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        columns = ("institution","regime","period","rows","validated","mass","impact","execution")
        self.matching_history_tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="browse")
        specs = [
            ("institution","Institution",250),("regime","Régime",100),("period","Période",90),
            ("rows","Lignes",85),("validated","Validées",85),("mass","Masse contrôlée",135),
            ("impact","Impact potentiel",135),("execution","Exécution",260),
        ]
        for col, title, width in specs:
            self.matching_history_tree.heading(col, text=title)
            self.matching_history_tree.column(col, width=width, anchor="w")
        sy = ttk.Scrollbar(frame, orient="vertical", command=self.matching_history_tree.yview)
        sx = ttk.Scrollbar(frame, orient="horizontal", command=self.matching_history_tree.xview)
        self.matching_history_tree.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        self.matching_history_tree.grid(row=0, column=0, sticky="nsew")
        sy.grid(row=0, column=1, sticky="ns")
        sx.grid(row=1, column=0, sticky="ew")

        actions = ttk.Frame(parent)
        actions.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        self.matching_delete_status = tk.StringVar(value="Sélectionnez un rapprochement à supprimer.")
        ttk.Label(actions, textvariable=self.matching_delete_status, style="PageHint.TLabel").pack(side="left")
        self.matching_delete_button = ttk.Button(
            actions,
            text="Supprimer le rapprochement",
            command=self._delete_selected_matching,
        )
        self.matching_delete_button.pack(side="right")

        self._matching_history_ids = {}
        self._refresh_matching_history()

    def _refresh_matching_history(self):
        if not hasattr(self, "matching_history_tree"):
            return
        self.matching_history_tree.delete(*self.matching_history_tree.get_children())
        self._matching_history_ids = {}
        try:
            rows = self.matching_deletion.list_runs()
        except Exception as exc:
            self.matching_delete_status.set(f"Impossible de charger l'historique : {exc}")
            return
        for row in rows:
            execution_id, institution, _institution_id, regime, quarter, year, count, validated, mass, impact, _last_validation = row
            item = self.matching_history_tree.insert(
                "", "end",
                values=(
                    institution, regime, f"{quarter} {year}", int(count or 0), int(validated or 0),
                    f"{float(mass or 0):,.2f}".replace(",", " "),
                    f"{float(impact or 0):,.2f}".replace(",", " "), execution_id,
                ),
            )
            self._matching_history_ids[item] = execution_id
        self.matching_delete_status.set(f"{len(rows)} rapprochement(s) disponible(s).")

    def _delete_selected_matching(self):
        if getattr(self, "busy", False):
            messagebox.showwarning("Traitement en cours", "Attendez la fin du traitement actuel avant de lancer une suppression.")
            return
        selected = self.matching_history_tree.selection()
        if not selected:
            messagebox.showwarning("Suppression rapprochement", "Sélectionnez d'abord un rapprochement.")
            return
        execution_id = self._matching_history_ids.get(selected[0], "")
        try:
            info = self.matching_deletion.get_run(execution_id)
        except Exception as exc:
            messagebox.showerror("Suppression rapprochement", str(exc))
            self._refresh_matching_history()
            return

        warning = (
            f"Supprimer définitivement ce rapprochement ?\n\n"
            f"Institution : {info['institution']}\n"
            f"Régime : {info['regime']}\n"
            f"Période : {info['quarter']} {info['year']}\n"
            f"Lignes de résultats : {info['rows']}\n"
            f"Lignes déjà validées : {info['validated']}\n"
            f"Impact confirmé : {float(info['confirmed'] or 0):,.2f}\n\n"
            "Les données de paie et du déclaratif ne seront pas supprimées.\n"
            "Cette action est irréversible."
        ).replace(",", " ")
        if not messagebox.askyesno("Confirmer la suppression", warning, icon="warning"):
            return
        if int(info["validated"] or 0) > 0:
            if not messagebox.askyesno(
                "Confirmation renforcée",
                "Ce rapprochement contient des lignes déjà validées.\n\nConfirmez-vous malgré tout la suppression de cet historique de contrôle ?",
                icon="warning",
            ):
                return

        self.matching_delete_button.configure(state="disabled")
        self.matching_delete_status.set("Suppression en cours… sauvegarde de sécurité puis nettoyage du rapprochement.")
        self._open_generation_dialog(
            "Suppression du rapprochement",
            f"Institution : {info['institution']}  •  Régime : {info['regime']}  •  Période : {info['quarter']} {info['year']}\n"
            "Une sauvegarde de sécurité est créée avant la suppression.",
            "Étapes de la suppression",
            True,
        )
        self._progress(10, "Préparation de la sauvegarde de sécurité")

        def task():
            self._progress(25, "Sauvegarde de la base DuckDB")
            backup = backup_database(
                self.config_data.database_path,
                self.config_data.backups_dir,
                "avant_suppression_rapprochement",
            )
            self._progress(60, "Suppression des résultats du rapprochement")
            result = self.matching_deletion.delete_run(execution_id)
            self._progress(90, "Vérification et actualisation de l'historique")
            return {"result": result, "backup": backup}

        self._background(
            task,
            self._matching_deleted_with_loader,
            refresh_data=True,
            operation="Suppression d’un rapprochement",
        )

    def _matching_deleted_with_loader(self, payload):
        result = payload["result"]
        backup = payload["backup"]
        self._refresh_matching_history()
        if hasattr(self, "matching_delete_button"):
            self.matching_delete_button.configure(state="normal")
        self.matching_delete_status.set(f"Suppression terminée : {result['deleted']} ligne(s) supprimée(s).")

        if self.generation_window and self.generation_window.winfo_exists():
            self.generation_title.set("Rapprochement supprimé avec succès")
            self.generation_status.set("100% — Sauvegarde créée et résultats supprimés de DuckDB.")
            self.generation_bar.stop()
            self.generation_bar.configure(mode="determinate")
            self.generation_bar["value"] = 100
            self.generated_files.insert("end", f"✓  {result['deleted']} ligne(s) supprimée(s)")
            self.generated_files.insert("end", f"✓  Sauvegarde : {backup}")
            self.generated_files.see("end")
            self.generation_close.configure(state="normal")

        messagebox.showinfo(
            "Suppression terminée",
            f"{result['deleted']} ligne(s) de rapprochement supprimée(s).\n\nSauvegarde préalable :\n{backup}",
        )
