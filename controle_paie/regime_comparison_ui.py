from __future__ import annotations

from datetime import datetime
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .payroll_deletion import PayrollAppWithPayrollDeletion
from .regime_comparison import RegimeComparisonService


class PayrollAppWithRegimeComparison(PayrollAppWithPayrollDeletion):
    """Ajoute la comparaison directe de deux régimes au module Rapprochement."""

    def _build_matching(self):
        super()._build_matching()
        self.regime_comparison = RegimeComparisonService(self.db)
        compare_tab = ttk.Frame(self.matching_tabs, padding=12)
        self.matching_tabs.insert(2, compare_tab, text="  Comparaison régime vs régime  ")
        self._build_regime_comparison(compare_tab)

    def _build_regime_comparison(self, parent):
        body = self._scrollable_dialog_body(parent, padding=12)
        body.columnconfigure(0, weight=1)

        selection = ttk.LabelFrame(body, text="Périmètres à comparer", style="Section.TLabelframe", padding=10)
        selection.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        for col in range(6):
            selection.columnconfigure(col, weight=1)

        self.compare_institution_a = tk.StringVar()
        self.compare_regime_a = tk.StringVar()
        self.compare_institution_b = tk.StringVar()
        self.compare_regime_b = tk.StringVar()
        self.compare_quarter = tk.StringVar(value="T1")
        self.compare_year = tk.StringVar(value=str(datetime.now().year))
        self.compare_threshold_amount = tk.StringVar(value="0")
        self.compare_threshold_percent = tk.StringVar(value="0")

        ttk.Label(selection, text="Institution A").grid(row=0, column=0, sticky="w", padx=4)
        ttk.Label(selection, text="Régime A").grid(row=0, column=1, sticky="w", padx=4)
        ttk.Label(selection, text="Institution B").grid(row=0, column=2, sticky="w", padx=4)
        ttk.Label(selection, text="Régime B").grid(row=0, column=3, sticky="w", padx=4)
        ttk.Label(selection, text="Trimestre").grid(row=0, column=4, sticky="w", padx=4)
        ttk.Label(selection, text="Année").grid(row=0, column=5, sticky="w", padx=4)

        self.compare_institution_a_combo = ttk.Combobox(selection, textvariable=self.compare_institution_a, state="readonly")
        self.compare_institution_b_combo = ttk.Combobox(selection, textvariable=self.compare_institution_b, state="readonly")
        self._refresh_institution_combo(self.compare_institution_a_combo)
        self._refresh_institution_combo(self.compare_institution_b_combo)
        self.compare_institution_a_combo.grid(row=1, column=0, sticky="ew", padx=4)
        self.compare_institution_b_combo.grid(row=1, column=2, sticky="ew", padx=4)
        ttk.Combobox(selection, textvariable=self.compare_regime_a, state="readonly", values=list(self.config_data.regimes)).grid(row=1, column=1, sticky="ew", padx=4)
        ttk.Combobox(selection, textvariable=self.compare_regime_b, state="readonly", values=list(self.config_data.regimes)).grid(row=1, column=3, sticky="ew", padx=4)
        ttk.Combobox(selection, textvariable=self.compare_quarter, state="readonly", values=["T1", "T2", "T3", "T4"]).grid(row=1, column=4, sticky="ew", padx=4)
        ttk.Combobox(selection, textvariable=self.compare_year, state="readonly", values=list(range(datetime.now().year + 1, 2019, -1))).grid(row=1, column=5, sticky="ew", padx=4)

        thresholds = ttk.Frame(selection)
        thresholds.grid(row=2, column=0, columnspan=6, sticky="ew", pady=(10, 0))
        ttk.Label(thresholds, text="Seuil écart financier").pack(side="left")
        ttk.Entry(thresholds, textvariable=self.compare_threshold_amount, width=14).pack(side="left", padx=(6, 16))
        ttk.Label(thresholds, text="Seuil écart %").pack(side="left")
        ttk.Entry(thresholds, textvariable=self.compare_threshold_percent, width=10).pack(side="left", padx=(6, 16))
        ttk.Label(thresholds, text="0 = signaler tout écart", style="PageHint.TLabel").pack(side="left")
        ttk.Button(thresholds, text="Vérifier les données", style="Secondary.TButton", command=self._preview_regime_comparison).pack(side="right", padx=4)
        ttk.Button(thresholds, text="Historique", style="Secondary.TButton", command=self._show_regime_comparison_history).pack(side="right", padx=4)
        ttk.Button(thresholds, text="Lancer la comparaison", style="Primary.TButton", command=self._run_regime_comparison).pack(side="right", padx=4)

        summary_box = ttk.LabelFrame(body, text="Synthèse de la comparaison", style="Section.TLabelframe", padding=8)
        summary_box.grid(row=1, column=0, sticky="ew", pady=4)
        summary_columns = ("indicator", "value")
        self.compare_summary_tree = ttk.Treeview(summary_box, columns=summary_columns, show="headings", height=7)
        self.compare_summary_tree.heading("indicator", text="Indicateur")
        self.compare_summary_tree.heading("value", text="Valeur")
        self.compare_summary_tree.column("indicator", width=420, anchor="w")
        self.compare_summary_tree.column("value", width=180, anchor="e")
        self.compare_summary_tree.pack(fill="x", expand=True)

        results_box = ttk.LabelFrame(body, text="Résultats détaillés", style="Section.TLabelframe", padding=8)
        results_box.grid(row=2, column=0, sticky="nsew", pady=4)
        body.rowconfigure(2, weight=1)
        filter_row = ttk.Frame(results_box)
        filter_row.pack(fill="x", pady=(0, 6))
        self.compare_result_filter = tk.StringVar(value="Tous")
        filter_values = ["Tous", "Payés dans les deux"] + RegimeComparisonService.STATUSES
        self.compare_filter_combo = ttk.Combobox(filter_row, textvariable=self.compare_result_filter, state="readonly", values=filter_values, width=34)
        self.compare_filter_combo.pack(side="left")
        self.compare_filter_combo.bind("<<ComboboxSelected>>", lambda _e: self._refresh_regime_comparison_results())
        self.compare_export_button = ttk.Button(filter_row, text="Exporter en Excel", state="disabled", style="Secondary.TButton", command=self._export_regime_comparison)
        self.compare_export_button.pack(side="right")

        frame = ttk.Frame(results_box)
        frame.pack(fill="both", expand=True)
        columns = ("status", "key", "matricule", "nom", "occ_a", "occ_b", "gross_a", "gross_b", "gross_diff",
                   "net_a", "net_b", "net_diff", "pct", "grade_a", "grade_b", "cat_a", "cat_b", "aff_a", "aff_b", "diagnostic")
        self.compare_result_tree = ttk.Treeview(frame, columns=columns, show="headings", height=12)
        specs = [
            ("status", "Statut", 190), ("key", "Clé", 90), ("matricule", "Matricule", 120), ("nom", "Nom", 220),
            ("occ_a", "Occ. A", 70), ("occ_b", "Occ. B", 70), ("gross_a", "Brut A", 110), ("gross_b", "Brut B", 110),
            ("gross_diff", "Écart brut", 110), ("net_a", "Net A", 110), ("net_b", "Net B", 110), ("net_diff", "Écart net", 110),
            ("pct", "Écart %", 80), ("grade_a", "Grade A", 130), ("grade_b", "Grade B", 130),
            ("cat_a", "Catégorie A", 120), ("cat_b", "Catégorie B", 120), ("aff_a", "Affectation A", 170),
            ("aff_b", "Affectation B", 170), ("diagnostic", "Diagnostic", 360),
        ]
        for col, title, width in specs:
            self.compare_result_tree.heading(col, text=title)
            self.compare_result_tree.column(col, width=width, anchor="w")
        sy = ttk.Scrollbar(frame, orient="vertical", command=self.compare_result_tree.yview)
        sx = ttk.Scrollbar(frame, orient="horizontal", command=self.compare_result_tree.xview)
        self.compare_result_tree.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        self.compare_result_tree.grid(row=0, column=0, sticky="nsew")
        sy.grid(row=0, column=1, sticky="ns")
        sx.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

        self.compare_status = tk.StringVar(value="Sélectionnez deux régimes et une période.")
        ttk.Label(body, textvariable=self.compare_status, style="PageHint.TLabel", wraplength=1000).grid(row=3, column=0, sticky="w", pady=(6, 0))
        self.compare_last_id = ""

    def _comparison_inputs(self):
        name_a = self.compare_institution_a.get().strip()
        name_b = self.compare_institution_b.get().strip()
        regime_a = self.compare_regime_a.get().strip()
        regime_b = self.compare_regime_b.get().strip()
        quarter = self.compare_quarter.get().strip()
        year = self.compare_year.get().strip()
        if not all([name_a, regime_a, name_b, regime_b, quarter, year]):
            raise ValueError("Sélectionnez les deux institutions, les deux régimes et la période.")
        institution_a = self.institution_ids_by_name.get(name_a)
        institution_b = self.institution_ids_by_name.get(name_b)
        if not institution_a or not institution_b:
            raise ValueError("Une institution sélectionnée n'existe plus dans la configuration.")
        try:
            year = int(year)
            amount = float((self.compare_threshold_amount.get() or "0").replace(" ", "").replace(",", "."))
            percent = float((self.compare_threshold_percent.get() or "0").replace(" ", "").replace(",", "."))
        except ValueError as exc:
            raise ValueError("L'année et les seuils doivent contenir des valeurs numériques valides.") from exc
        return institution_a, regime_a, institution_b, regime_b, quarter, year, amount, percent

    def _preview_regime_comparison(self):
        try:
            institution_a, regime_a, institution_b, regime_b, quarter, year, _amount, _percent = self._comparison_inputs()
            count_a = self.regime_comparison.available_count(institution_a, regime_a, quarter, year)
            count_b = self.regime_comparison.available_count(institution_b, regime_b, quarter, year)
        except ValueError as exc:
            messagebox.showwarning("Comparaison des régimes", str(exc))
            return
        self.compare_status.set(f"Données disponibles : régime A = {count_a:,} ligne(s), régime B = {count_b:,} ligne(s).".replace(",", " "))

    def _run_regime_comparison(self):
        if not self._require_active_trial("la comparaison des régimes"):
            return
        try:
            args = self._comparison_inputs()
        except ValueError as exc:
            messagebox.showwarning("Comparaison des régimes", str(exc))
            return
        self.compare_status.set("Comparaison en cours…")
        self._background(
            lambda: self.regime_comparison.run(*args, progress=self._progress),
            self._regime_comparison_completed,
            operation="Comparaison régime contre régime",
        )

    def _regime_comparison_completed(self, summary):
        self.compare_last_id = summary["id"]
        self._display_regime_comparison_summary(summary)
        self.compare_result_filter.set("Tous")
        self._refresh_regime_comparison_results()
        self.compare_export_button.configure(state="normal")
        self.compare_status.set(
            f"Comparaison terminée : {summary['common']} agent(s) payés dans les deux régimes, "
            f"{summary['only_a']} uniquement A, {summary['only_b']} uniquement B."
        )

    def _display_regime_comparison_summary(self, summary):
        self.compare_summary_tree.delete(*self.compare_summary_tree.get_children())
        rows = [
            ("Lignes de paie régime A", summary["rows_a"]),
            ("Lignes de paie régime B", summary["rows_b"]),
            ("Agents payés dans les deux régimes", summary["common"]),
            ("Uniquement régime A", summary["only_a"]),
            ("Uniquement régime B", summary["only_b"]),
            ("Écarts financiers", summary["financial"]),
            ("Écarts administratifs", summary["administrative"]),
            ("Masse A / Masse B / Écart", f"{float(summary['mass_a'] or 0):,.2f} / {float(summary['mass_b'] or 0):,.2f} / {float((summary['mass_a'] or 0)-(summary['mass_b'] or 0)):,.2f}".replace(",", " ")),
        ]
        for row in rows:
            self.compare_summary_tree.insert("", "end", values=row)

    def _refresh_regime_comparison_results(self):
        if not self.compare_last_id:
            return
        selected = self.compare_result_filter.get()
        status = "" if selected == "Tous" else "DOUBLE_PAIEMENT" if selected == "Payés dans les deux" else selected
        rows = self.regime_comparison.list_results(self.compare_last_id, status)
        self.compare_result_tree.delete(*self.compare_result_tree.get_children())
        for row in rows:
            values = list(row)
            for index in [6, 7, 8, 9, 10, 11]:
                values[index] = f"{float(values[index] or 0):,.2f}".replace(",", " ")
            values[12] = f"{float(values[12] or 0):.2f}%"
            self.compare_result_tree.insert("", "end", values=values)
        self.compare_status.set(f"{len(rows)} résultat(s) affiché(s) pour le filtre « {selected} ».")

    def _show_regime_comparison_history(self):
        rows = self.regime_comparison.list_history()
        window = tk.Toplevel(self)
        window.title("Historique des comparaisons de régimes")
        frame = ttk.Frame(window, padding=12)
        frame.pack(fill="both", expand=True)
        columns = ("a", "b", "period", "status", "common", "only_a", "only_b", "financial", "date")
        tree = ttk.Treeview(frame, columns=columns, show="headings", height=14)
        for col, title, width in [
            ("a", "Régime A", 260), ("b", "Régime B", 260), ("period", "Période", 90), ("status", "État", 90),
            ("common", "Communs", 80), ("only_a", "Seulement A", 90), ("only_b", "Seulement B", 90),
            ("financial", "Écarts fin.", 90), ("date", "Créée le", 150),
        ]:
            tree.heading(col, text=title); tree.column(col, width=width, anchor="w")
        tree.pack(fill="both", expand=True)
        ids = {}
        for row in rows:
            comparison_id, inst_a, reg_a, inst_b, reg_b, quarter, year, status, common, only_a, only_b, financial, created = row
            item = tree.insert("", "end", values=(f"{inst_a} — {reg_a}", f"{inst_b} — {reg_b}", f"{quarter} {year}", status, common, only_a, only_b, financial, created))
            ids[item] = comparison_id
        actions = ttk.Frame(frame); actions.pack(fill="x", pady=(8, 0))
        def reopen():
            selected = tree.selection()
            if not selected: return
            self.compare_last_id = ids[selected[0]]
            summary = self.regime_comparison.get_summary(self.compare_last_id)
            self._display_regime_comparison_summary(summary)
            self.compare_result_filter.set("Tous")
            self._refresh_regime_comparison_results()
            self.compare_export_button.configure(state="normal")
            window.destroy()
        ttk.Button(actions, text="Rouvrir la comparaison", style="Primary.TButton", command=reopen).pack(side="right")
        ttk.Button(actions, text="Fermer", style="Secondary.TButton", command=window.destroy).pack(side="right", padx=6)
        window.after_idle(lambda: self._center_child_window(window, 1180, 620))

    def _export_regime_comparison(self):
        if not self.compare_last_id:
            messagebox.showwarning("Export", "Lancez ou rouvrez d'abord une comparaison.")
            return
        target = filedialog.asksaveasfilename(
            title="Exporter la comparaison des régimes",
            defaultextension=".xlsx",
            filetypes=[("Classeur Excel", "*.xlsx")],
            initialfile="comparaison_regimes.xlsx",
        )
        if not target:
            return
        self._background(
            lambda: self.regime_comparison.export(self.compare_last_id, target),
            lambda path: messagebox.showinfo("Export terminé", f"Comparaison exportée :\n{path}"),
            operation="Export de la comparaison des régimes",
        )
