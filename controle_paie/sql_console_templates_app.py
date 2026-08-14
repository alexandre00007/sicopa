from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from .sql_console_app import PayrollAppWithSqlConsole
from .sql_templates import SqlTemplateLibrary


class PayrollAppWithSqlTemplates(PayrollAppWithSqlConsole):
    """Console SQL enrichie d'une bibliothèque de modèles de lecture."""

    def _build_sql_console(self, parent):
        super()._build_sql_console(parent)
        self._install_sql_template_controls(parent)

    def _install_sql_template_controls(self, parent):
        editor = None
        for child in parent.winfo_children():
            if isinstance(child, ttk.LabelFrame) and str(child.cget("text")) == "Éditeur SQL":
                editor = child
                break
        if editor is None:
            return

        panel = ttk.LabelFrame(editor, text="Modèles SQL prêts à l'emploi", style="Section.TLabelframe", padding=8)
        panel.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(9, 0))
        panel.columnconfigure(1, weight=3)
        panel.columnconfigure(3, weight=2)

        self.sql_template_name = tk.StringVar(value=SqlTemplateLibrary.names()[0])
        self.sql_template_table_b = tk.StringVar()

        ttk.Label(panel, text="Opération").grid(row=0, column=0, sticky="w", padx=4)
        template_combo = ttk.Combobox(
            panel,
            textvariable=self.sql_template_name,
            state="readonly",
            values=SqlTemplateLibrary.names(),
            width=52,
        )
        template_combo.grid(row=0, column=1, sticky="ew", padx=4)

        ttk.Label(panel, text="Table B (JOIN / comparaison)").grid(row=0, column=2, sticky="w", padx=(12, 4))
        self.sql_template_table_b_combo = ttk.Combobox(
            panel,
            textvariable=self.sql_template_table_b,
            state="readonly",
            width=28,
        )
        self.sql_template_table_b_combo.grid(row=0, column=3, sticky="ew", padx=4)

        actions = ttk.Frame(panel)
        actions.grid(row=1, column=0, columnspan=4, sticky="ew", padx=4, pady=(8, 0))
        ttk.Label(
            actions,
            text="Table A = table RAW sélectionnée à gauche. Les noms génériques de colonnes sont à adapter au schéma réel.",
            style="PageHint.TLabel",
        ).pack(side="left")
        ttk.Button(
            actions,
            text="Ajouter à la requête",
            style="Secondary.TButton",
            command=lambda: self._insert_sql_template(replace=False),
        ).pack(side="right", padx=(6, 0))
        ttk.Button(
            actions,
            text="Remplacer par le modèle",
            style="Primary.TButton",
            command=lambda: self._insert_sql_template(replace=True),
        ).pack(side="right")

        self._refresh_sql_template_tables()

    def _refresh_sql_tables(self):
        super()._refresh_sql_tables()
        if hasattr(self, "sql_template_table_b_combo"):
            self._refresh_sql_template_tables()

    def _refresh_sql_template_tables(self):
        if not hasattr(self, "sql_template_table_b_combo"):
            return
        tables = [self.sql_raw_tree.item(item, "values")[0] for item in self.sql_raw_tree.get_children()]
        self.sql_template_table_b_combo["values"] = tables
        if tables and self.sql_template_table_b.get() not in tables:
            self.sql_template_table_b.set(tables[0])

    def _selected_sql_table_name(self):
        selected = self.sql_raw_tree.selection()
        if not selected:
            raise ValueError("Sélectionnez d'abord la table RAW principale (table A).")
        return selected[0]

    def _insert_sql_template(self, replace=True):
        try:
            table_a = self._selected_sql_table_name()
            table_b = self.sql_template_table_b.get().strip() or None
            sql = SqlTemplateLibrary.render(self.sql_template_name.get(), table_a, table_b)
        except ValueError as exc:
            messagebox.showwarning("Modèles SQL", str(exc))
            return

        if replace:
            self.sql_editor.delete("1.0", "end")
            self.sql_editor.insert("1.0", sql)
        else:
            current = self.sql_editor.get("1.0", "end").strip()
            if current:
                self.sql_editor.insert("end", "\n\n" + sql)
            else:
                self.sql_editor.insert("1.0", sql)
        self.sql_editor.focus_set()
        self.sql_status.set(f"Modèle chargé : {self.sql_template_name.get()}.")
