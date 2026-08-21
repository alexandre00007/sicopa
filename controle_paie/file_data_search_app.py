from __future__ import annotations

import json
import logging
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .file_data_search import SUPPORTED_EXTENSIONS, export_hits_xlsx, inspect_files, search_files
from .user_manual_app import PayrollAppWithUserManual


class PayrollAppWithFileDataSearch(PayrollAppWithUserManual):
    """Ajoute Outils fichiers > Recherche multi-fichiers."""

    def __init__(self, *args, **kwargs):
        self.file_search_paths = []
        self.file_search_structures = {}
        self.file_search_hits = []
        super().__init__(*args, **kwargs)
        self._install_file_search_menu_entry()

    def _install_file_search_menu_entry(self):
        try:
            menubar = self.nametowidget(self.cget("menu"))
            end = menubar.index("end")
            if end is None:
                return
            for index in range(end + 1):
                if str(menubar.type(index)) != "cascade":
                    continue
                if str(menubar.entrycget(index, "label")) != "Outils fichiers":
                    continue
                tools = self.nametowidget(menubar.entrycget(index, "menu"))
                labels = []
                tools_end = tools.index("end")
                if tools_end is not None:
                    for item in range(tools_end + 1):
                        try:
                            labels.append(str(tools.entrycget(item, "label")))
                        except tk.TclError:
                            pass
                if "Recherche multi-fichiers…" not in labels:
                    tools.add_separator()
                    tools.add_command(label="Recherche multi-fichiers…", command=self._show_file_data_search)
                return
        except tk.TclError:
            logging.exception("Impossible d'ajouter Recherche multi-fichiers dans le menu")

    def _show_file_data_search(self):
        window = tk.Toplevel(self)
        window.title("Recherche multi-fichiers — Excel, Access, Parquet")
        window.transient(self)
        self._file_search_window = window

        header = tk.Frame(window, background="#12355B", padx=18, pady=14)
        header.pack(fill="x")
        tk.Label(header, text="Recherche multi-fichiers", background="#12355B", foreground="white",
                 font=("DejaVu Sans", 16, "bold")).pack(anchor="w")
        tk.Label(header, text="Cherchez une ou plusieurs valeurs dans Excel, Access ou Parquet et récupérez les lignes complètes.",
                 background="#12355B", foreground="#CFE2F3").pack(anchor="w", pady=(4, 0))

        root = ttk.Frame(window, padding=12)
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)
        root.columnconfigure(1, weight=2)
        root.rowconfigure(1, weight=1)

        actions = ttk.Frame(root)
        actions.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        ttk.Button(actions, text="Ajouter des fichiers", style="Primary.TButton", command=self._file_search_choose).pack(side="left")
        ttk.Button(actions, text="Vider", command=self._file_search_clear).pack(side="left", padx=6)
        ttk.Button(actions, text="Analyser la structure", command=self._file_search_inspect).pack(side="left", padx=6)
        self._file_search_status = tk.StringVar(value="Sélectionnez des fichiers .xlsx/.xls/.xlsm, .mdb/.accdb ou .parquet")
        ttk.Label(actions, textvariable=self._file_search_status, style="PageHint.TLabel").pack(side="left", padx=12)

        left = ttk.LabelFrame(root, text="Sources et structure", padding=8)
        left.grid(row=1, column=0, sticky="nsew", padx=(0, 8))
        left.rowconfigure(0, weight=1); left.columnconfigure(0, weight=1)
        self._file_search_structure_tree = ttk.Treeview(left, show="tree")
        sy = ttk.Scrollbar(left, orient="vertical", command=self._file_search_structure_tree.yview)
        self._file_search_structure_tree.configure(yscrollcommand=sy.set)
        self._file_search_structure_tree.grid(row=0, column=0, sticky="nsew")
        sy.grid(row=0, column=1, sticky="ns")

        right = ttk.Frame(root)
        right.grid(row=1, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1); right.rowconfigure(3, weight=1)

        criteria = ttk.LabelFrame(right, text="Critères de recherche", padding=10)
        criteria.grid(row=0, column=0, sticky="ew")
        criteria.columnconfigure(1, weight=1)
        ttk.Label(criteria, text="Colonne clé :").grid(row=0, column=0, sticky="w")
        self._file_search_key = tk.StringVar()
        self._file_search_key_combo = ttk.Combobox(criteria, textvariable=self._file_search_key, state="readonly")
        self._file_search_key_combo.grid(row=0, column=1, sticky="ew", padx=6)
        self._file_search_all_columns = tk.BooleanVar(value=False)
        ttk.Checkbutton(criteria, text="Recherche partout (toutes les colonnes)", variable=self._file_search_all_columns,
                        command=self._file_search_toggle_all).grid(row=0, column=2, sticky="w", padx=6)

        ttk.Label(criteria, text="Mode :").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self._file_search_mode = tk.StringVar(value="NORMALIZED")
        ttk.Combobox(criteria, textvariable=self._file_search_mode, state="readonly", width=18,
                     values=("EXACT", "NORMALIZED", "CONTAINS", "STARTS", "ENDS")).grid(row=1, column=1, sticky="w", padx=6, pady=(8, 0))
        ttk.Label(criteria, text="NORMALIZED ignore accents, casse et caractères spéciaux.", style="PageHint.TLabel").grid(row=1, column=2, sticky="w", padx=6, pady=(8, 0))

        values_box = ttk.LabelFrame(right, text="Valeur(s) à rechercher — une par ligne", padding=8)
        values_box.grid(row=1, column=0, sticky="ew", pady=8)
        self._file_search_values = tk.Text(values_box, height=5, wrap="none")
        self._file_search_values.pack(fill="x")

        runbar = ttk.Frame(right)
        runbar.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        self._file_search_run_btn = ttk.Button(runbar, text="Rechercher", style="Primary.TButton", command=self._file_search_run)
        self._file_search_run_btn.pack(side="left")
        ttk.Button(runbar, text="Exporter les résultats", command=self._file_search_export).pack(side="left", padx=6)
        self._file_search_metrics = tk.StringVar(value="0 occurrence")
        ttk.Label(runbar, textvariable=self._file_search_metrics).pack(side="left", padx=12)

        result_frame = ttk.LabelFrame(right, text="Résultats — double-cliquez pour voir toute la ligne", padding=6)
        result_frame.grid(row=3, column=0, sticky="nsew")
        result_frame.rowconfigure(0, weight=1); result_frame.columnconfigure(0, weight=1)
        cols = ("file", "container", "column", "line", "searched", "found")
        self._file_search_result_tree = ttk.Treeview(result_frame, columns=cols, show="headings")
        labels = {"file":"Fichier", "container":"Feuille/Table", "column":"Colonne", "line":"Ligne", "searched":"Recherché", "found":"Trouvé"}
        widths = {"file":180, "container":150, "column":130, "line":70, "searched":120, "found":160}
        for col in cols:
            self._file_search_result_tree.heading(col, text=labels[col])
            self._file_search_result_tree.column(col, width=widths[col], stretch=col in {"file", "found"})
        ry = ttk.Scrollbar(result_frame, orient="vertical", command=self._file_search_result_tree.yview)
        rx = ttk.Scrollbar(result_frame, orient="horizontal", command=self._file_search_result_tree.xview)
        self._file_search_result_tree.configure(yscrollcommand=ry.set, xscrollcommand=rx.set)
        self._file_search_result_tree.grid(row=0, column=0, sticky="nsew")
        ry.grid(row=0, column=1, sticky="ns"); rx.grid(row=1, column=0, sticky="ew")
        self._file_search_result_tree.bind("<Double-1>", self._file_search_show_detail)

        self._center_child_window(window, 1260, 760)

    def _file_search_choose(self):
        paths = filedialog.askopenfilenames(
            parent=self._file_search_window,
            title="Sélectionner les fichiers à analyser",
            filetypes=[
                ("Sources prises en charge", "*.xlsx *.xls *.xlsm *.mdb *.accdb *.parquet"),
                ("Excel", "*.xlsx *.xls *.xlsm"), ("Access", "*.mdb *.accdb"),
                ("Parquet", "*.parquet"), ("Tous les fichiers", "*.*"),
            ],
        )
        for path in paths:
            if Path(path).suffix.lower() in SUPPORTED_EXTENSIONS and path not in self.file_search_paths:
                self.file_search_paths.append(path)
        self._file_search_render_structure(files_only=True)
        self._file_search_status.set(f"{len(self.file_search_paths)} fichier(s) sélectionné(s)")

    def _file_search_clear(self):
        self.file_search_paths = []
        self.file_search_structures = {}
        self.file_search_hits = []
        self._file_search_render_structure(files_only=True)
        self._file_search_key_combo.configure(values=())
        self._file_search_key.set("")
        self._file_search_result_tree.delete(*self._file_search_result_tree.get_children())
        self._file_search_metrics.set("0 occurrence")
        self._file_search_status.set("Sélection vidée")

    def _file_search_render_structure(self, files_only=False):
        tree = self._file_search_structure_tree
        tree.delete(*tree.get_children())
        for path in self.file_search_paths:
            file_node = tree.insert("", "end", text=Path(path).name, open=True)
            if files_only:
                continue
            for container, columns in (self.file_search_structures.get(path) or {}).items():
                cnode = tree.insert(file_node, "end", text=container, open=False)
                for column in columns:
                    tree.insert(cnode, "end", text=str(column))

    def _file_search_inspect(self):
        if not self.file_search_paths:
            messagebox.showwarning("Recherche multi-fichiers", "Ajoutez au moins un fichier.", parent=self._file_search_window)
            return
        self._file_search_status.set("Analyse de la structure en cours…")
        def task():
            return inspect_files(self.file_search_paths, self.config_data.access_driver)
        threading.Thread(target=lambda:self._file_search_inspect_worker(task), daemon=True).start()

    def _file_search_inspect_worker(self, task):
        try:
            structures = task()
            self.after(0, lambda:self._file_search_inspect_done(structures))
        except Exception as exc:
            logging.exception("Inspection multi-fichiers impossible")
            self.after(0, lambda e=exc:messagebox.showerror("Recherche multi-fichiers", str(e), parent=self._file_search_window))

    def _file_search_inspect_done(self, structures):
        self.file_search_structures = structures
        self._file_search_render_structure(files_only=False)
        columns = sorted({c for file_struct in structures.values() for cols in file_struct.values() for c in cols}, key=str.casefold)
        self._file_search_key_combo.configure(values=columns)
        preferred = next((c for c in columns if str(c).casefold() in {"matricule", "matricule_source", "nom", "nom_complet", "id_agent"}), None)
        if preferred:
            self._file_search_key.set(preferred)
        elif columns:
            self._file_search_key.set(columns[0])
        self._file_search_status.set(f"Structure analysée : {len(columns)} colonne(s) distincte(s)")

    def _file_search_toggle_all(self):
        self._file_search_key_combo.configure(state="disabled" if self._file_search_all_columns.get() else "readonly")

    def _file_search_run(self):
        if not self.file_search_structures:
            messagebox.showwarning("Recherche multi-fichiers", "Analysez d'abord la structure des fichiers.", parent=self._file_search_window)
            return
        values = [line.strip() for line in self._file_search_values.get("1.0", "end").splitlines() if line.strip()]
        if not values:
            messagebox.showwarning("Recherche multi-fichiers", "Saisissez au moins une valeur.", parent=self._file_search_window)
            return
        self._file_search_run_btn.configure(state="disabled")
        self._file_search_status.set("Recherche en cours…")
        args = dict(paths=list(self.file_search_paths), structures=self.file_search_structures, searched_values=values,
                    mode=self._file_search_mode.get(), key_column=self._file_search_key.get(),
                    all_columns=self._file_search_all_columns.get(), access_driver=self.config_data.access_driver)
        threading.Thread(target=lambda:self._file_search_worker(args), daemon=True).start()

    def _file_search_worker(self, args):
        try:
            hits = search_files(**args)
            self.after(0, lambda:self._file_search_done(hits))
        except Exception as exc:
            logging.exception("Recherche multi-fichiers impossible")
            self.after(0, lambda e=exc:self._file_search_failed(e))

    def _file_search_failed(self, exc):
        self._file_search_run_btn.configure(state="normal")
        self._file_search_status.set("Recherche interrompue")
        messagebox.showerror("Recherche multi-fichiers", str(exc), parent=self._file_search_window)

    def _file_search_done(self, hits):
        self.file_search_hits = hits
        tree = self._file_search_result_tree
        tree.delete(*tree.get_children())
        for index, hit in enumerate(hits):
            tree.insert("", "end", iid=str(index), values=(Path(hit.file).name, hit.container, hit.column, hit.row_number, hit.searched_value, hit.found_value))
        distinct = len({h.searched_value for h in hits})
        files = len({h.file for h in hits})
        self._file_search_metrics.set(f"{len(hits)} occurrence(s) — {distinct} valeur(s) — {files} fichier(s)")
        self._file_search_status.set("Recherche terminée")
        self._file_search_run_btn.configure(state="normal")

    def _file_search_show_detail(self, _event=None):
        selected = self._file_search_result_tree.selection()
        if not selected:
            return
        hit = self.file_search_hits[int(selected[0])]
        window = tk.Toplevel(self._file_search_window)
        window.title(f"Détail — {Path(hit.file).name} / {hit.container}")
        text = tk.Text(window, wrap="none", font=("DejaVu Sans Mono", 10))
        sy = ttk.Scrollbar(window, orient="vertical", command=text.yview)
        sx = ttk.Scrollbar(window, orient="horizontal", command=text.xview)
        text.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        text.grid(row=0, column=0, sticky="nsew"); sy.grid(row=0, column=1, sticky="ns"); sx.grid(row=1, column=0, sticky="ew")
        window.rowconfigure(0, weight=1); window.columnconfigure(0, weight=1)
        text.insert("end", f"Fichier : {hit.file}\nFeuille/Table : {hit.container}\nLigne : {hit.row_number}\nColonne trouvée : {hit.column}\n\n")
        for key, value in hit.row_data.items():
            text.insert("end", f"{key}: {value}\n")
        text.configure(state="disabled")
        self._center_child_window(window, 900, 650)

    def _file_search_export(self):
        if not self.file_search_hits:
            messagebox.showwarning("Recherche multi-fichiers", "Aucun résultat à exporter.", parent=self._file_search_window)
            return
        target = filedialog.asksaveasfilename(parent=self._file_search_window, title="Exporter les résultats",
                                              defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")],
                                              initialfile="recherche_multi_fichiers.xlsx")
        if not target:
            return
        values = [line.strip() for line in self._file_search_values.get("1.0", "end").splitlines() if line.strip()]
        try:
            path = export_hits_xlsx(self.file_search_hits, values, target)
            self._file_search_status.set(f"Export créé : {path.name}")
            messagebox.showinfo("Recherche multi-fichiers", f"Export créé :\n{path}", parent=self._file_search_window)
        except Exception as exc:
            logging.exception("Export recherche multi-fichiers impossible")
            messagebox.showerror("Recherche multi-fichiers", str(exc), parent=self._file_search_window)
