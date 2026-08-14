from __future__ import annotations

from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .regime_comparison_app import PayrollAppWithFinalRegimeComparison
from .sql_console import SqlConsoleService


class PayrollAppWithSqlConsole(PayrollAppWithFinalRegimeComparison):
    """Application finale avec console SQL DuckDB en lecture seule."""

    def __init__(self, *args, **kwargs):
        self.sql_console_service = None
        self.sql_last_query = ""
        self.sql_history = []
        super().__init__(*args, **kwargs)
        self.sql_console_service = SqlConsoleService(self.db)

    def _build_ui(self):
        super()._build_ui()
        self.sql_console_service = SqlConsoleService(self.db)
        self._add_sql_console_tab()

    def _add_sql_console_tab(self):
        outer, body = self._make_scrollable_tab()
        self.sql_console_page = body
        self._tab_shells["sql_console_page"] = outer
        self.notebook.add(outer, text="  Requêtes SQL  ")
        self._build_sql_console(body)

    def _build_sql_console(self, parent):
        self._page_heading(parent, "Requêtes SQL", "Interrogez les tables DuckDB en lecture seule et exportez les résultats en Excel ou CSV.")

        warning = tk.Label(parent, text="MODE LECTURE SEULE — les instructions de modification de la base sont bloquées.",
                           background="#FFF4E5", foreground="#8A4B08", anchor="w", padx=12, pady=9,
                           font=("DejaVu Sans", 9, "bold"))
        warning.pack(fill="x", pady=(0, 10))

        top = ttk.Frame(parent)
        top.pack(fill="x", pady=(0, 10))
        left = ttk.LabelFrame(top, text="Tables RAW disponibles", style="Section.TLabelframe", padding=10)
        left.pack(side="left", fill="both", expand=False, padx=(0, 8))
        right = ttk.LabelFrame(top, text="Structure de la table sélectionnée", style="Section.TLabelframe", padding=10)
        right.pack(side="left", fill="both", expand=True)

        self.sql_raw_tree = ttk.Treeview(left, columns=("table", "rows"), show="headings", height=8, selectmode="browse")
        self.sql_raw_tree.heading("table", text="Table RAW")
        self.sql_raw_tree.heading("rows", text="Lignes")
        self.sql_raw_tree.column("table", width=220, anchor="w")
        self.sql_raw_tree.column("rows", width=85, anchor="e")
        raw_scroll = ttk.Scrollbar(left, orient="vertical", command=self.sql_raw_tree.yview)
        self.sql_raw_tree.configure(yscrollcommand=raw_scroll.set)
        self.sql_raw_tree.grid(row=0, column=0, sticky="nsew")
        raw_scroll.grid(row=0, column=1, sticky="ns")
        ttk.Button(left, text="Actualiser les tables", style="Secondary.TButton", command=self._refresh_sql_tables).grid(row=1, column=0, sticky="w", pady=(7, 0))
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)
        self.sql_raw_tree.bind("<<TreeviewSelect>>", self._sql_table_selected)
        self.sql_raw_tree.bind("<Double-1>", self._insert_selected_sql_table)

        self.sql_structure_tree = ttk.Treeview(right, columns=("column", "type", "nullable"), show="headings", height=8)
        for col, title, width in [("column", "Colonne", 240), ("type", "Type", 180), ("nullable", "Nullable", 90)]:
            self.sql_structure_tree.heading(col, text=title)
            self.sql_structure_tree.column(col, width=width, anchor="w")
        structure_y = ttk.Scrollbar(right, orient="vertical", command=self.sql_structure_tree.yview)
        self.sql_structure_tree.configure(yscrollcommand=structure_y.set)
        self.sql_structure_tree.grid(row=0, column=0, sticky="nsew")
        structure_y.grid(row=0, column=1, sticky="ns")
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)

        editor = ttk.LabelFrame(parent, text="Éditeur SQL", style="Section.TLabelframe", padding=10)
        editor.pack(fill="x", pady=(0, 10))
        self.sql_editor = tk.Text(editor, height=8, wrap="none", font=("DejaVu Sans Mono", 10), undo=True)
        editor_y = ttk.Scrollbar(editor, orient="vertical", command=self.sql_editor.yview)
        editor_x = ttk.Scrollbar(editor, orient="horizontal", command=self.sql_editor.xview)
        self.sql_editor.configure(yscrollcommand=editor_y.set, xscrollcommand=editor_x.set)
        self.sql_editor.grid(row=0, column=0, sticky="nsew")
        editor_y.grid(row=0, column=1, sticky="ns")
        editor_x.grid(row=1, column=0, sticky="ew")
        editor.rowconfigure(0, weight=1)
        editor.columnconfigure(0, weight=1)

        editor_actions = ttk.Frame(editor)
        editor_actions.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(editor_actions, text="Modèle SELECT", style="Secondary.TButton", command=self._sql_insert_select_template).pack(side="left")
        ttk.Button(editor_actions, text="Effacer", command=lambda: self.sql_editor.delete("1.0", "end")).pack(side="left", padx=6)
        ttk.Label(editor_actions, text="Limite d'affichage").pack(side="left", padx=(18, 4))
        self.sql_display_limit = tk.IntVar(value=1000)
        ttk.Spinbox(editor_actions, from_=10, to=10000, textvariable=self.sql_display_limit, width=8).pack(side="left")
        ttk.Button(editor_actions, text="Exécuter", style="Primary.TButton", command=self._run_sql_query).pack(side="right")

        result_box = ttk.LabelFrame(parent, text="Résultats", style="Section.TLabelframe", padding=10)
        result_box.pack(fill="both", expand=True, pady=(0, 10))
        result_frame = ttk.Frame(result_box)
        result_frame.pack(fill="both", expand=True)
        self.sql_result_tree = ttk.Treeview(result_frame, show="headings", height=12)
        result_y = ttk.Scrollbar(result_frame, orient="vertical", command=self.sql_result_tree.yview)
        result_x = ttk.Scrollbar(result_frame, orient="horizontal", command=self.sql_result_tree.xview)
        self.sql_result_tree.configure(yscrollcommand=result_y.set, xscrollcommand=result_x.set)
        self.sql_result_tree.grid(row=0, column=0, sticky="nsew")
        result_y.grid(row=0, column=1, sticky="ns")
        result_x.grid(row=1, column=0, sticky="ew")
        result_frame.rowconfigure(0, weight=1)
        result_frame.columnconfigure(0, weight=1)

        result_actions = ttk.Frame(result_box)
        result_actions.pack(fill="x", pady=(7, 0))
        self.sql_status = tk.StringVar(value="Sélectionnez une table RAW ou saisissez une requête SQL.")
        ttk.Label(result_actions, textvariable=self.sql_status, style="PageHint.TLabel").pack(side="left")
        ttk.Button(result_actions, text="Exporter CSV", style="Secondary.TButton", command=self._export_sql_csv).pack(side="right")
        ttk.Button(result_actions, text="Exporter Excel", style="Secondary.TButton", command=self._export_sql_excel).pack(side="right", padx=6)

        history_box = ttk.LabelFrame(parent, text="Historique de la session", style="Section.TLabelframe", padding=10)
        history_box.pack(fill="x")
        self.sql_history_tree = ttk.Treeview(history_box, columns=("time", "rows", "duration", "status", "query"), show="headings", height=5)
        for col, title, width in [("time", "Heure", 85), ("rows", "Lignes", 80), ("duration", "Durée", 85),
                                  ("status", "État", 90), ("query", "Requête", 650)]:
            self.sql_history_tree.heading(col, text=title)
            self.sql_history_tree.column(col, width=width, anchor="w", stretch=col == "query")
        self.sql_history_tree.pack(fill="x", expand=True)
        self.sql_history_tree.bind("<Double-1>", self._reload_sql_history)

        self._refresh_sql_tables()

    def _refresh_sql_tables(self):
        self.sql_raw_tree.delete(*self.sql_raw_tree.get_children())
        try:
            rows = self.sql_console_service.list_raw_tables()
        except Exception as exc:
            self.sql_status.set(f"Impossible de lire les tables RAW : {exc}")
            return
        for name, count in rows:
            self.sql_raw_tree.insert("", "end", iid=name, values=(name, f"{count:,}".replace(",", " ")))
        self.sql_status.set(f"{len(rows)} table(s) RAW disponible(s).")

    def _sql_table_selected(self, _event=None):
        selected = self.sql_raw_tree.selection()
        if not selected:
            return
        table = selected[0]
        self.sql_structure_tree.delete(*self.sql_structure_tree.get_children())
        try:
            for row in self.sql_console_service.describe_table(table):
                column = row[0] if len(row) > 0 else ""
                dtype = row[1] if len(row) > 1 else ""
                nullable = row[2] if len(row) > 2 else ""
                self.sql_structure_tree.insert("", "end", values=(column, dtype, nullable))
        except Exception as exc:
            self.sql_status.set(str(exc))

    def _insert_selected_sql_table(self, _event=None):
        selected = self.sql_raw_tree.selection()
        if not selected:
            return
        table = selected[0].replace('"', '""')
        self.sql_editor.insert("insert", f'"{table}"')

    def _sql_insert_select_template(self):
        selected = self.sql_raw_tree.selection()
        if not selected:
            messagebox.showwarning("Requêtes SQL", "Sélectionnez d'abord une table RAW.")
            return
        table = selected[0].replace('"', '""')
        self.sql_editor.delete("1.0", "end")
        self.sql_editor.insert("1.0", f'SELECT *\nFROM "{table}"\nLIMIT 100;')

    def _run_sql_query(self):
        query = self.sql_editor.get("1.0", "end").strip()
        started = datetime.now()
        try:
            result = self.sql_console_service.execute(query, self.sql_display_limit.get())
        except Exception as exc:
            self.sql_status.set(f"Erreur SQL : {exc}")
            self._append_sql_history(started, 0, 0.0, "ERREUR", query)
            messagebox.showwarning("Requête SQL", str(exc))
            return
        self.sql_last_query = result["query"]
        self.sql_result_tree.delete(*self.sql_result_tree.get_children())
        columns = result["columns"]
        self.sql_result_tree["columns"] = columns
        for column in columns:
            self.sql_result_tree.heading(column, text=str(column))
            self.sql_result_tree.column(column, width=150, anchor="w")
        for row in result["rows"]:
            self.sql_result_tree.insert("", "end", values=["" if value is None else value for value in row])
        suffix = " — résultat tronqué à la limite d'affichage" if result["truncated"] else ""
        self.sql_status.set(f"{result['displayed']} ligne(s) affichée(s) en {result['elapsed']:.3f} s{suffix}.")
        self._append_sql_history(started, result["displayed"], result["elapsed"], "OK", result["query"])

    def _append_sql_history(self, started, rows, duration, status, query):
        item = (started.strftime("%H:%M:%S"), rows, duration, status, query)
        self.sql_history.append(item)
        iid = str(len(self.sql_history) - 1)
        self.sql_history_tree.insert("", 0, iid=iid,
                                     values=(item[0], item[1], f"{duration:.3f}s", status, query.replace("\n", " ")[:300]))

    def _reload_sql_history(self, _event=None):
        selected = self.sql_history_tree.selection()
        if not selected:
            return
        index = int(selected[0])
        query = self.sql_history[index][4]
        self.sql_editor.delete("1.0", "end")
        self.sql_editor.insert("1.0", query)

    def _export_sql_excel(self):
        if not self.sql_last_query:
            messagebox.showwarning("Export SQL", "Exécutez d'abord une requête valide.")
            return
        target = filedialog.asksaveasfilename(defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")])
        if not target:
            return
        try:
            path = self.sql_console_service.export_excel(self.sql_last_query, target)
        except Exception as exc:
            messagebox.showerror("Export SQL", str(exc))
            return
        messagebox.showinfo("Export SQL", f"Résultat exporté :\n{path}")

    def _export_sql_csv(self):
        if not self.sql_last_query:
            messagebox.showwarning("Export SQL", "Exécutez d'abord une requête valide.")
            return
        target = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not target:
            return
        try:
            path = self.sql_console_service.export_csv(self.sql_last_query, target)
        except Exception as exc:
            messagebox.showerror("Export SQL", str(exc))
            return
        messagebox.showinfo("Export SQL", f"Résultat exporté :\n{path}")
