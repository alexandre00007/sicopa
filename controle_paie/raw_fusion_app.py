from __future__ import annotations

from datetime import datetime
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .raw_fusion import RawFusionMultiRegimeService
from .regime_comparison_folder_export_app import PayrollAppWithRegimeComparisonFolderExport


class PayrollAppWithRawFusion(PayrollAppWithRegimeComparisonFolderExport):
    """Ajoute un sous-onglet de fusion RAW et d'analyse multi-régimes."""

    def _build_matching(self):
        super()._build_matching()
        self.raw_fusion_service = RawFusionMultiRegimeService(self.db)
        tab = ttk.Frame(self.matching_tabs, padding=10)
        self.matching_tabs.insert(3, tab, text="  Fusion & analyse multi-régimes  ")
        self._build_raw_fusion_tab(tab)

    def _build_raw_fusion_tab(self, parent):
        body = self._scrollable_dialog_body(parent, padding=10)
        body.columnconfigure(0, weight=1)

        source_box = ttk.LabelFrame(body, text="1. Tables RAW à fusionner", style="Section.TLabelframe", padding=10)
        source_box.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        source_box.columnconfigure(0, weight=1)
        self.raw_fusion_tree = ttk.Treeview(
            source_box, columns=("table","rows","regime","institution","period","execs"),
            show="headings", height=8, selectmode="extended"
        )
        for col,title,width in [
            ("table","Table RAW",260),("rows","Lignes",90),("regime","Régime",100),
            ("institution","Institution",180),("period","Période",90),("execs","Exécutions",80)
        ]:
            self.raw_fusion_tree.heading(col,text=title); self.raw_fusion_tree.column(col,width=width,anchor="w")
        sy=ttk.Scrollbar(source_box,orient="vertical",command=self.raw_fusion_tree.yview)
        self.raw_fusion_tree.configure(yscrollcommand=sy.set)
        self.raw_fusion_tree.grid(row=0,column=0,sticky="ew"); sy.grid(row=0,column=1,sticky="ns")
        controls=ttk.Frame(source_box); controls.grid(row=1,column=0,columnspan=2,sticky="ew",pady=(8,0))
        ttk.Button(controls,text="Actualiser",style="Secondary.TButton",command=self._refresh_raw_fusion_sources).pack(side="left")
        ttk.Button(controls,text="Vérifier les schémas",style="Secondary.TButton",command=self._preview_raw_fusion_schema).pack(side="left",padx=6)
        ttk.Label(controls,text="Ctrl/Cmd + clic pour sélectionner plusieurs tables.",style="PageHint.TLabel").pack(side="left",padx=8)

        config=ttk.LabelFrame(body,text="2. Paramètres de la fusion",style="Section.TLabelframe",padding=10)
        config.grid(row=1,column=0,sticky="ew",pady=4)
        self.raw_fusion_quarter=tk.StringVar(value="T1")
        self.raw_fusion_year=tk.StringVar(value=str(datetime.now().year))
        self.raw_fusion_suffix=tk.StringVar()
        ttk.Label(config,text="Trimestre").grid(row=0,column=0,sticky="w",padx=4)
        ttk.Combobox(config,textvariable=self.raw_fusion_quarter,state="readonly",values=["T1","T2","T3","T4"],width=10).grid(row=1,column=0,sticky="w",padx=4)
        ttk.Label(config,text="Année").grid(row=0,column=1,sticky="w",padx=4)
        ttk.Combobox(config,textvariable=self.raw_fusion_year,state="readonly",values=list(range(datetime.now().year+1,2019,-1)),width=10).grid(row=1,column=1,sticky="w",padx=4)
        ttk.Label(config,text="Suffixe optionnel").grid(row=0,column=2,sticky="w",padx=4)
        ttk.Entry(config,textvariable=self.raw_fusion_suffix,width=24).grid(row=1,column=2,sticky="w",padx=4)
        ttk.Button(config,text="Fusionner et analyser",style="Primary.TButton",command=self._run_raw_fusion).grid(row=1,column=3,padx=(18,4))
        ttk.Button(config,text="Historique",style="Secondary.TButton",command=self._show_raw_fusion_history).grid(row=1,column=4,padx=4)

        schema_box=ttk.LabelFrame(body,text="Compatibilité des schémas",style="Section.TLabelframe",padding=8)
        schema_box.grid(row=2,column=0,sticky="ew",pady=4)
        self.raw_fusion_schema_text=tk.StringVar(value="Sélectionnez au moins deux tables puis cliquez sur « Vérifier les schémas ».")
        ttk.Label(schema_box,textvariable=self.raw_fusion_schema_text,wraplength=1100,justify="left").pack(fill="x")

        summary_box=ttk.LabelFrame(body,text="3. Synthèse de l'analyse",style="Section.TLabelframe",padding=8)
        summary_box.grid(row=3,column=0,sticky="ew",pady=4)
        self.raw_fusion_summary=ttk.Treeview(summary_box,columns=("status","agents","occ","gross","net"),show="headings",height=7)
        for col,title,width in [("status","Catégorie",260),("agents","Agents",90),("occ","Occurrences",100),("gross","Masse brute",140),("net","Masse nette",140)]:
            self.raw_fusion_summary.heading(col,text=title); self.raw_fusion_summary.column(col,width=width,anchor="w")
        self.raw_fusion_summary.pack(fill="x",expand=True)

        result_box=ttk.LabelFrame(body,text="4. Agents analysés",style="Section.TLabelframe",padding=8)
        result_box.grid(row=4,column=0,sticky="nsew",pady=4); body.rowconfigure(4,weight=1)
        actions=ttk.Frame(result_box); actions.pack(fill="x",pady=(0,6))
        self.raw_fusion_filter=tk.StringVar(value="Tous")
        filters=["Tous","DEUX_REGIMES","TROIS_REGIMES_OU_PLUS","PAIEMENT_MULTIPLE_MEME_REGIME","PLUSIEURS_INSTITUTIONS","IDENTITE_INCOHERENTE","UN_SEUL_REGIME"]
        combo=ttk.Combobox(actions,textvariable=self.raw_fusion_filter,state="readonly",values=filters,width=34)
        combo.pack(side="left"); combo.bind("<<ComboboxSelected>>",lambda _e:self._refresh_raw_fusion_results())
        ttk.Button(actions,text="Voir matrice régimes",style="Secondary.TButton",command=self._show_raw_fusion_matrix).pack(side="right",padx=4)
        ttk.Button(actions,text="Exporter tout dans un dossier",style="Primary.TButton",command=self._export_raw_fusion).pack(side="right",padx=4)

        frame=ttk.Frame(result_box); frame.pack(fill="both",expand=True)
        cols=("status","mat","nom","prenom","regimes","nbreg","nbinst","occ","gross","net","sections","cats","grades","units","provinces","multi","dup","identity","diag")
        self.raw_fusion_results=ttk.Treeview(frame,columns=cols,show="headings",height=12)
        specs=[("status","Statut",190),("mat","Matricule",120),("nom","Nom",180),("prenom","Prénom",130),
               ("regimes","Régimes",180),("nbreg","Nb régimes",85),("nbinst","Nb institutions",105),("occ","Occurrences",90),
               ("gross","Masse brute",120),("net","Masse nette",120),("sections","Sections",160),("cats","Catégories",150),
               ("grades","Grades",140),("units","Unités d'affectation",200),("provinces","Provinces",150),
               ("multi","Multi-régimes",105),("dup","Multi même régime",125),("identity","Identité incoh.",115),("diag","Diagnostic",300)]
        for col,title,width in specs:
            self.raw_fusion_results.heading(col,text=title); self.raw_fusion_results.column(col,width=width,anchor="w")
        sy=ttk.Scrollbar(frame,orient="vertical",command=self.raw_fusion_results.yview); sx=ttk.Scrollbar(frame,orient="horizontal",command=self.raw_fusion_results.xview)
        self.raw_fusion_results.configure(yscrollcommand=sy.set,xscrollcommand=sx.set)
        self.raw_fusion_results.grid(row=0,column=0,sticky="nsew"); sy.grid(row=0,column=1,sticky="ns"); sx.grid(row=1,column=0,sticky="ew")
        frame.rowconfigure(0,weight=1); frame.columnconfigure(0,weight=1)

        self.raw_fusion_status=tk.StringVar(value="Sélectionnez les tables RAW à fusionner.")
        ttk.Label(body,textvariable=self.raw_fusion_status,style="PageHint.TLabel",wraplength=1100).grid(row=5,column=0,sticky="w",pady=(6,0))
        self.raw_fusion_last_id=""
        self._refresh_raw_fusion_sources()

    def _refresh_raw_fusion_sources(self):
        if not hasattr(self,"raw_fusion_tree"): return
        self.raw_fusion_tree.delete(*self.raw_fusion_tree.get_children())
        try: rows=self.raw_fusion_service.list_raw_tables()
        except Exception as exc:
            self.raw_fusion_status.set(f"Erreur de lecture des RAW : {exc}"); return
        for name,count,regime,institution,quarter,year,execs in rows:
            self.raw_fusion_tree.insert("","end",iid=name,values=(name,f"{count:,}".replace(","," "),regime,institution,f"{quarter} {year}".strip(),execs))
        self.raw_fusion_status.set(f"{len(rows)} table(s) RAW disponible(s).")

    def _selected_raw_fusion_tables(self):
        return list(self.raw_fusion_tree.selection())

    def _preview_raw_fusion_schema(self):
        tables=self._selected_raw_fusion_tables()
        if len(tables)<2:
            messagebox.showwarning("Fusion RAW","Sélectionnez au moins deux tables RAW."); return
        try: info=self.raw_fusion_service.preview_schema(tables)
        except Exception as exc:
            messagebox.showerror("Fusion RAW",str(exc)); return
        specifics=sum(len(v) for v in info["specifics"].values())
        self.raw_fusion_schema_text.set(
            f"{len(info['common'])} colonne(s) commune(s), {len(info['all'])} colonne(s) au total, "
            f"{specifics} colonne(s) spécifique(s) selon les sources. Les colonnes absentes seront remplies par NULL grâce à UNION ALL BY NAME."
        )

    def _run_raw_fusion(self):
        tables=self._selected_raw_fusion_tables()
        if len(tables)<2:
            messagebox.showwarning("Fusion RAW","Sélectionnez au moins deux tables RAW."); return
        quarter=self.raw_fusion_quarter.get(); year=self.raw_fusion_year.get(); suffix=self.raw_fusion_suffix.get().strip()
        self.raw_fusion_status.set("Fusion et analyse en cours…")
        self._background(
            lambda:self.raw_fusion_service.create_fusion(tables,quarter,int(year),suffix,progress=self._progress),
            self._raw_fusion_completed,
            operation="Fusion RAW multi-régimes",
        )

    def _raw_fusion_completed(self, info):
        self.raw_fusion_last_id=info["id"]
        self.raw_fusion_filter.set("Tous")
        self._refresh_raw_fusion_summary(); self._refresh_raw_fusion_results(); self._refresh_raw_fusion_sources()
        self.raw_fusion_status.set(f"Fusion terminée : {info['table']} — {info['rows']:,} lignes, {info['regimes']} régime(s).".replace(","," "))

    def _refresh_raw_fusion_summary(self):
        if not self.raw_fusion_last_id:return
        self.raw_fusion_summary.delete(*self.raw_fusion_summary.get_children())
        for status,agents,occ,gross,net in self.raw_fusion_service.summary(self.raw_fusion_last_id):
            self.raw_fusion_summary.insert("","end",values=(status,agents,occ,f"{float(gross or 0):,.2f}".replace(","," "),f"{float(net or 0):,.2f}".replace(","," ")))

    def _refresh_raw_fusion_results(self):
        if not self.raw_fusion_last_id:return
        selected=self.raw_fusion_filter.get(); status="" if selected=="Tous" else selected
        rows=self.raw_fusion_service.list_results(self.raw_fusion_last_id,status)
        self.raw_fusion_results.delete(*self.raw_fusion_results.get_children())
        for row in rows:
            values=list(row); values[8]=f"{float(values[8] or 0):,.2f}".replace(","," "); values[9]=f"{float(values[9] or 0):,.2f}".replace(","," ")
            self.raw_fusion_results.insert("","end",values=values)
        self.raw_fusion_status.set(f"{len(rows)} agent(s) affiché(s) — filtre {selected}.")

    def _show_raw_fusion_matrix(self):
        if not self.raw_fusion_last_id:
            messagebox.showwarning("Matrice","Lancez ou rouvrez d'abord une fusion."); return
        regimes,rows=self.raw_fusion_service.regime_matrix(self.raw_fusion_last_id)
        win=tk.Toplevel(self); win.title("Matrice des agents communs entre régimes")
        frame=ttk.Frame(win,padding=12); frame.pack(fill="both",expand=True)
        cols=["regime"]+[f"c{i}" for i in range(len(regimes))]
        tree=ttk.Treeview(frame,columns=cols,show="headings",height=max(5,len(regimes)))
        tree.heading("regime",text="Régime"); tree.column("regime",width=140,anchor="w")
        for i,r in enumerate(regimes): tree.heading(f"c{i}",text=r); tree.column(f"c{i}",width=100,anchor="e")
        for row in rows: tree.insert("","end",values=row)
        tree.pack(fill="both",expand=True); win.after_idle(lambda:self._center_child_window(win,800,420))

    def _show_raw_fusion_history(self):
        rows=self.raw_fusion_service.list_history()
        win=tk.Toplevel(self); win.title("Historique des fusions RAW")
        frame=ttk.Frame(win,padding=12); frame.pack(fill="both",expand=True)
        cols=("table","period","status","rows","sources","regimes","date")
        tree=ttk.Treeview(frame,columns=cols,show="headings",height=14)
        for col,title,width in [("table","Table fusionnée",260),("period","Période",90),("status","État",90),("rows","Lignes",100),("sources","Sources",80),("regimes","Régimes",80),("date","Créée le",160)]:
            tree.heading(col,text=title); tree.column(col,width=width,anchor="w")
        tree.pack(fill="both",expand=True); ids={}
        for fusion_id,table,q,y,status,count,sources,regimes,created,_export in rows:
            item=tree.insert("","end",values=(table,f"{q} {y}",status,count,sources,regimes,created)); ids[item]=fusion_id
        actions=ttk.Frame(frame); actions.pack(fill="x",pady=(8,0))
        def reopen():
            sel=tree.selection()
            if not sel:return
            self.raw_fusion_last_id=ids[sel[0]]; self.raw_fusion_filter.set("Tous")
            self._refresh_raw_fusion_summary(); self._refresh_raw_fusion_results(); win.destroy()
        def delete():
            sel=tree.selection()
            if not sel:return
            fid=ids[sel[0]]; info=self.raw_fusion_service.get_fusion(fid)
            if not messagebox.askyesno("Supprimer la fusion",f"Supprimer la table {info['table']} et ses résultats d'analyse ?"):return
            try:self.raw_fusion_service.delete_fusion(fid)
            except Exception as exc:messagebox.showerror("Suppression",str(exc));return
            if self.raw_fusion_last_id==fid:self.raw_fusion_last_id=""
            win.destroy(); self._refresh_raw_fusion_sources(); messagebox.showinfo("Suppression","Fusion supprimée.")
        ttk.Button(actions,text="Rouvrir",style="Primary.TButton",command=reopen).pack(side="right")
        ttk.Button(actions,text="Supprimer",style="Secondary.TButton",command=delete).pack(side="right",padx=6)
        ttk.Button(actions,text="Fermer",command=win.destroy).pack(side="right",padx=6)
        win.after_idle(lambda:self._center_child_window(win,1000,560))

    def _export_raw_fusion(self):
        if not self.raw_fusion_last_id:
            messagebox.showwarning("Export","Lancez ou rouvrez d'abord une fusion."); return
        folder=filedialog.askdirectory(title="Choisir le dossier parent pour l'export multi-régimes")
        if not folder:return
        self._background(
            lambda:self.raw_fusion_service.export_all(self.raw_fusion_last_id,folder,progress=self._progress),
            lambda path:messagebox.showinfo("Export terminé",f"Analyses exportées dans :\n{path}"),
            operation="Export fusion multi-régimes",
        )
