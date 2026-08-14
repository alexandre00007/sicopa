from __future__ import annotations

import re
import tkinter as tk
from tkinter import messagebox, ttk

from .sql_console_unified_base import PayrollAppWithUnifiedSqlConsole
from .sql_syntax_highlighter import SqlSyntaxHighlighter
from .sql_templates import SqlTemplateLibrary


class PayrollAppUnified(PayrollAppWithUnifiedSqlConsole):
    """Application consolidée : console SQL enrichie au-dessus de toutes les fonctionnalités récentes."""

    SQL_WORDS = sorted(SqlSyntaxHighlighter.KEYWORDS | SqlSyntaxHighlighter.FUNCTIONS)

    def _build_sql_console(self, parent):
        super()._build_sql_console(parent)
        self._install_sql_syntax_highlighting()
        self._install_sql_template_controls(parent)
        self._install_line_numbers()
        self._install_autocomplete()
        self._install_fictifs_assistant(parent)

    def _install_sql_syntax_highlighting(self):
        SqlSyntaxHighlighter.configure(self.sql_editor)
        self._sql_highlight_after = None
        def schedule(_event=None):
            if self._sql_highlight_after is not None:
                try: self.after_cancel(self._sql_highlight_after)
                except Exception: pass
            self._sql_highlight_after = self.after(120, self._highlight_sql_editor)
        self.sql_editor.bind("<KeyRelease>", schedule, add="+")
        self.sql_editor.bind("<<Paste>>", schedule, add="+")
        self.sql_editor.bind("<<Undo>>", schedule, add="+")
        self.sql_editor.bind("<<Redo>>", schedule, add="+")
        self._highlight_sql_editor()

    def _highlight_sql_editor(self):
        self._sql_highlight_after = None
        try: SqlSyntaxHighlighter.highlight(self.sql_editor)
        except tk.TclError: pass

    def _install_sql_template_controls(self, parent):
        editor = next((c for c in parent.winfo_children() if isinstance(c, ttk.LabelFrame) and str(c.cget("text")) == "Éditeur SQL"), None)
        if editor is None: return
        panel = ttk.LabelFrame(editor, text="Modèles SQL prêts à l'emploi", style="Section.TLabelframe", padding=8)
        panel.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(9, 0))
        panel.columnconfigure(1, weight=3); panel.columnconfigure(3, weight=2)
        self.sql_template_name = tk.StringVar(value=SqlTemplateLibrary.names()[0])
        self.sql_template_table_b = tk.StringVar()
        ttk.Label(panel, text="Opération").grid(row=0, column=0, sticky="w", padx=4)
        ttk.Combobox(panel, textvariable=self.sql_template_name, state="readonly", values=SqlTemplateLibrary.names(), width=52).grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Label(panel, text="Table B (JOIN / comparaison)").grid(row=0, column=2, sticky="w", padx=(12,4))
        self.sql_template_table_b_combo = ttk.Combobox(panel, textvariable=self.sql_template_table_b, state="readonly", width=28)
        self.sql_template_table_b_combo.grid(row=0, column=3, sticky="ew", padx=4)
        actions = ttk.Frame(panel); actions.grid(row=1, column=0, columnspan=4, sticky="ew", padx=4, pady=(8,0))
        ttk.Label(actions, text="Table A = table RAW sélectionnée. Adaptez les noms de colonnes génériques au schéma réel.", style="PageHint.TLabel").pack(side="left")
        ttk.Button(actions, text="Ajouter à la requête", style="Secondary.TButton", command=lambda:self._insert_sql_template(False)).pack(side="right", padx=(6,0))
        ttk.Button(actions, text="Remplacer par le modèle", style="Primary.TButton", command=lambda:self._insert_sql_template(True)).pack(side="right")
        self._refresh_sql_template_tables()

    def _refresh_sql_tables(self):
        super()._refresh_sql_tables()
        if hasattr(self, "sql_template_table_b_combo"): self._refresh_sql_template_tables()
        if hasattr(self, "fictif_ref_combo"): self._refresh_fictif_tables()

    def _refresh_sql_template_tables(self):
        tables = [self.sql_raw_tree.item(i, "values")[0] for i in self.sql_raw_tree.get_children()]
        self.sql_template_table_b_combo["values"] = tables
        if tables and self.sql_template_table_b.get() not in tables: self.sql_template_table_b.set(tables[0])

    def _selected_sql_table_name(self):
        selected = self.sql_raw_tree.selection()
        if not selected: raise ValueError("Sélectionnez d'abord la table RAW principale (table A).")
        return selected[0]

    def _insert_sql_template(self, replace=True):
        try:
            sql = SqlTemplateLibrary.render(self.sql_template_name.get(), self._selected_sql_table_name(), self.sql_template_table_b.get().strip() or None)
        except ValueError as exc:
            messagebox.showwarning("Modèles SQL", str(exc)); return
        if replace:
            self.sql_editor.delete("1.0", "end"); self.sql_editor.insert("1.0", sql)
        else:
            current = self.sql_editor.get("1.0", "end").strip()
            self.sql_editor.insert("end" if current else "1.0", ("\n\n" if current else "") + sql)
        self._highlight_sql_editor(); self._refresh_line_numbers(); self.sql_editor.focus_set()
        self.sql_status.set(f"Modèle chargé : {self.sql_template_name.get()}.")

    def _install_line_numbers(self):
        editor = self.sql_editor.master
        for child in editor.grid_slaves(row=0, column=0): child.grid_forget()
        for child in editor.grid_slaves(row=0, column=1): child.grid_forget()
        self.sql_line_numbers = tk.Text(editor, width=2, padx=2, takefocus=0, borderwidth=0, highlightthickness=0,
            background="#F3F4F6", foreground="#6B7280", cursor="arrow", font=("DejaVu Sans Mono",9), state="disabled", wrap="none")
        self.sql_line_numbers.grid(row=0, column=0, sticky="ns", padx=(0,3))
        self.sql_editor.grid(row=0, column=1, sticky="nsew")
        editor.columnconfigure(0, weight=0, minsize=0); editor.columnconfigure(1, weight=1)
        ybar = ttk.Scrollbar(editor, orient="vertical", command=self._sql_yview); ybar.grid(row=0,column=2,sticky="ns")
        self.sql_editor.configure(yscrollcommand=lambda a,b:(ybar.set(a,b), self._refresh_line_numbers()))
        self.sql_editor.bind("<KeyRelease>", lambda _e:self._refresh_line_numbers(), add="+")
        self.sql_editor.bind("<Configure>", lambda _e:self._refresh_line_numbers(), add="+")
        self._refresh_line_numbers()

    def _sql_yview(self, *args):
        self.sql_editor.yview(*args); self.sql_line_numbers.yview_moveto(self.sql_editor.yview()[0])

    def _refresh_line_numbers(self):
        if not hasattr(self, "sql_line_numbers"): return
        count = max(1, int(self.sql_editor.index("end-1c").split(".")[0])); digits=max(2,len(str(count)))
        if int(self.sql_line_numbers.cget("width")) != digits: self.sql_line_numbers.configure(width=digits)
        text="\n".join(f"{i:>{digits}}" for i in range(1,count+1))
        self.sql_line_numbers.configure(state="normal"); self.sql_line_numbers.delete("1.0","end"); self.sql_line_numbers.insert("1.0",text)
        self.sql_line_numbers.tag_add("right","1.0","end"); self.sql_line_numbers.tag_configure("right",justify="right",rmargin=1); self.sql_line_numbers.configure(state="disabled")
        try:self.sql_line_numbers.yview_moveto(self.sql_editor.yview()[0])
        except tk.TclError:pass

    def _install_autocomplete(self):
        self.sql_editor.bind("<Control-space>", self._show_sql_autocomplete, add="+")
        self.sql_editor.bind("<KeyRelease>", self._sql_autocomplete_keyrelease, add="+")
        self.sql_autocomplete_popup=None

    def _autocomplete_candidates(self):
        values=set(self.SQL_WORDS)
        for item in self.sql_raw_tree.get_children():
            vals=self.sql_raw_tree.item(item,"values")
            if vals: values.add(str(vals[0]))
        selected=self.sql_raw_tree.selection()
        if selected:
            try:
                for row in self.sql_console_service.describe_table(selected[0]):
                    if row: values.add(str(row[0]))
            except Exception: pass
        return sorted(values,key=str.upper)

    def _current_sql_prefix(self):
        before=self.sql_editor.get("insert linestart","insert"); m=re.search(r"([A-Za-z_][A-Za-z0-9_]*)$",before)
        return m.group(1) if m else ""

    def _sql_autocomplete_keyrelease(self,event=None):
        if event and event.keysym in {"Up","Down","Return","Escape","Tab"}:return
        prefix=self._current_sql_prefix()
        if len(prefix)>=2:self._show_sql_autocomplete(prefix=prefix)
        else:self._close_sql_autocomplete()

    def _show_sql_autocomplete(self,event=None,prefix=None):
        prefix=self._current_sql_prefix() if prefix is None else prefix
        candidates=[x for x in self._autocomplete_candidates() if x.upper().startswith(prefix.upper()) and x.upper()!=prefix.upper()]
        if not candidates:self._close_sql_autocomplete();return "break" if event else None
        self._close_sql_autocomplete(); popup=tk.Toplevel(self); popup.overrideredirect(True)
        listbox=tk.Listbox(popup,height=min(8,len(candidates)),width=34,font=("DejaVu Sans Mono",10));listbox.pack(fill="both",expand=True)
        for item in candidates[:50]:listbox.insert("end",item)
        bbox=self.sql_editor.bbox("insert") or (0,0,0,0); x=self.sql_editor.winfo_rootx()+bbox[0]; y=self.sql_editor.winfo_rooty()+bbox[1]+bbox[3]+2; popup.geometry(f"+{x}+{y}")
        self.sql_autocomplete_popup=popup
        def accept(_e=None):
            if not listbox.curselection():listbox.selection_set(0)
            choice=listbox.get(listbox.curselection()[0]); start=f"insert-{len(prefix)}c" if prefix else "insert"
            self.sql_editor.delete(start,"insert"); self.sql_editor.insert("insert",choice); self._close_sql_autocomplete(); self._highlight_sql_editor(); return "break"
        listbox.bind("<Return>",accept);listbox.bind("<Double-1>",accept);listbox.bind("<Escape>",lambda _e:(self._close_sql_autocomplete(),"break"));listbox.focus_set();listbox.selection_set(0)
        return "break" if event else None

    def _close_sql_autocomplete(self):
        if self.sql_autocomplete_popup is not None:
            try:self.sql_autocomplete_popup.destroy()
            except tk.TclError:pass
            self.sql_autocomplete_popup=None

    def _install_fictifs_assistant(self,parent):
        box=ttk.LabelFrame(parent,text="Assistant Fictifs — paie vs référentiel",style="Section.TLabelframe",padding=10);box.pack(fill="x",pady=(0,10))
        self.fictif_table_ref=tk.StringVar();self.fictif_key_paie=tk.StringVar(value="matricule");self.fictif_key_ref=tk.StringVar(value="matricule")
        ttk.Label(box,text="Référentiel (table B)").grid(row=0,column=0,sticky="w",padx=4);self.fictif_ref_combo=ttk.Combobox(box,textvariable=self.fictif_table_ref,state="readonly",width=30);self.fictif_ref_combo.grid(row=1,column=0,sticky="ew",padx=4)
        ttk.Label(box,text="Clé paie").grid(row=0,column=1,sticky="w",padx=4);ttk.Entry(box,textvariable=self.fictif_key_paie,width=20).grid(row=1,column=1,sticky="ew",padx=4)
        ttk.Label(box,text="Clé référentiel").grid(row=0,column=2,sticky="w",padx=4);ttk.Entry(box,textvariable=self.fictif_key_ref,width=20).grid(row=1,column=2,sticky="ew",padx=4)
        ttk.Button(box,text="Générer la requête Fictifs",style="Primary.TButton",command=self._generate_fictifs_query).grid(row=1,column=3,padx=8)
        for col in range(3):box.columnconfigure(col,weight=1)
        self._refresh_fictif_tables()

    def _refresh_fictif_tables(self):
        tables=[self.sql_raw_tree.item(i,"values")[0] for i in self.sql_raw_tree.get_children()];self.fictif_ref_combo["values"]=tables
        if tables and self.fictif_table_ref.get() not in tables:self.fictif_table_ref.set(tables[0])

    @staticmethod
    def _safe_identifier(name):
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*",name or ""):raise ValueError("Les clés doivent être des noms de colonnes simples (lettres, chiffres, underscore).")
        return '"'+name.replace('"','""')+'"'

    def _generate_fictifs_query(self):
        selected=self.sql_raw_tree.selection()
        if not selected:messagebox.showwarning("Assistant Fictifs","Sélectionnez la table de paie (table A).");return
        ref=self.fictif_table_ref.get().strip()
        if not ref:messagebox.showwarning("Assistant Fictifs","Sélectionnez une table référentielle.");return
        try:ka=self._safe_identifier(self.fictif_key_paie.get().strip());kb=self._safe_identifier(self.fictif_key_ref.get().strip())
        except ValueError as exc:messagebox.showwarning("Assistant Fictifs",str(exc));return
        a='"'+selected[0].replace('"','""')+'"';b='"'+ref.replace('"','""')+'"'
        sql=(f"SELECT a.*\nFROM {a} a\nWHERE COALESCE(TRIM(CAST(a.{ka} AS VARCHAR)), '') <> ''\n  AND NOT EXISTS (\n      SELECT 1\n      FROM {b} b\n      WHERE TRIM(CAST(b.{kb} AS VARCHAR)) = TRIM(CAST(a.{ka} AS VARCHAR))\n  )\nORDER BY 1\nLIMIT 1000;")
        self.sql_editor.delete("1.0","end");self.sql_editor.insert("1.0",sql);self._highlight_sql_editor();self._refresh_line_numbers();self.sql_status.set("Requête Fictifs générée : agents présents dans la paie mais absents du référentiel.")
