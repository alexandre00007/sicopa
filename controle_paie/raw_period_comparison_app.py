from __future__ import annotations

from datetime import datetime
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .raw_period_comparison import RawPeriodComparisonService
from .sql_console_unified_enhanced import PayrollAppUnified


class PayrollAppWithRawPeriodComparison(PayrollAppUnified):
    """Ajoute la comparaison de deux raw_* sur une période donnée."""

    def _build_matching(self):
        super()._build_matching()
        self.raw_period_comparison_service = RawPeriodComparisonService(self.db)
        tab = ttk.Frame(self.matching_tabs, padding=10)
        self.matching_tabs.insert(4, tab, text="  Comparaison RAW par période  ")
        self._build_raw_period_comparison(tab)

    def _build_raw_period_comparison(self, parent):
        body = self._scrollable_dialog_body(parent, padding=10)
        body.columnconfigure(0, weight=1)

        cfg = ttk.LabelFrame(body, text="1. Sources et période", style="Section.TLabelframe", padding=10)
        cfg.grid(row=0,column=0,sticky="ew",pady=(0,8))
        self.rpc_table_a=tk.StringVar(); self.rpc_table_b=tk.StringVar()
        self.rpc_quarter=tk.StringVar(value="T1"); self.rpc_year=tk.StringVar(value=str(datetime.now().year))
        ttk.Label(cfg,text="RAW A").grid(row=0,column=0,sticky="w",padx=4); self.rpc_a=ttk.Combobox(cfg,textvariable=self.rpc_table_a,state="readonly",width=34); self.rpc_a.grid(row=1,column=0,sticky="ew",padx=4)
        ttk.Label(cfg,text="RAW B").grid(row=0,column=1,sticky="w",padx=4); self.rpc_b=ttk.Combobox(cfg,textvariable=self.rpc_table_b,state="readonly",width=34); self.rpc_b.grid(row=1,column=1,sticky="ew",padx=4)
        ttk.Label(cfg,text="Trimestre").grid(row=0,column=2,sticky="w",padx=4); ttk.Combobox(cfg,textvariable=self.rpc_quarter,state="readonly",values=["T1","T2","T3","T4"],width=9).grid(row=1,column=2,sticky="w",padx=4)
        ttk.Label(cfg,text="Année").grid(row=0,column=3,sticky="w",padx=4); ttk.Combobox(cfg,textvariable=self.rpc_year,state="readonly",values=list(range(datetime.now().year+1,2019,-1)),width=10).grid(row=1,column=3,sticky="w",padx=4)
        self.rpc_analyze_btn=ttk.Button(cfg,text="Analyser",style="Primary.TButton",command=self._rpc_analyze); self.rpc_analyze_btn.grid(row=1,column=4,padx=(14,4))
        ttk.Button(cfg,text="Actualiser RAW",style="Secondary.TButton",command=self._rpc_refresh_sources).grid(row=1,column=5,padx=4)
        for c in (0,1): cfg.columnconfigure(c,weight=1)

        info = ttk.LabelFrame(body,text="Principe de rapprochement",style="Section.TLabelframe",padding=8)
        info.grid(row=1,column=0,sticky="ew",pady=4)
        ttk.Label(info,text="Le moteur recherche séparément les agents communs A ↔ B par matricule normalisé et par nom normalisé. Il signale aussi même matricule / nom différent et même nom / matricule différent.",wraplength=1150,justify="left").pack(fill="x")

        synth=ttk.LabelFrame(body,text="2. Synthèse",style="Section.TLabelframe",padding=8); synth.grid(row=2,column=0,sticky="ew",pady=4)
        self.rpc_metrics=tk.StringVar(value="Aucune analyse chargée.")
        ttk.Label(synth,textvariable=self.rpc_metrics,font=("DejaVu Sans",10,"bold"),wraplength=1150,justify="left").pack(fill="x",pady=(0,6))
        self.rpc_summary=ttk.Treeview(synth,columns=("status","agents","ba","bb","na","nb"),show="headings",height=7)
        for col,title,width in [("status","Catégorie",280),("agents","Agents",90),("ba","Brut A",130),("bb","Brut B",130),("na","Net A",130),("nb","Net B",130)]: self.rpc_summary.heading(col,text=title); self.rpc_summary.column(col,width=width,anchor="w")
        self.rpc_summary.pack(fill="x")

        results=ttk.LabelFrame(body,text="3. Résultats détaillés",style="Section.TLabelframe",padding=8); results.grid(row=3,column=0,sticky="nsew",pady=4); body.rowconfigure(3,weight=1)
        actions=ttk.Frame(results); actions.pack(fill="x",pady=(0,6))
        self.rpc_filter=tk.StringVar(value="Tous")
        filters=["Tous","COMMUN_PAR_MATRICULE_ET_NOM","COMMUN_PAR_MATRICULE","COMMUN_PAR_NOM","UNIQUEMENT_A","UNIQUEMENT_B","MEME_MATRICULE_NOM_DIFFERENT","MEME_NOM_MATRICULE_DIFFERENT","DOUBLON_MATRICULE_A","DOUBLON_MATRICULE_B","DOUBLON_NOM_A","DOUBLON_NOM_B"]
        combo=ttk.Combobox(actions,textvariable=self.rpc_filter,state="readonly",values=filters,width=39); combo.pack(side="left"); combo.bind("<<ComboboxSelected>>",lambda _e:self._rpc_refresh_results())
        self.rpc_reanalyze_btn=ttk.Button(actions,text="Réanalyser",style="Secondary.TButton",command=self._rpc_reanalyze); self.rpc_reanalyze_btn.pack(side="right",padx=4)
        ttk.Button(actions,text="Historique",style="Secondary.TButton",command=self._rpc_history).pack(side="right",padx=4)
        ttk.Button(actions,text="Exporter toutes les analyses",style="Primary.TButton",command=self._rpc_export).pack(side="right",padx=4)
        frame=ttk.Frame(results); frame.pack(fill="both",expand=True); frame.columnconfigure(0,weight=1); frame.rowconfigure(0,weight=1)
        cols=("status","ma","mb","na","nb","pa","pb","cm","cn","ra","rb","ia","ib","oa","ob","ba","bb","eb","neta","netb","en","sa","sb","ca","cb","ga","gb","ua","ub","pra","prb","diag")
        self.rpc_tree=ttk.Treeview(frame,columns=cols,show="headings",height=13)
        specs=[("status","Statut",220),("ma","Matricule A",115),("mb","Matricule B",115),("na","Nom A",160),("nb","Nom B",160),("pa","Prénom A",120),("pb","Prénom B",120),("cm","Commun mat.",90),("cn","Commun nom",90),("ra","Régime A",100),("rb","Régime B",100),("ia","Institution A",150),("ib","Institution B",150),("oa","Occ A",65),("ob","Occ B",65),("ba","Brut A",110),("bb","Brut B",110),("eb","Écart brut",110),("neta","Net A",110),("netb","Net B",110),("en","Écart net",110),("sa","Section A",130),("sb","Section B",130),("ca","Catégorie A",120),("cb","Catégorie B",120),("ga","Grade A",110),("gb","Grade B",110),("ua","Unité A",170),("ub","Unité B",170),("pra","Province A",120),("prb","Province B",120),("diag","Diagnostic",360)]
        for col,title,width in specs:self.rpc_tree.heading(col,text=title);self.rpc_tree.column(col,width=width,anchor="w")
        sy=ttk.Scrollbar(frame,orient="vertical",command=self.rpc_tree.yview); sx=ttk.Scrollbar(frame,orient="horizontal",command=self.rpc_tree.xview);self.rpc_tree.configure(yscrollcommand=sy.set,xscrollcommand=sx.set)
        self.rpc_tree.grid(row=0,column=0,sticky="nsew");sy.grid(row=0,column=1,sticky="ns");sx.grid(row=1,column=0,sticky="ew")
        self.rpc_status=tk.StringVar(value="Sélectionnez deux RAW et une période.");ttk.Label(body,textvariable=self.rpc_status,style="PageHint.TLabel").grid(row=4,column=0,sticky="w",pady=(5,0))
        self.rpc_last_id=""; self._rpc_refresh_sources()

    def _rpc_refresh_sources(self):
        try: rows=self.raw_period_comparison_service.list_raw_tables()
        except Exception as exc:self.rpc_status.set(str(exc));return
        names=[r[0] for r in rows];self.rpc_a['values']=names;self.rpc_b['values']=names
        if names and self.rpc_table_a.get() not in names:self.rpc_table_a.set(names[0])
        if len(names)>1 and self.rpc_table_b.get() not in names:self.rpc_table_b.set(names[1])
        elif names and self.rpc_table_b.get() not in names:self.rpc_table_b.set(names[0])
        self.rpc_status.set(f"{len(names)} table(s) RAW disponible(s).")

    def _rpc_open_loader(self,title,detail): self._open_generation_dialog(title,detail,"Étapes du traitement",True)
    def _rpc_finish_loader(self,title,detail):
        if self.generation_window and self.generation_window.winfo_exists():
            self.generation_title.set(title);self.generation_status.set("100% — "+detail);self.generation_bar.stop();self.generation_bar.configure(mode="determinate");self.generation_bar['value']=100;self.generation_close.configure(state="normal")

    def _rpc_analyze(self):
        a=self.rpc_table_a.get().strip();b=self.rpc_table_b.get().strip();q=self.rpc_quarter.get();y=self.rpc_year.get()
        if not a or not b:messagebox.showwarning("Comparaison RAW","Sélectionnez les tables A et B.");return
        self.rpc_analyze_btn.configure(state="disabled");self.rpc_reanalyze_btn.configure(state="disabled")
        self._rpc_open_loader("Comparaison RAW par période",f"{a} ↔ {b} • {q} {y}\nMatching par matricule et par nom, écarts et doublons.")
        self._background(lambda:self.raw_period_comparison_service.analyze(a,b,q,int(y),progress=self._progress),self._rpc_analysis_done,operation="Comparaison RAW par période")

    def _rpc_analysis_done(self,info):
        self.rpc_last_id=info['id'];self.rpc_filter.set("Tous");self._rpc_refresh_summary();self._rpc_refresh_results();self.rpc_analyze_btn.configure(state="normal");self.rpc_reanalyze_btn.configure(state="normal");self._rpc_finish_loader("Comparaison terminée","résultats A ↔ B recalculés")

    def _rpc_refresh_summary(self):
        if not self.rpc_last_id:return
        base,m=self.raw_period_comparison_service.summary(self.rpc_last_id);self.rpc_summary.delete(*self.rpc_summary.get_children())
        for r in base:self.rpc_summary.insert("","end",values=(r[0],r[1],f"{float(r[2] or 0):,.2f}".replace(","," "),f"{float(r[3] or 0):,.2f}".replace(","," "),f"{float(r[4] or 0):,.2f}".replace(","," "),f"{float(r[5] or 0):,.2f}".replace(","," ")))
        self.rpc_metrics.set(f"Communs par matricule : {int(m[0] or 0)}   •   Communs par nom : {int(m[1] or 0)}   •   Matricule + nom : {int(m[2] or 0)}   •   Même matricule / nom différent : {int(m[3] or 0)}   •   Même nom / matricule différent : {int(m[4] or 0)}")

    def _rpc_refresh_results(self):
        if not self.rpc_last_id:return
        status="" if self.rpc_filter.get()=="Tous" else self.rpc_filter.get();rows=self.raw_period_comparison_service.list_results(self.rpc_last_id,status);self.rpc_tree.delete(*self.rpc_tree.get_children())
        for row in rows:
            vals=list(row)
            for i in (15,16,17,18,19,20):vals[i]=f"{float(vals[i] or 0):,.2f}".replace(","," ")
            self.rpc_tree.insert("","end",values=vals)
        self.rpc_status.set(f"{len(rows)} résultat(s) affiché(s) — filtre {self.rpc_filter.get()}.")

    def _rpc_reanalyze(self):
        if not self.rpc_last_id:messagebox.showwarning("Réanalyse","Aucune comparaison chargée.");return
        info=self.raw_period_comparison_service.get_comparison(self.rpc_last_id)
        if not messagebox.askyesno("Réanalyser",f"Recalculer {info['table_a']} ↔ {info['table_b']} pour {info['quarter']} {info['year']} ?"):return
        self.rpc_reanalyze_btn.configure(state="disabled");self.rpc_analyze_btn.configure(state="disabled");self._rpc_open_loader("Réanalyse RAW",f"{info['table_a']} ↔ {info['table_b']} • {info['quarter']} {info['year']}")
        self._background(lambda:self.raw_period_comparison_service.reanalyze(self.rpc_last_id,progress=self._progress),self._rpc_analysis_done,operation="Réanalyse comparaison RAW")

    def _rpc_export(self):
        if not self.rpc_last_id:messagebox.showwarning("Export","Aucune comparaison chargée.");return
        folder=filedialog.askdirectory(title="Choisir le dossier parent de l'export RAW");
        if not folder:return
        self._rpc_open_loader("Export comparaison RAW","Création des analyses et annexes RAW complètes A/B.")
        self._background(lambda:self.raw_period_comparison_service.export_all(self.rpc_last_id,folder,progress=self._progress),self._rpc_export_done,operation="Export comparaison RAW")

    def _rpc_export_done(self,path):self._rpc_finish_loader("Export terminé","annexes et analyses générées");messagebox.showinfo("Export terminé",f"Dossier créé :\n{path}")

    def _rpc_history(self):
        rows=self.raw_period_comparison_service.list_history();win=tk.Toplevel(self);win.title("Historique des comparaisons RAW");frame=ttk.Frame(win,padding=12);frame.pack(fill="both",expand=True)
        tree=ttk.Treeview(frame,columns=("a","b","period","status","date"),show="headings",height=14)
        for c,t,w in [("a","RAW A",240),("b","RAW B",240),("period","Période",90),("status","État",90),("date","Créée le",170)]:tree.heading(c,text=t);tree.column(c,width=w,anchor="w")
        ids={}
        for cid,a,b,q,y,s,d,_e in rows:ids[tree.insert("","end",values=(a,b,f"{q} {y}",s,d))]=cid
        tree.pack(fill="both",expand=True);actions=ttk.Frame(frame);actions.pack(fill="x",pady=(8,0))
        def selected():
            s=tree.selection();return ids.get(s[0],"") if s else ""
        def reopen():
            cid=selected();
            if not cid:return
            self.rpc_last_id=cid;self.rpc_filter.set("Tous");self._rpc_refresh_summary();self._rpc_refresh_results();win.destroy()
        def reanalyze():
            cid=selected();
            if not cid:return
            self.rpc_last_id=cid;win.destroy();self._rpc_reanalyze()
        def delete():
            cid=selected();
            if not cid:return
            if not messagebox.askyesno("Supprimer","Supprimer cette analyse RAW ?"):return
            win.destroy();self._rpc_open_loader("Suppression comparaison RAW","Nettoyage de l'historique et des résultats.")
            self._background(lambda:(self._progress(30,"Suppression des résultats"),self.raw_period_comparison_service.delete(cid),self._progress(100,"Suppression terminée"),cid)[-1],lambda _cid:(self._rpc_finish_loader("Suppression terminée","analyse supprimée"),messagebox.showinfo("Suppression","Analyse supprimée.")),operation="Suppression comparaison RAW")
        ttk.Button(actions,text="Rouvrir",style="Primary.TButton",command=reopen).pack(side="right");ttk.Button(actions,text="Réanalyser",style="Secondary.TButton",command=reanalyze).pack(side="right",padx=6);ttk.Button(actions,text="Supprimer",style="Secondary.TButton",command=delete).pack(side="right",padx=6);ttk.Button(actions,text="Fermer",command=win.destroy).pack(side="right",padx=6)
        win.after_idle(lambda:self._center_child_window(win,950,540))
