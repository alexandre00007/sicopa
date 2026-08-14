from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from .flexible_access_app import PayrollAppWithFlexibleAccess
from .raw_fusion_enhanced import EnhancedRawFusionService


class PayrollAppWithEnhancedRawFusion(PayrollAppWithFlexibleAccess):
    """Ajoute doublons, réanalyse et loaders cohérents au module de fusion RAW."""

    def _build_matching(self):
        super()._build_matching()
        self.raw_fusion_service = EnhancedRawFusionService(self.db)
        self._enhance_raw_fusion_controls()
        self._refresh_raw_fusion_sources()

    def _enhance_raw_fusion_controls(self):
        if not hasattr(self, "raw_fusion_filter"):
            return
        filters = ["Tous","DEUX_REGIMES","TROIS_REGIMES_OU_PLUS","PAIEMENT_MULTIPLE_MEME_REGIME",
                   "PLUSIEURS_INSTITUTIONS","IDENTITE_INCOHERENTE","DOUBLON_MATRICULE","DOUBLON_NOM","UN_SEUL_REGIME"]
        for widget in self.winfo_children():
            self._configure_filter_combo_recursive(widget, filters)
        combo = self._find_filter_combo(self)
        if combo is not None:
            self.raw_reanalyze_button = ttk.Button(
                combo.master,
                text="Réanalyser",
                style="Secondary.TButton",
                command=self._reanalyze_current_raw_fusion,
            )
            self.raw_reanalyze_button.pack(side="right", padx=4)

    def _configure_filter_combo_recursive(self, widget, filters):
        try:
            if isinstance(widget, ttk.Combobox) and str(widget.cget("textvariable")) == str(self.raw_fusion_filter):
                widget["values"] = filters
        except tk.TclError:
            pass
        for child in widget.winfo_children():
            self._configure_filter_combo_recursive(child, filters)

    def _find_filter_combo(self, widget):
        try:
            if isinstance(widget, ttk.Combobox) and str(widget.cget("textvariable")) == str(self.raw_fusion_filter):
                return widget
        except tk.TclError:
            pass
        for child in widget.winfo_children():
            found = self._find_filter_combo(child)
            if found is not None:
                return found
        return None

    def _open_raw_loader(self, title, detail):
        self._open_generation_dialog(title, detail, "Étapes du traitement", True)

    def _finish_raw_loader(self, title, detail):
        if self.generation_window and self.generation_window.winfo_exists():
            self.generation_title.set(title)
            self.generation_status.set("100% — " + detail)
            self.generation_bar.stop()
            self.generation_bar.configure(mode="determinate")
            self.generation_bar["value"] = 100
            self.generation_close.configure(state="normal")

    def _set_reanalysis_busy(self, busy: bool):
        if hasattr(self, "raw_reanalyze_button"):
            self.raw_reanalyze_button.configure(state="disabled" if busy else "normal")
        if hasattr(self, "raw_fusion_status"):
            self.raw_fusion_status.set(
                "Réanalyse en cours… recalcul des catégories, doublons et masses."
                if busy else "Réanalyse terminée."
            )

    def _run_raw_fusion(self):
        tables = self._selected_raw_fusion_tables()
        if len(tables) < 2:
            messagebox.showwarning("Fusion RAW", "Sélectionnez au moins deux tables RAW.")
            return
        quarter = self.raw_fusion_quarter.get()
        year = self.raw_fusion_year.get()
        suffix = self.raw_fusion_suffix.get().strip()
        self._open_raw_loader(
            "Fusion & analyse multi-régimes",
            f"{len(tables)} tables RAW • {quarter} {year}\nFusion, analyse, doublons et matrice s'exécutent en arrière-plan.",
        )
        self._background(
            lambda: self.raw_fusion_service.create_fusion(tables, quarter, int(year), suffix, progress=self._progress),
            self._raw_fusion_completed_with_loader,
            operation="Fusion RAW multi-régimes",
        )

    def _raw_fusion_completed_with_loader(self, info):
        self._raw_fusion_completed(info)
        self._finish_raw_loader("Fusion terminée", f"{info['rows']:,} lignes analysées".replace(",", " "))

    def _reanalyze_current_raw_fusion(self):
        if getattr(self, "busy", False):
            messagebox.showwarning("Traitement en cours", "Attendez la fin du traitement actuel avant de relancer une analyse.")
            return
        if not getattr(self, "raw_fusion_last_id", ""):
            messagebox.showwarning("Réanalyse", "Lancez ou rouvrez d'abord une fusion.")
            return
        info = self.raw_fusion_service.get_fusion(self.raw_fusion_last_id)
        if not messagebox.askyesno(
            "Réanalyser",
            f"Recalculer toutes les analyses de {info['table']} ?\n\n"
            "Les résultats d'analyse existants seront remplacés.\n"
            "La table RAW fusionnée restera intacte.",
        ):
            return

        self._set_reanalysis_busy(True)
        self._open_raw_loader(
            "Réanalyse multi-régimes",
            f"Table : {info['table']}\n"
            "Recalcul des agents, régimes, institutions, masses, identités et doublons.",
        )
        self._progress(5, "Initialisation de la réanalyse")
        self._background(
            lambda: self.raw_fusion_service.reanalyze(self.raw_fusion_last_id, progress=self._progress),
            self._raw_reanalysis_completed,
            operation="Réanalyse fusion multi-régimes",
        )

    def _raw_reanalysis_completed(self, info):
        self._refresh_raw_fusion_summary()
        self._refresh_raw_fusion_results()
        self._set_reanalysis_busy(False)
        self._finish_raw_loader("Réanalyse terminée", "catégories, doublons et masses recalculés")
        messagebox.showinfo(
            "Réanalyse terminée",
            f"La fusion {info['table']} a été réanalysée.\n\n"
            "Les catégories multi-régimes, doublons par matricule/nom, identités, institutions et masses ont été actualisés.",
        )

    def _export_raw_fusion(self):
        if not self.raw_fusion_last_id:
            messagebox.showwarning("Export", "Lancez ou rouvrez d'abord une fusion.")
            return
        from tkinter import filedialog
        folder = filedialog.askdirectory(title="Choisir le dossier parent pour l'export multi-régimes")
        if not folder:
            return
        info = self.raw_fusion_service.get_fusion(self.raw_fusion_last_id)
        self._open_raw_loader(
            "Export des analyses multi-régimes",
            f"Table : {info['table']}\nCréation de la synthèse, des annexes, doublons et matrice.",
        )
        self._background(
            lambda: self.raw_fusion_service.export_all(self.raw_fusion_last_id, folder, progress=self._progress),
            self._raw_export_completed,
            operation="Export fusion multi-régimes",
        )

    def _raw_export_completed(self, path):
        self._finish_raw_loader("Export terminé", "tous les fichiers ont été générés")
        messagebox.showinfo("Export terminé", f"Analyses exportées dans :\n{path}")

    def _show_raw_fusion_history(self):
        rows = self.raw_fusion_service.list_history()
        win = tk.Toplevel(self)
        win.title("Historique des fusions RAW")
        frame = ttk.Frame(win, padding=12)
        frame.pack(fill="both", expand=True)
        cols = ("table","period","status","rows","sources","regimes","date")
        tree = ttk.Treeview(frame, columns=cols, show="headings", height=14)
        for col,title,width in [
            ("table","Table fusionnée",260),("period","Période",90),("status","État",90),
            ("rows","Lignes",100),("sources","Sources",80),("regimes","Régimes",80),("date","Créée le",160),
        ]:
            tree.heading(col,text=title)
            tree.column(col,width=width,anchor="w")
        tree.pack(fill="both",expand=True)
        ids = {}
        for fusion_id,table,q,y,status,count,sources,regimes,created,_export in rows:
            item = tree.insert("","end",values=(table,f"{q} {y}",status,count,sources,regimes,created))
            ids[item]=fusion_id
        actions = ttk.Frame(frame)
        actions.pack(fill="x",pady=(8,0))

        def selected_id():
            sel = tree.selection()
            return ids.get(sel[0], "") if sel else ""

        def reopen():
            fid = selected_id()
            if not fid:
                return
            self.raw_fusion_last_id = fid
            self.raw_fusion_filter.set("Tous")
            self._refresh_raw_fusion_summary()
            self._refresh_raw_fusion_results()
            win.destroy()

        def reanalyze():
            fid = selected_id()
            if not fid:
                return
            if getattr(self, "busy", False):
                messagebox.showwarning("Traitement en cours", "Attendez la fin du traitement actuel.")
                return
            self.raw_fusion_last_id = fid
            info = self.raw_fusion_service.get_fusion(fid)
            if not messagebox.askyesno("Réanalyser", f"Réanalyser {info['table']} ?"):
                return
            win.destroy()
            self._set_reanalysis_busy(True)
            self._open_raw_loader(
                "Réanalyse multi-régimes",
                f"Table : {info['table']}\nRecalcul complet des analyses en cours.",
            )
            self._progress(5, "Initialisation de la réanalyse")
            self._background(
                lambda: self.raw_fusion_service.reanalyze(fid, progress=self._progress),
                self._raw_reanalysis_completed,
                operation="Réanalyse fusion multi-régimes",
            )

        def delete():
            fid = selected_id()
            if not fid:
                return
            info = self.raw_fusion_service.get_fusion(fid)
            if not messagebox.askyesno("Supprimer la fusion", f"Supprimer la table {info['table']} et ses résultats d'analyse ?"):
                return
            win.destroy()
            self._open_raw_loader(
                "Suppression de la fusion",
                f"Table : {info['table']}\nSuppression sécurisée des résultats et de la table fusionnée.",
            )
            self._background(
                lambda: self._delete_raw_fusion_background(fid),
                self._raw_fusion_deleted,
                operation="Suppression fusion multi-régimes",
            )

        ttk.Button(actions,text="Rouvrir",style="Primary.TButton",command=reopen).pack(side="right")
        ttk.Button(actions,text="Réanalyser",style="Secondary.TButton",command=reanalyze).pack(side="right",padx=6)
        ttk.Button(actions,text="Supprimer",style="Secondary.TButton",command=delete).pack(side="right",padx=6)
        ttk.Button(actions,text="Fermer",command=win.destroy).pack(side="right",padx=6)
        win.after_idle(lambda:self._center_child_window(win,1000,560))

    def _delete_raw_fusion_background(self, fid):
        self._progress(20, "Préparation de la suppression")
        self.raw_fusion_service.delete_fusion(fid)
        self._progress(100, "Suppression terminée")
        return fid

    def _raw_fusion_deleted(self, fid):
        if self.raw_fusion_last_id == fid:
            self.raw_fusion_last_id = ""
        self._refresh_raw_fusion_sources()
        self._finish_raw_loader("Suppression terminée", "la fusion et ses résultats ont été supprimés")
        messagebox.showinfo("Suppression", "Fusion supprimée.")
