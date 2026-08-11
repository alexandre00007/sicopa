from __future__ import annotations

import logging
import os
import platform
import queue
import shutil
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from .config import AppConfig, RegimeConfig
from .database import Database
from .loaders import IngestionService, excel_sheets, list_access_tables, preview_excel
from .matching import MatchingService
from .reports import ReportService
from .explorer import DataExplorerService
from .help_content import USER_GUIDE
from .runtime import APP_NAME, APP_VERSION, CURRENT_SCHEMA_VERSION, DEVELOPER, backup_database, configure_logging, database_schema_version, initialize_runtime, open_path


def validate_scope_values(institution: str, regime: str, quarter: str, year: str):
    """Validate a UI scope and report every missing field in one message."""
    values = {"institution": institution.strip(), "régime": regime.strip(),
              "trimestre": quarter.strip(), "année": year.strip()}
    missing = [label for label, value in values.items() if not value]
    if missing:
        raise ValueError("Complétez les champs suivants : " + ", ".join(missing) + ".")
    try:
        parsed_year = int(values["année"])
    except ValueError as exc:
        raise ValueError("L’année doit être un nombre valide.") from exc
    return values["institution"], values["régime"], values["trimestre"], parsed_year


class PayrollApp(tk.Tk):
    def __init__(self, config: Optional[AppConfig] = None):
        super().__init__()
        supplied_config=config is not None;self.config_data=config or AppConfig();self.runtime_paths=self.config_data.runtime_paths
        if not supplied_config:
            initialize_runtime(self.runtime_paths)
        else:
            for folder in [Path(self.config_data.database_path).parent,Path(self.config_data.results_dir),Path(self.config_data.backups_dir),Path(self.config_data.logs_dir)]:folder.mkdir(parents=True,exist_ok=True)
            configure_logging(Path(self.config_data.logs_dir)/"sicorpa.log")
        current_schema=database_schema_version(Path(self.config_data.database_path))
        pre_migration_backup=backup_database(Path(self.config_data.database_path),Path(self.config_data.backups_dir),"avant_migration") if current_schema<CURRENT_SCHEMA_VERSION else None
        if pre_migration_backup:logging.info("Sauvegarde avant migration du schéma %s vers %s : %s",current_schema,CURRENT_SCHEMA_VERSION,pre_migration_backup)
        self.db = Database(self.config_data.database_path)
        self.db.migrate();logging.info("SICORPA %s démarré avec la base %s",APP_VERSION,self.config_data.database_path)
        self._sync_regimes_from_database()
        self.ingestion = IngestionService(self.db, self.config_data)
        self.matching = MatchingService(self.db)
        self.reports = ReportService(self.db)
        self.explorer = DataExplorerService(self.db)
        self.institution_ids_by_name = {}
        self.events: queue.Queue = queue.Queue()
        self.busy = False
        self.generation_window = None
        self.title(f"{APP_NAME} {APP_VERSION} — Contrôle et rapprochement de la paie")
        self.geometry("1280x820")
        self.minsize(1050, 700)
        self.configure(background="#F3F6FA")
        self.after_idle(self._center_main_window)
        self._build_style()
        self._build_menu()
        self._build_ui()
        self.after(100, self._poll_events)


    def _sync_regimes_from_database(self):
        """Seed built-ins once, then make DuckDB the source of regime configuration."""
        rows = self.db.list_regimes(active_only=False)
        if not rows:
            for code, item in self.config_data.regimes.items():
                self.db.upsert_regime(code, code.replace("_", " ").title(), item.table_pattern, item.raw_table)
            rows = self.db.list_regimes(active_only=False)
        self.config_data.regimes = {
            code: RegimeConfig(code, pattern, raw_table)
            for code, _label, pattern, raw_table, active in rows if active
        }

    def _center_main_window(self):
        self.update_idletasks();width=self.winfo_width() or 1280;height=self.winfo_height() or 820
        x=max(0,(self.winfo_screenwidth()-width)//2);y=max(0,(self.winfo_screenheight()-height)//2)
        self.geometry(f"{width}x{height}+{x}+{y}")

    def _center_child_window(self,window):
        window.update_idletasks();width=window.winfo_width();height=window.winfo_height()
        x=self.winfo_rootx()+max(0,(self.winfo_width()-width)//2);y=self.winfo_rooty()+max(0,(self.winfo_height()-height)//2)
        window.geometry(f"{width}x{height}+{x}+{y}")

    def _build_style(self):
        style = ttk.Style(self)
        if "clam" in style.theme_names(): style.theme_use("clam")
        style.configure("TFrame", background="#F3F6FA")
        style.configure("TLabel", background="#F3F6FA", foreground="#243247", font=("DejaVu Sans", 10))
        style.configure("Title.TLabel", background="#12355B", foreground="white", font=("DejaVu Sans", 21, "bold"))
        style.configure("Subtitle.TLabel", background="#12355B", foreground="#CFE2F3")
        style.configure("PageTitle.TLabel", foreground="#12355B", font=("DejaVu Sans", 18, "bold"))
        style.configure("PageHint.TLabel", foreground="#617187")
        style.configure("Metric.TLabel", background="white", foreground="#12355B", font=("DejaVu Sans", 22, "bold"))
        style.configure("MetricName.TLabel", background="white", foreground="#617187", font=("DejaVu Sans", 9))
        style.configure("Section.TLabelframe", background="white", bordercolor="#D8E1EC", relief="solid")
        style.configure("Section.TLabelframe.Label", background="white", foreground="#12355B", font=("DejaVu Sans", 11, "bold"))
        style.configure("Primary.TButton", background="#1677FF", foreground="white", padding=(16, 10), font=("DejaVu Sans", 10, "bold"))
        style.map("Primary.TButton", background=[("active", "#0B5ED7")])
        style.configure("Secondary.TButton", background="white", foreground="#12355B", padding=(13, 9), font=("DejaVu Sans", 10, "bold"))
        style.configure("TEntry", padding=8); style.configure("TCombobox", padding=7)
        style.configure("TNotebook.Tab", padding=(18, 11), font=("DejaVu Sans", 10, "bold"), background="#E5EBF2")
        style.map("TNotebook.Tab", background=[("selected", "white")], foreground=[("selected", "#12355B")])
        style.configure("Treeview", rowheight=30)
        style.configure("Treeview.Heading", background="#EAF2FB", foreground="#12355B", font=("DejaVu Sans", 9, "bold"))

    def _build_menu(self):
        menu=tk.Menu(self);file_menu=tk.Menu(menu,tearoff=False)
        file_menu.add_command(label="Ouvrir le dossier des résultats",command=lambda:self._open_runtime_path(Path(self.config_data.results_dir)))
        file_menu.add_command(label="Ouvrir le dossier des sauvegardes",command=lambda:self._open_runtime_path(Path(self.config_data.backups_dir)))
        file_menu.add_separator();file_menu.add_command(label="Sauvegarder la base",command=self._manual_backup)
        file_menu.add_separator();file_menu.add_command(label="Quitter",command=self.destroy);menu.add_cascade(label="Fichier",menu=file_menu)
        help_menu=tk.Menu(menu,tearoff=False);help_menu.add_command(label="Mode d’emploi",command=self._show_user_guide);help_menu.add_command(label="Diagnostic",command=self._show_diagnostic);help_menu.add_separator();help_menu.add_command(label="À propos de SICORPA",command=self._show_about);menu.add_cascade(label="Aide",menu=help_menu);self.configure(menu=menu)

    def _open_runtime_path(self,path: Path):
        try:open_path(path)
        except Exception as exc:logging.exception("Ouverture du dossier impossible");messagebox.showerror("Ouverture impossible",str(exc))

    def _manual_backup(self):
        try:target=backup_database(Path(self.config_data.database_path),Path(self.config_data.backups_dir),"manuel")
        except Exception as exc:logging.exception("Sauvegarde impossible");messagebox.showerror("Sauvegarde impossible",str(exc));return
        if target:messagebox.showinfo("Sauvegarde terminée",f"Base sauvegardée dans :\n{target}")
        else:messagebox.showwarning("Sauvegarde","La base n’existe pas encore.")

    def _text_dialog(self,title: str,content: str,geometry: str="820x650"):
        window=tk.Toplevel(self);window.title(title);window.geometry(geometry);window.minsize(620,420);window.transient(self)
        header=tk.Frame(window,background="#12355B",padx=20,pady=14);header.pack(fill="x");tk.Label(header,text=title,background="#12355B",foreground="white",font=("DejaVu Sans",15,"bold")).pack(anchor="w")
        body=ttk.Frame(window,padding=16);body.pack(fill="both",expand=True);scroll=ttk.Scrollbar(body);scroll.pack(side="right",fill="y")
        text=tk.Text(body,wrap="word",yscrollcommand=scroll.set,font=("DejaVu Sans",10),background="white",foreground="#243247",padx=14,pady=14,relief="solid",borderwidth=1);text.pack(side="left",fill="both",expand=True);scroll.configure(command=text.yview);text.insert("1.0",content);text.configure(state="disabled")
        ttk.Button(window,text="Fermer",style="Primary.TButton",command=window.destroy).pack(anchor="e",padx=16,pady=(0,14));window.after_idle(lambda:self._center_child_window(window));return window

    def _show_user_guide(self):self._text_dialog("Mode d’emploi de SICORPA",USER_GUIDE)

    def _show_about(self):
        content=f"""SICORPA {APP_VERSION}
Système Intégré de Contrôle et de Rapprochement de la Paie

Application locale d’importation, de standardisation, de filtrage, de rapprochement et de restitution des contrôles de paie.

Développeur
{DEVELOPER}

Base analytique
{self.config_data.database_path}

Résultats
{self.config_data.results_dir}

Journal
{Path(self.config_data.logs_dir)/'sicorpa.log'}

Moteur analytique : DuckDB
Interface : Python / Tkinter"""
        self._text_dialog("À propos de SICORPA",content,"720x520")

    def _diagnostic_text(self) -> str:
        checks=[]
        def add(label,ok,detail):checks.append(f"{'OK' if ok else 'À VÉRIFIER'} — {label}\n    {detail}")
        database=Path(self.config_data.database_path);add("Dossier de la base",database.parent.exists() and os.access(database.parent,os.W_OK),str(database.parent))
        for label,path in [("Résultats",Path(self.config_data.results_dir)),("Sauvegardes",Path(self.config_data.backups_dir)),("Journaux",Path(self.config_data.logs_dir))]:add(label,path.exists() and os.access(path,os.W_OK),str(path))
        try:
            with self.db.connect() as con:con.execute("SELECT 1").fetchone()
            add("DuckDB",True,str(database))
        except Exception as exc:add("DuckDB",False,str(exc))
        if platform.system()=="Windows":
            try:
                import pyodbc
                drivers=[driver for driver in pyodbc.drivers() if "Access" in driver];add("Lecture Access",bool(drivers),", ".join(drivers) or "Pilote Microsoft Access absent")
            except Exception as exc:add("Lecture Access",False,str(exc))
        else:add("Lecture Access",bool(shutil.which("mdb-tables") and shutil.which("mdb-export")),"mdbtools installé" if shutil.which("mdb-tables") else "Installez mdbtools")
        add("Espace disque",shutil.disk_usage(database.parent).free>500*1024*1024,f"{shutil.disk_usage(database.parent).free/(1024**3):.1f} Go libres")
        return f"DIAGNOSTIC SICORPA {APP_VERSION}\nSystème : {platform.system()} {platform.release()}\n\n"+"\n\n".join(checks)

    def _show_diagnostic(self):self._text_dialog("Diagnostic de SICORPA",self._diagnostic_text(),"760x600")

    def _build_ui(self):
        header = tk.Frame(self, background="#12355B", padx=24, pady=17); header.pack(fill="x")
        identity = tk.Frame(header, background="#12355B"); identity.pack(side="left")
        ttk.Label(identity, text="SICORPA", style="Title.TLabel").pack(anchor="w")
        ttk.Label(identity, text="Système Intégré de Contrôle et de Rapprochement de la Paie", style="Subtitle.TLabel").pack(anchor="w")
        tk.Label(header, text=f"●  DuckDB connecté  •  v{APP_VERSION}\n{self.config_data.database_path}", background="#0D2947", foreground="#D7E9FA", padx=14, pady=8).pack(side="right")
        self.notebook = ttk.Notebook(self); self.notebook.pack(fill="both", expand=True, padx=22, pady=(18,10))
        self.dashboard_page=ttk.Frame(self.notebook,padding=20);self.access_page=ttk.Frame(self.notebook,padding=20);self.excel_page=ttk.Frame(self.notebook,padding=20);self.match_page=ttk.Frame(self.notebook,padding=20);self.explorer_page=ttk.Frame(self.notebook,padding=20);self.admin_page=ttk.Frame(self.notebook,padding=20);self.mapping_page=ttk.Frame(self.notebook,padding=20)
        for page,label in [(self.dashboard_page,"  Tableau de bord  "),(self.access_page,"  1. Paie Access  "),(self.excel_page,"  2. Déclaratif Excel  "),(self.match_page,"  3. Rapprochement  "),(self.explorer_page,"  Explorer les données  "),(self.admin_page,"  Configuration  "),(self.mapping_page,"  Mapping colonnes  ")]:self.notebook.add(page,text=label)
        self._build_dashboard();self._build_access();self._build_excel();self._build_matching();self._build_explorer();self._build_admin();self._build_mapping()
        footer=ttk.Frame(self,padding=(22,7,22,14));footer.pack(fill="x")
        self.progress=ttk.Progressbar(footer,maximum=100);self.progress.pack(side="left",fill="x",expand=True)
        self.status=tk.StringVar(value="Prêt");ttk.Label(footer,textvariable=self.status,width=42).pack(side="left",padx=12)
        self._refresh_dashboard()

    def _page_heading(self,parent,title,description):
        heading=ttk.Frame(parent);heading.pack(fill="x",pady=(0,14))
        ttk.Label(heading,text=title,style="PageTitle.TLabel").pack(anchor="w")
        ttk.Label(heading,text=description,style="PageHint.TLabel").pack(anchor="w",pady=(3,0))

    def _build_dashboard(self):
        self._page_heading(self.dashboard_page,"Tableau de bord","Vue d’ensemble de l’entrepôt analytique et accès rapide au traitement trimestriel.")
        choice=ttk.LabelFrame(self.dashboard_page,text="Quel traitement souhaitez-vous effectuer ?",style="Section.TLabelframe",padding=16);choice.pack(fill="x",pady=(0,16))
        self.treatment_choice=tk.StringVar(value="Traitement complet : paie + déclaratif + rapprochement + rapport")
        options=["Charger uniquement une table de paie Access","Charger uniquement un déclaratif Excel","Lancer un rapprochement existant","Générer uniquement le rapport et les annexes","Traitement complet : paie + déclaratif + rapprochement + rapport"]
        ttk.Combobox(choice,textvariable=self.treatment_choice,state="readonly",values=options,width=70).pack(side="left",fill="x",expand=True,padx=(0,10))
        ttk.Button(choice,text="Commencer",style="Primary.TButton",command=self._start_selected_treatment).pack(side="right")
        dashboard_filters=ttk.LabelFrame(self.dashboard_page,text="Filtres du tableau de bord",style="Section.TLabelframe",padding=12);dashboard_filters.pack(fill="x",pady=(0,14))
        self.dashboard_institution=tk.StringVar(value="Toutes");self.dashboard_regime=tk.StringVar(value="Tous");self.dashboard_quarter=tk.StringVar(value="Tous");self.dashboard_year=tk.StringVar(value="Toutes")
        dashboard_fields=[("Institution",self.dashboard_institution),("Régime",self.dashboard_regime),("Trimestre",self.dashboard_quarter),("Année",self.dashboard_year)]
        for col,(label,var) in enumerate(dashboard_fields):ttk.Label(dashboard_filters,text=label).grid(row=0,column=col,sticky="w",padx=4)
        self.dashboard_institution_combo=ttk.Combobox(dashboard_filters,textvariable=self.dashboard_institution,state="readonly",values=["Toutes"]+[row[2] for row in self.db.list_institutions()]);self.dashboard_institution_combo.grid(row=1,column=0,sticky="ew",padx=4)
        self.dashboard_regime_combo=ttk.Combobox(dashboard_filters,textvariable=self.dashboard_regime,state="readonly",values=["Tous"]+list(self.config_data.regimes));self.dashboard_regime_combo.grid(row=1,column=1,sticky="ew",padx=4)
        ttk.Combobox(dashboard_filters,textvariable=self.dashboard_quarter,state="readonly",values=["Tous","T1","T2","T3","T4"]).grid(row=1,column=2,sticky="ew",padx=4)
        ttk.Combobox(dashboard_filters,textvariable=self.dashboard_year,state="readonly",values=["Toutes"]+list(range(datetime.now().year+1,2019,-1))).grid(row=1,column=3,sticky="ew",padx=4)
        ttk.Button(dashboard_filters,text="Réinitialiser",style="Secondary.TButton",command=self._reset_dashboard_filters).grid(row=1,column=4,padx=5)
        ttk.Button(dashboard_filters,text="Appliquer",style="Primary.TButton",command=self._refresh_dashboard).grid(row=1,column=5,padx=5)
        for combo in [self.dashboard_institution_combo,self.dashboard_regime_combo]:combo.bind("<<ComboboxSelected>>",lambda _e:self._refresh_dashboard())
        for col in range(4):dashboard_filters.columnconfigure(col,weight=1)
        metrics=ttk.Frame(self.dashboard_page);metrics.pack(fill="x",pady=(2,18));self.metric_vars={}
        for col,(key,label) in enumerate([("institutions","INSTITUTIONS"),("imports","IMPORTATIONS"),("paie","LIGNES DE PAIE"),("declarations","DÉCLARATIONS"),("anomalies","ANOMALIES À VALIDER")]):
            card=tk.Frame(metrics,background="white",highlightbackground="#D8E1EC",highlightthickness=1,padx=17,pady=15);card.grid(row=0,column=col,sticky="nsew",padx=5)
            value=tk.StringVar(value="0");self.metric_vars[key]=value
            ttk.Label(card,textvariable=value,style="Metric.TLabel").pack(anchor="w");ttk.Label(card,text=label,style="MetricName.TLabel").pack(anchor="w",pady=(4,0));metrics.columnconfigure(col,weight=1)
        workflow=ttk.LabelFrame(self.dashboard_page,text="Parcours recommandé",style="Section.TLabelframe",padding=18);workflow.pack(fill="both",expand=True)
        for number,title,hint,tab in [("01","Configurer l’institution","Créez l’institution et son périmètre métier.",5),("02","Importer la paie Access","Sélectionnez la table du trimestre.",1),("03","Importer le déclaratif","Contrôlez l’aperçu Excel.",2),("04","Rapprocher et exporter","Classez les écarts et générez les annexes.",3)]:
            item=tk.Frame(workflow,background="white",pady=10);item.pack(fill="x")
            tk.Label(item,text=number,background="#EAF2FB",foreground="#1677FF",font=("DejaVu Sans",11,"bold"),width=4,pady=8).pack(side="left")
            copy=tk.Frame(item,background="white",padx=13);copy.pack(side="left",fill="x",expand=True)
            tk.Label(copy,text=title,background="white",foreground="#12355B",font=("DejaVu Sans",11,"bold")).pack(anchor="w");tk.Label(copy,text=hint,background="white",foreground="#6C7A8D").pack(anchor="w")
            ttk.Button(item,text="Ouvrir",style="Secondary.TButton",command=lambda index=tab:self.notebook.select(index)).pack(side="right")

    def _start_selected_treatment(self):
        choice=self.treatment_choice.get()
        if choice.startswith("Charger uniquement une table"):self.notebook.select(1)
        elif choice.startswith("Charger uniquement un déclaratif"):self.notebook.select(2)
        elif choice.startswith("Lancer un rapprochement"):self.notebook.select(3)
        elif choice.startswith("Générer uniquement"):self.notebook.select(3);messagebox.showinfo("Rapport","Sélectionnez le périmètre puis cliquez sur Générer le rapport final et les annexes.")
        else:self.notebook.select(1);messagebox.showinfo("Traitement complet","Étape 1/4 : chargez la table de paie. Poursuivez ensuite avec les onglets numérotés.")

    def _dashboard_conditions(self):
        conditions=[];params=[]
        institution_name=self.dashboard_institution.get() if hasattr(self,"dashboard_institution") else "Toutes"
        if institution_name not in {"","Toutes"}:
            institution_id=self.institution_ids_by_name.get(institution_name)
            if institution_id:conditions.append("institution_id=?");params.append(institution_id)
        regime=self.dashboard_regime.get() if hasattr(self,"dashboard_regime") else "Tous"
        if regime not in {"","Tous"}:conditions.append("regime=?");params.append(regime)
        quarter=self.dashboard_quarter.get() if hasattr(self,"dashboard_quarter") else "Tous"
        if quarter not in {"","Tous"}:conditions.append("trimestre=?");params.append(quarter)
        year=self.dashboard_year.get() if hasattr(self,"dashboard_year") else "Toutes"
        if year not in {"","Toutes"}:conditions.append("annee=?");params.append(int(year))
        return conditions,params

    def _reset_dashboard_filters(self):
        self.dashboard_institution.set("Toutes");self.dashboard_regime.set("Tous");self.dashboard_quarter.set("Tous");self.dashboard_year.set("Toutes");self._refresh_dashboard()

    def _refresh_dashboard(self):
        if not hasattr(self,"metric_vars"):return
        conditions,params=self._dashboard_conditions();where=(" WHERE "+" AND ".join(conditions)) if conditions else ""
        scoped_institutions="SELECT institution_id,regime,trimestre,annee FROM paie_standardisee UNION ALL SELECT institution_id,regime,trimestre,annee FROM declaratif_standardise"
        queries={
            "institutions":(f"SELECT COUNT(DISTINCT institution_id) FROM ({scoped_institutions}) donnees"+where,params),
            "imports":("SELECT COUNT(*) FROM journal_executions WHERE statut='TERMINE'"+(" AND "+" AND ".join(conditions) if conditions else ""),params),
            "paie":("SELECT COUNT(*) FROM paie_standardisee"+where,params),
            "declarations":("SELECT COUNT(*) FROM declaratif_standardise"+where,params),
            "anomalies":("SELECT COUNT(*) FROM resultats_rapprochement WHERE statut_rapprochement NOT LIKE 'CONFORME%' AND statut_validation='A_VALIDER'"+(" AND "+" AND ".join(conditions) if conditions else ""),params),
        }
        with self.db.connect() as con:
            for key,(query,values) in queries.items():self.metric_vars[key].set(f"{con.execute(query,values).fetchone()[0]:,}".replace(","," "))

    def _common_scope(self, parent):
        frame = ttk.LabelFrame(parent, text="Périmètre", style="Section.TLabelframe", padding=10)
        frame.pack(fill="x", pady=8)
        values = {}
        labels = [("institution", "Institution"), ("regime", "Régime"), ("quarter", "Trimestre"), ("year", "Année")]
        for col, (key, label) in enumerate(labels):
            ttk.Label(frame, text=label).grid(row=0, column=col, sticky="w", padx=5)
            var = tk.StringVar(); values[key] = var
            combo = ttk.Combobox(frame, textvariable=var, state="readonly")
            combo.grid(row=1, column=col, sticky="ew", padx=5)
            if key == "regime":
                combo["values"] = list(self.config_data.regimes)
                values["regime_combo"] = combo
            elif key == "quarter": combo["values"] = ["T1", "T2", "T3", "T4"]
            elif key == "year": combo["values"] = list(range(datetime.now().year + 1, 2019, -1))
            else: values["institution_combo"] = combo
            frame.columnconfigure(col, weight=1)
        self._refresh_institution_combo(values["institution_combo"])
        return values

    def _build_access(self):
        self._page_heading(self.access_page,"Importer une table de paie","Choisissez la base Access, contrôlez le régime détecté puis chargez la table dans DuckDB.")
        self.access_scope = self._common_scope(self.access_page)
        src = ttk.LabelFrame(self.access_page, text="Source Access", style="Section.TLabelframe", padding=10); src.pack(fill="x", pady=8)
        self.access_path = tk.StringVar(); self.access_table = tk.StringVar()
        ttk.Entry(src, textvariable=self.access_path).grid(row=0,column=0,sticky="ew",padx=5)
        ttk.Button(src,text="Parcourir",command=self._choose_access).grid(row=0,column=1,padx=5)
        self.table_combo=ttk.Combobox(src,textvariable=self.access_table,state="readonly"); self.table_combo.grid(row=1,column=0,sticky="ew",padx=5,pady=8)
        self.table_combo.bind("<<ComboboxSelected>>", lambda _event: self._autofill_table(self.access_table.get()))
        ttk.Button(src,text="Lister les tables",command=self._scan_access).grid(row=1,column=1,padx=5)
        src.columnconfigure(0,weight=1)
        self.access_load=ttk.Button(self.access_page,text="Charger la table sélectionnée",style="Primary.TButton",command=self._load_access); self.access_load.pack(anchor="e",pady=12)

    def _build_excel(self):
        self._page_heading(self.excel_page,"Importer un déclaratif Excel","Sélectionnez l’institution, vérifiez la feuille et contrôlez les colonnes avant chargement.")
        self.excel_scope = self._common_scope(self.excel_page)
        src=ttk.LabelFrame(self.excel_page,text="Source Excel",style="Section.TLabelframe",padding=10); src.pack(fill="x",pady=8)
        self.excel_path=tk.StringVar(); self.excel_sheet=tk.StringVar(); self.header_row=tk.IntVar(value=1)
        ttk.Entry(src,textvariable=self.excel_path).grid(row=0,column=0,sticky="ew",padx=5)
        ttk.Button(src,text="Parcourir",command=self._choose_excel).grid(row=0,column=1,padx=5)
        self.sheet_combo=ttk.Combobox(src,textvariable=self.excel_sheet,state="readonly"); self.sheet_combo.grid(row=1,column=0,sticky="ew",padx=5,pady=8)
        ttk.Spinbox(src,from_=1,to=100,textvariable=self.header_row,width=8).grid(row=1,column=1,padx=5)
        ttk.Button(src,text="Afficher l’aperçu",command=self._preview_excel).grid(row=2,column=1,padx=5)
        src.columnconfigure(0,weight=1)
        self.preview=ttk.Treeview(self.excel_page,show="headings",height=10); self.preview.pack(fill="both",expand=True,pady=8)
        self.excel_load=ttk.Button(self.excel_page,text="Charger le déclaratif",style="Primary.TButton",command=self._load_excel); self.excel_load.pack(anchor="e",pady=8)

    def _build_matching(self):
        self._page_heading(self.match_page,"Rapprochement et restitution","Filtrez strictement le listing de l’institution, puis comparez ce périmètre au déclaratif et aux autres institutions.")
        self.match_scope=self._common_scope(self.match_page)
        self.match_scope["institution_combo"].bind("<<ComboboxSelected>>",lambda _e:self._refresh_treatment_filters())
        self.match_scope["regime_combo"].bind("<<ComboboxSelected>>",lambda _e:self._refresh_treatment_filters())
        filtres=ttk.LabelFrame(self.match_page,text="Filtres métier du listing — appliqués avant toute comparaison",style="Section.TLabelframe",padding=12);filtres.pack(fill="both",expand=True,pady=8)
        self.treatment_filter_column=tk.StringVar();self.treatment_filter_operator=tk.StringVar(value="égal à");self.treatment_filter_value=tk.StringVar()
        ttk.Label(filtres,text="Colonne standardisée du listing").grid(row=0,column=0,sticky="w",padx=4)
        ttk.Label(filtres,text="Opérateur").grid(row=0,column=1,sticky="w",padx=4)
        ttk.Label(filtres,text="Contenu recherché").grid(row=0,column=2,sticky="w",padx=4)
        ttk.Combobox(filtres,textvariable=self.treatment_filter_column,state="readonly",values=sorted(self.db.PAYROLL_FILTER_COLUMNS)).grid(row=1,column=0,sticky="ew",padx=4)
        ttk.Combobox(filtres,textvariable=self.treatment_filter_operator,state="readonly",values=sorted(self.db.FILTER_OPERATORS)).grid(row=1,column=1,sticky="ew",padx=4)
        ttk.Entry(filtres,textvariable=self.treatment_filter_value).grid(row=1,column=2,sticky="ew",padx=4)
        ttk.Button(filtres,text="Ajouter le filtre",style="Primary.TButton",command=self._add_treatment_filter).grid(row=1,column=3,padx=4)
        columns=("colonne","operateur","valeur");self.treatment_filter_tree=ttk.Treeview(filtres,columns=columns,show="headings",height=5)
        for column,title,width in [("colonne","Colonne du listing",230),("operateur","Condition",150),("valeur","Contenu",300)]:self.treatment_filter_tree.heading(column,text=title);self.treatment_filter_tree.column(column,width=width,anchor="w")
        self.treatment_filter_tree.grid(row=2,column=0,columnspan=4,sticky="nsew",padx=4,pady=(10,6))
        actions=ttk.Frame(filtres);actions.grid(row=3,column=0,columnspan=4,sticky="ew",padx=4)
        ttk.Button(actions,text="Supprimer le filtre sélectionné",command=self._delete_treatment_filter).pack(side="left")
        ttk.Button(actions,text="Réinitialiser les filtres",command=self._clear_treatment_filters).pack(side="left",padx=6)
        ttk.Button(actions,text="Vérifier le périmètre",style="Secondary.TButton",command=self._preview_treatment_scope).pack(side="right")
        for col in range(4):filtres.columnconfigure(col,weight=1)
        filtres.rowconfigure(2,weight=1)
        info=ttk.LabelFrame(self.match_page,text="Règles du traitement",style="Section.TLabelframe",padding=10);info.pack(fill="x",pady=4)
        ttk.Label(info,text="Les filtres sont combinés avec ET. NU / N.U est traité comme matricule non exploitable et exclu des doublons.").pack(anchor="w")
        buttons=ttk.Frame(self.match_page);buttons.pack(fill="x",pady=10)
        self.match_button=ttk.Button(buttons,text="Lancer le rapprochement",style="Primary.TButton",command=self._run_matching);self.match_button.pack(side="right",padx=5)
        ttk.Button(buttons,text="Générer le rapport final et les annexes",style="Secondary.TButton",command=self._export_report).pack(side="right",padx=5)

    def _build_admin(self):
        self._page_heading(self.admin_page,"Configuration métier","Gérez les institutions et ajoutez des régimes sans modifier le code.")
        institution=ttk.LabelFrame(self.admin_page,text="Institutions",style="Section.TLabelframe",padding=12);institution.pack(fill="x",pady=(0,12))
        self.inst_code=tk.StringVar();self.inst_name=tk.StringVar()
        ttk.Label(institution,text="Code").grid(row=0,column=0,sticky="w");ttk.Entry(institution,textvariable=self.inst_code).grid(row=1,column=0,sticky="ew",padx=(0,8))
        ttk.Label(institution,text="Nom officiel affiché").grid(row=0,column=1,sticky="w");ttk.Entry(institution,textvariable=self.inst_name).grid(row=1,column=1,sticky="ew")
        ttk.Button(institution,text="Ajouter l’institution",style="Primary.TButton",command=self._add_institution).grid(row=1,column=2,padx=8);institution.columnconfigure(1,weight=1)
        regime=ttk.LabelFrame(self.admin_page,text="Régimes de paie",style="Section.TLabelframe",padding=12);regime.pack(fill="both",expand=True)
        form=ttk.Frame(regime);form.pack(fill="x",pady=(0,10))
        self.regime_code=tk.StringVar();self.regime_label=tk.StringVar();self.regime_pattern=tk.StringVar(value=r"^Tab_NouveauRegime_T[1-4]_\d{4}$");self.regime_raw=tk.StringVar(value="raw_nouveau_regime")
        fields=[("Code",self.regime_code,16),("Libellé",self.regime_label,24),("Motif de table Access",self.regime_pattern,34),("Table RAW DuckDB",self.regime_raw,24)]
        for col,(label,var,width) in enumerate(fields):
            ttk.Label(form,text=label).grid(row=0,column=col,sticky="w",padx=4);ttk.Entry(form,textvariable=var,width=width).grid(row=1,column=col,sticky="ew",padx=4);form.columnconfigure(col,weight=1)
        actions=ttk.Frame(regime);actions.pack(fill="x",pady=(0,10))
        ttk.Button(actions,text="Enregistrer le régime",style="Primary.TButton",command=self._save_regime).pack(side="right",padx=4)
        ttk.Button(actions,text="Nouveau",style="Secondary.TButton",command=self._clear_regime_form).pack(side="right",padx=4)
        ttk.Button(actions,text="Activer / désactiver",style="Secondary.TButton",command=self._toggle_regime).pack(side="right",padx=4)
        columns=("code","libelle","pattern","raw","actif");self.regime_tree=ttk.Treeview(regime,columns=columns,show="headings",height=8)
        for column,title,width in [("code","Code",150),("libelle","Libellé",220),("pattern","Détection Access",330),("raw","Destination RAW",190),("actif","Actif",70)]:self.regime_tree.heading(column,text=title);self.regime_tree.column(column,width=width,anchor="w")
        self.regime_tree.pack(fill="both",expand=True);self.regime_tree.bind("<<TreeviewSelect>>",self._select_regime)
        self._refresh_regime_tree()

    def _refresh_regime_tree(self):
        if not hasattr(self,"regime_tree"):return
        self.regime_tree.delete(*self.regime_tree.get_children())
        for row in self.db.list_regimes(active_only=False):self.regime_tree.insert("","end",iid=row[0],values=(row[0],row[1],row[2],row[3],"Oui" if row[4] else "Non"))

    def _save_regime(self):
        try:self.db.upsert_regime(self.regime_code.get(),self.regime_label.get(),self.regime_pattern.get(),self.regime_raw.get(),True)
        except ValueError as exc:messagebox.showwarning("Configuration invalide",str(exc));return
        self._sync_regimes_from_database();self._refresh_all_regimes();self._refresh_regime_tree();self._clear_regime_form();messagebox.showinfo("Régime","Régime enregistré et disponible dans les sélecteurs.")

    def _select_regime(self,_event=None):
        selected=self.regime_tree.selection()
        if not selected:return
        values=self.regime_tree.item(selected[0],"values");self.regime_code.set(values[0]);self.regime_label.set(values[1]);self.regime_pattern.set(values[2]);self.regime_raw.set(values[3])

    def _toggle_regime(self):
        selected=self.regime_tree.selection()
        if not selected:return
        values=self.regime_tree.item(selected[0],"values");self.db.set_regime_active(values[0],values[4]!="Oui");self._sync_regimes_from_database();self._refresh_all_regimes();self._refresh_regime_tree()

    def _clear_regime_form(self):
        self.regime_code.set("");self.regime_label.set("");self.regime_pattern.set(r"^Tab_NouveauRegime_T[1-4]_\d{4}$");self.regime_raw.set("raw_nouveau_regime")



    def _build_explorer(self):
        self._page_heading(self.explorer_page,"Explorer les données existantes","Consultez les tables DuckDB, appliquez un filtre et exportez le résultat affiché.")
        filters=ttk.LabelFrame(self.explorer_page,text="Lecture et filtres",style="Section.TLabelframe",padding=12);filters.pack(fill="x",pady=(0,10))
        self.explorer_table=tk.StringVar();self.explorer_column=tk.StringVar();self.explorer_operator=tk.StringVar();self.explorer_value=tk.StringVar();self.explorer_limit=tk.IntVar(value=500);self.explorer_offset=tk.IntVar(value=0)
        labels=["Table","Colonne","Opérateur","Valeur","Limite"]
        for col,label in enumerate(labels):ttk.Label(filters,text=label).grid(row=0,column=col,sticky="w",padx=4)
        self.explorer_table_combo=ttk.Combobox(filters,textvariable=self.explorer_table,state="readonly",values=self.explorer.list_tables());self.explorer_table_combo.grid(row=1,column=0,sticky="ew",padx=4);self.explorer_table_combo.bind("<<ComboboxSelected>>",self._explorer_table_changed)
        self.explorer_column_combo=ttk.Combobox(filters,textvariable=self.explorer_column,state="readonly");self.explorer_column_combo.grid(row=1,column=1,sticky="ew",padx=4)
        ttk.Combobox(filters,textvariable=self.explorer_operator,state="readonly",values=[""]+self.explorer.OPERATORS).grid(row=1,column=2,sticky="ew",padx=4)
        ttk.Entry(filters,textvariable=self.explorer_value).grid(row=1,column=3,sticky="ew",padx=4)
        ttk.Spinbox(filters,from_=1,to=10000,textvariable=self.explorer_limit,width=9).grid(row=1,column=4,sticky="ew",padx=4)
        ttk.Button(filters,text="Actualiser les tables",style="Secondary.TButton",command=self._refresh_explorer_tables).grid(row=2,column=0,padx=4,pady=10,sticky="w")
        ttk.Button(filters,text="Effacer le filtre",style="Secondary.TButton",command=self._clear_explorer_filter).grid(row=2,column=2,padx=4,pady=10)
        ttk.Button(filters,text="Afficher",style="Primary.TButton",command=self._read_existing_data).grid(row=2,column=4,padx=4,pady=10,sticky="e")
        for col in range(5):filters.columnconfigure(col,weight=1)
        result=ttk.LabelFrame(self.explorer_page,text="Résultats",style="Section.TLabelframe",padding=8);result.pack(fill="both",expand=True)
        table_frame=ttk.Frame(result);table_frame.pack(fill="both",expand=True)
        self.explorer_tree=ttk.Treeview(table_frame,show="headings")
        yscroll=ttk.Scrollbar(table_frame,orient="vertical",command=self.explorer_tree.yview);xscroll=ttk.Scrollbar(table_frame,orient="horizontal",command=self.explorer_tree.xview)
        self.explorer_tree.configure(yscrollcommand=yscroll.set,xscrollcommand=xscroll.set);self.explorer_tree.grid(row=0,column=0,sticky="nsew");yscroll.grid(row=0,column=1,sticky="ns");xscroll.grid(row=1,column=0,sticky="ew");table_frame.rowconfigure(0,weight=1);table_frame.columnconfigure(0,weight=1)
        self.explorer_tree.bind("<MouseWheel>",self._scroll_explorer)
        self.explorer_tree.bind("<Button-4>",self._scroll_explorer)
        self.explorer_tree.bind("<Button-5>",self._scroll_explorer)
        actions=ttk.Frame(result);actions.pack(fill="x",pady=(8,0));self.explorer_count=tk.StringVar(value="Aucune donnée affichée");ttk.Label(actions,textvariable=self.explorer_count).pack(side="left")
        ttk.Button(actions,text="Page précédente",style="Secondary.TButton",command=lambda:self._change_explorer_page(-1)).pack(side="right",padx=3);ttk.Button(actions,text="Page suivante",style="Secondary.TButton",command=lambda:self._change_explorer_page(1)).pack(side="right",padx=3);ttk.Button(actions,text="Exporter cette sélection",style="Secondary.TButton",command=self._export_explorer).pack(side="right",padx=3);ttk.Button(actions,text="Réinitialiser les résultats",style="Secondary.TButton",command=self._reset_explorer_results).pack(side="right",padx=3)

    def _refresh_explorer_tables(self):
        tables=self.explorer.list_tables();self.explorer_table_combo["values"]=tables
        if self.explorer_table.get() not in tables:self.explorer_table.set("");self.explorer_column.set("")

    def _explorer_table_changed(self,_event=None):
        try:columns=self.explorer.columns(self.explorer_table.get())
        except ValueError:return
        self.explorer_column_combo["values"]=[""]+columns;self.explorer_column.set("");self.explorer_offset.set(0)

    def _explorer_filters(self):
        table=self.explorer_table.get()
        if not table:raise ValueError("Sélectionnez une table DuckDB.")
        return dict(table=table,column=self.explorer_column.get(),operator=self.explorer_operator.get(),value=self.explorer_value.get(),limit=self.explorer_limit.get(),offset=self.explorer_offset.get())

    def _read_existing_data(self):
        try:filters=self._explorer_filters()
        except ValueError as exc:messagebox.showwarning("Lecture",str(exc));return
        self._background(lambda:self.explorer.read(**filters),self._display_explorer_data)

    def _display_explorer_data(self,data):
        self.current_explorer_frame=data;self.explorer_tree.delete(*self.explorer_tree.get_children());columns=list(data.columns);self.explorer_tree["columns"]=columns
        for column in columns:self.explorer_tree.heading(column,text=str(column));self.explorer_tree.column(column,width=145,anchor="w")
        for row in data.fillna("").itertuples(index=False,name=None):self.explorer_tree.insert("","end",values=row)
        start=self.explorer_offset.get()+1 if len(data) else 0;end=self.explorer_offset.get()+len(data);self.explorer_count.set(f"{len(data)} ligne(s) affichée(s) — positions {start} à {end}")

    def _clear_explorer_filter(self):
        self.explorer_column.set("");self.explorer_operator.set("");self.explorer_value.set("");self.explorer_offset.set(0)

    def _reset_explorer_results(self):
        self._clear_explorer_filter()
        self.explorer_tree.delete(*self.explorer_tree.get_children())
        self.explorer_tree["columns"]=()
        self.current_explorer_frame=None
        self.explorer_count.set("Aucune donnée affichée")

    def _scroll_explorer(self,event):
        if getattr(event,"num",None)==4:units=-3
        elif getattr(event,"num",None)==5:units=3
        else:units=-1*int(event.delta/120) if getattr(event,"delta",0) else 0
        if units:self.explorer_tree.yview_scroll(units,"units")
        return "break"

    def _change_explorer_page(self,direction):
        if not self.explorer_table.get():return
        self.explorer_offset.set(max(0,self.explorer_offset.get()+direction*self.explorer_limit.get()));self._read_existing_data()

    def _export_explorer(self):
        try:filters=self._explorer_filters()
        except ValueError as exc:messagebox.showwarning("Export",str(exc));return
        target=filedialog.asksaveasfilename(defaultextension=".xlsx",filetypes=[("Excel","*.xlsx")])
        if target:self._background(lambda:self.explorer.export(target,**filters),lambda path:messagebox.showinfo("Export",f"Données exportées :\n{path}"))

    def _build_mapping(self):
        self._page_heading(self.mapping_page,"Mapping des colonnes","Associez les colonnes propres à chaque régime au schéma analytique standard.")
        panel=ttk.LabelFrame(self.mapping_page,text="Nouvelle correspondance",style="Section.TLabelframe",padding=14);panel.pack(fill="x",pady=(0,12))
        self.map_regime=tk.StringVar();self.map_source_type=tk.StringVar(value="ACCESS");self.map_source_column=tk.StringVar();self.map_target_column=tk.StringVar();self.map_required=tk.BooleanVar(value=False)
        targets=["matricule_source","nom","prenom","section","categorie","grade","service","unite_affectation","province","remuneration_base","transport","prime","logement","pension_rente","autres_remunerations","retenues","montant_net","remuneration_declaree","statut_agent"]
        fields=[("Régime",self.map_regime),("Type de source",self.map_source_type),("Colonne dans le fichier",self.map_source_column),("Colonne standard",self.map_target_column)]
        for col,(label,var) in enumerate(fields):
            ttk.Label(panel,text=label).grid(row=0,column=col,sticky="w",padx=5)
            if col==0:
                widget=self.map_regime_combo=ttk.Combobox(panel,textvariable=var,state="readonly",values=list(self.config_data.regimes))
            elif col==1:
                widget=self.map_source_combo=ttk.Combobox(panel,textvariable=var,state="readonly",values=["ACCESS","EXCEL"])
            elif col==3:
                widget=self.map_target_combo=ttk.Combobox(panel,textvariable=var,state="readonly",values=targets)
            else:
                widget=self.map_source_entry=ttk.Entry(panel,textvariable=var)
            widget.grid(row=1,column=col,sticky="ew",padx=5)
            panel.columnconfigure(col,weight=1)
        ttk.Checkbutton(panel,text="Colonne obligatoire",variable=self.map_required).grid(row=2,column=0,sticky="w",padx=5,pady=10)
        ttk.Button(panel,text="Enregistrer le mapping",style="Primary.TButton",command=self._save_mapping).grid(row=2,column=3,sticky="e",padx=5,pady=10)
        table=ttk.LabelFrame(self.mapping_page,text="Mappings configurés",style="Section.TLabelframe",padding=10);table.pack(fill="both",expand=True)
        columns=("regime","source_type","source","target","required");self.mapping_tree=ttk.Treeview(table,columns=columns,show="headings",height=12)
        for column,title,width in [("regime","Régime",160),("source_type","Source",100),("source","Colonne du fichier",250),("target","Colonne standard",250),("required","Obligatoire",100)]:self.mapping_tree.heading(column,text=title);self.mapping_tree.column(column,width=width,anchor="w")
        self.mapping_tree.pack(fill="both",expand=True);self.mapping_tree.bind("<<TreeviewSelect>>",self._select_mapping)
        actions=ttk.Frame(table);actions.pack(fill="x",pady=(8,0));ttk.Button(actions,text="Supprimer la sélection",style="Secondary.TButton",command=self._delete_mapping).pack(side="right")
        self._refresh_mapping_tree()

    def _refresh_mapping_tree(self):
        if not hasattr(self,"mapping_tree"):return
        self.mapping_tree.delete(*self.mapping_tree.get_children())
        for index,row in enumerate(self.db.list_column_mappings()):self.mapping_tree.insert("","end",iid=str(index),values=(row[0],row[1],row[2],row[3],"Oui" if row[4] else "Non"))

    def _save_mapping(self):
        try:self.db.upsert_column_mapping(self.map_regime.get(),self.map_source_type.get(),self.map_source_column.get(),self.map_target_column.get(),self.map_required.get())
        except ValueError as exc:messagebox.showwarning("Mapping invalide",str(exc));return
        self._refresh_mapping_tree();self.map_source_column.set("");self.map_target_column.set("");self.map_required.set(False);messagebox.showinfo("Mapping","La correspondance sera appliquée aux prochains imports.")

    def _select_mapping(self,_event=None):
        selected=self.mapping_tree.selection()
        if not selected:return
        values=self.mapping_tree.item(selected[0],"values");self.map_regime.set(values[0]);self.map_source_type.set(values[1]);self.map_source_column.set(values[2]);self.map_target_column.set(values[3]);self.map_required.set(values[4]=="Oui")

    def _delete_mapping(self):
        selected=self.mapping_tree.selection()
        if not selected:return
        values=self.mapping_tree.item(selected[0],"values")
        if messagebox.askyesno("Supprimer","Supprimer cette correspondance de colonnes ?"):
            self.db.delete_column_mapping(values[0],values[1],values[2]);self._refresh_mapping_tree()

    def _refresh_institution_combo(self, combo):
        rows=self.db.list_institutions()
        self.institution_ids_by_name.update({row[2]: row[0] for row in rows})
        combo["values"]=[row[2] for row in rows]

    def _refresh_all_institutions(self):
        for scope in [self.access_scope,self.excel_scope,self.match_scope]: self._refresh_institution_combo(scope["institution_combo"])
        if hasattr(self,"dashboard_institution_combo"):
            names=[row[2] for row in self.db.list_institutions()];self.dashboard_institution_combo["values"]=["Toutes"]+names
            if self.dashboard_institution.get() not in names:self.dashboard_institution.set("Toutes")

    def _refresh_all_regimes(self):
        values=list(self.config_data.regimes)
        for scope in [self.access_scope,self.excel_scope,self.match_scope]:
            scope["regime_combo"]["values"]=values
            if scope["regime"].get() not in values:scope["regime"].set("")
        if hasattr(self,"map_regime_combo"):
            self.map_regime_combo["values"]=values
            if self.map_regime.get() not in values:self.map_regime.set("")
        if hasattr(self,"dashboard_regime_combo"):
            self.dashboard_regime_combo["values"]=["Tous"]+values
            if self.dashboard_regime.get() not in values:self.dashboard_regime.set("Tous")

    def _choose_access(self):
        path=filedialog.askopenfilename(filetypes=[("Access","*.accdb *.mdb")]); self.access_path.set(path or self.access_path.get())
    def _choose_excel(self):
        path=filedialog.askopenfilename(filetypes=[("Excel","*.xlsx *.xls")]);
        if path:
            self.excel_path.set(path); self.sheet_combo["values"]=excel_sheets(path)
            if self.sheet_combo["values"]: self.excel_sheet.set(self.sheet_combo["values"][0])
    def _scan_access(self):
        if not self.access_path.get().strip():
            messagebox.showwarning("Fichier manquant", "Sélectionnez d’abord une base Access.")
            return
        self._background(lambda: list_access_tables(self.access_path.get(),self.config_data.access_driver), self._tables_loaded)
    def _tables_loaded(self,tables):
        self.table_combo["values"]=tables
        if tables: self.access_table.set(tables[0]); self._autofill_table(tables[0])
    def _autofill_table(self,table):
        regime=self.config_data.detect_regime(table); quarter,year=self.config_data.detect_period(table)
        if regime:self.access_scope["regime"].set(regime)
        if quarter:self.access_scope["quarter"].set(quarter)
        if year:self.access_scope["year"].set(str(year))
    def _preview_excel(self):
        if not self.excel_path.get().strip() or not self.excel_sheet.get().strip():
            messagebox.showwarning("Source incomplète", "Sélectionnez un fichier Excel et une feuille.")
            return
        try:
            frame=preview_excel(self.excel_path.get(),self.excel_sheet.get(),self.header_row.get())
        except Exception as exc:
            messagebox.showerror("Lecture Excel impossible", str(exc))
            return
        self.preview.delete(*self.preview.get_children()); self.preview["columns"]=list(frame.columns)
        for c in frame.columns:self.preview.heading(c,text=str(c));self.preview.column(c,width=130)
        for row in frame.fillna("").itertuples(index=False,name=None):self.preview.insert("", "end", values=row)
    def _scope_values(self,scope):
        institution_name=scope["institution"].get().strip()
        institution_id=self.institution_ids_by_name.get(institution_name, "")
        return validate_scope_values(institution_id,scope["regime"].get(),scope["quarter"].get(),scope["year"].get())
    def _validated_scope(self,scope):
        try:return self._scope_values(scope)
        except ValueError as exc:
            messagebox.showwarning("Périmètre incomplet",str(exc));return None
    def _load_access(self):
        args=self._validated_scope(self.access_scope)
        if args is None:return
        if not self.access_path.get().strip() or not self.access_table.get().strip():
            messagebox.showwarning("Source incomplète","Sélectionnez une base Access et une table.");return
        self._background(lambda:self.ingestion.load_access(self.access_path.get(),self.access_table.get(),*args,progress=self._progress),lambda _:messagebox.showinfo("Terminé","Table Access chargée"))
    def _load_excel(self):
        args=self._validated_scope(self.excel_scope)
        if args is None:return
        if not self.excel_path.get().strip() or not self.excel_sheet.get().strip():
            messagebox.showwarning("Source incomplète","Sélectionnez un fichier Excel et une feuille.");return
        self._background(lambda:self.ingestion.load_excel(self.excel_path.get(),self.excel_sheet.get(),self.header_row.get(),*args,progress=self._progress),lambda _:messagebox.showinfo("Terminé","Déclaratif chargé"))
    def _treatment_filter_scope(self):
        name=self.match_scope["institution"].get().strip();institution_id=self.institution_ids_by_name.get(name,"");regime=self.match_scope["regime"].get().strip()
        if not institution_id or not regime:raise ValueError("Sélectionnez d’abord l’institution et le régime.")
        return institution_id,regime

    def _refresh_treatment_filters(self):
        if not hasattr(self,"treatment_filter_tree"):return
        self.treatment_filter_tree.delete(*self.treatment_filter_tree.get_children())
        try:institution_id,regime=self._treatment_filter_scope()
        except ValueError:return
        for filter_id,column,operator,value in self.db.list_treatment_filters(institution_id,regime):
            self.treatment_filter_tree.insert("","end",iid=filter_id,values=(column,operator,value))

    def _add_treatment_filter(self):
        try:
            institution_id,regime=self._treatment_filter_scope()
            self.db.add_treatment_filter(institution_id,regime,self.treatment_filter_column.get(),self.treatment_filter_operator.get(),self.treatment_filter_value.get())
        except ValueError as exc:messagebox.showwarning("Filtre incomplet",str(exc));return
        self.treatment_filter_value.set("");self._refresh_treatment_filters();self._preview_treatment_scope()

    def _delete_treatment_filter(self):
        selected=self.treatment_filter_tree.selection()
        if not selected:messagebox.showwarning("Filtre","Sélectionnez un filtre à supprimer.");return
        self.db.delete_treatment_filter(selected[0]);self._refresh_treatment_filters()

    def _clear_treatment_filters(self):
        try:institution_id,regime=self._treatment_filter_scope()
        except ValueError as exc:messagebox.showwarning("Périmètre incomplet",str(exc));return
        if messagebox.askyesno("Réinitialiser","Supprimer tous les filtres métier de ce listing ?"):
            self.db.clear_treatment_filters(institution_id,regime);self._refresh_treatment_filters()

    def _preview_treatment_scope(self):
        try:
            institution_id,regime=self._treatment_filter_scope();quarter=self.match_scope["quarter"].get();year=self.match_scope["year"].get()
            if not quarter or not year:raise ValueError("Sélectionnez aussi le trimestre et l’année.")
            clause,values=self.db.payroll_filter_clause(institution_id,regime,"p")
            with self.db.connect() as con:
                total=con.execute("SELECT COUNT(*) FROM paie_standardisee p WHERE p.institution_id=? AND p.regime=? AND p.trimestre=? AND p.annee=?",[institution_id,regime,quarter,int(year)]).fetchone()[0]
                selected=con.execute("SELECT COUNT(*) FROM paie_standardisee p WHERE p.institution_id=? AND p.regime=? AND p.trimestre=? AND p.annee=?"+clause,[institution_id,regime,quarter,int(year)]+values).fetchone()[0]
            messagebox.showinfo("Périmètre du listing",f"Lignes disponibles : {total:,}\nLignes retenues après filtres : {selected:,}".replace(","," "))
        except ValueError as exc:messagebox.showwarning("Périmètre incomplet",str(exc))

    def _run_matching(self):
        args=self._validated_scope(self.match_scope)
        if args is None:return
        self._background(lambda:self.matching.run(*args,progress=self._progress),lambda run_id:self._matching_completed(run_id,args))
    def _matching_completed(self,run_id,args):
        self.status.set("Génération automatique du rapport et des annexes…")
        self._open_generation_dialog("Génération du rapport final et des annexes")
        self._background(lambda:self.reports.generate_package(str(self.config_data.results_dir),*args,progress=self._progress),self._package_completed)
    def _package_completed(self,path):
        if self.generation_window and self.generation_window.winfo_exists():
            self.generation_title.set("Génération terminée avec succès")
            self.generation_status.set(f"Dossier créé : {path}")
            self.generation_bar["value"]=100
            self.generation_close.configure(state="normal")
        messagebox.showinfo("Traitement terminé",f"Le rapprochement, le rapport final et les annexes ont été générés dans :\n{path}")
    def _export_report(self):
        args=self._validated_scope(self.match_scope)
        if args is None:return
        folder=filedialog.askdirectory(title="Choisir le dossier des résultats")
        if folder:
            self._open_generation_dialog("Génération du rapport final et des annexes")
            self._background(lambda:self.reports.generate_package(folder,*args,progress=self._progress),self._package_completed)
    def _add_institution(self):
        if not self.inst_code.get().strip() or not self.inst_name.get().strip(): return
        self.db.add_institution(self.inst_code.get().strip().upper(),self.inst_name.get().strip()); self._refresh_all_institutions(); self._refresh_dashboard(); self.inst_code.set("");self.inst_name.set("")
    def _open_generation_dialog(self,title):
        if self.generation_window and self.generation_window.winfo_exists():self.generation_window.destroy()
        window=self.generation_window=tk.Toplevel(self);window.title(title);window.geometry("720x460");window.minsize(620,380);window.transient(self)
        header=tk.Frame(window,background="#12355B",padx=20,pady=16);header.pack(fill="x")
        self.generation_title=tk.StringVar(value=title);tk.Label(header,textvariable=self.generation_title,background="#12355B",foreground="white",font=("DejaVu Sans",15,"bold")).pack(anchor="w")
        tk.Label(header,text="Ne fermez pas l’application pendant l’écriture des fichiers Excel.",background="#12355B",foreground="#CFE2F3").pack(anchor="w",pady=(3,0))
        body=ttk.Frame(window,padding=20);body.pack(fill="both",expand=True)
        self.generation_status=tk.StringVar(value="Initialisation…");ttk.Label(body,textvariable=self.generation_status,style="PageHint.TLabel").pack(anchor="w",pady=(0,8))
        self.generation_bar=ttk.Progressbar(body,maximum=100);self.generation_bar.pack(fill="x",pady=(0,15))
        ttk.Label(body,text="Fichiers générés",style="PageTitle.TLabel").pack(anchor="w",pady=(0,6))
        list_frame=ttk.Frame(body);list_frame.pack(fill="both",expand=True)
        self.generated_files=tk.Listbox(list_frame,bg="white",fg="#243247",font=("DejaVu Sans",10),relief="solid",borderwidth=1,activestyle="none")
        scroll=ttk.Scrollbar(list_frame,orient="vertical",command=self.generated_files.yview);self.generated_files.configure(yscrollcommand=scroll.set);self.generated_files.pack(side="left",fill="both",expand=True);scroll.pack(side="right",fill="y")
        self.generation_close=ttk.Button(body,text="Fermer",style="Primary.TButton",state="disabled",command=window.destroy);self.generation_close.pack(anchor="e",pady=(12,0))
        window.protocol("WM_DELETE_WINDOW",lambda:messagebox.showwarning("Traitement en cours","Attendez la fin de la génération avant de fermer cette fenêtre."));window.after_idle(lambda:self._center_child_window(window))

    def _update_generation_dialog(self,value,text):
        if not self.generation_window or not self.generation_window.winfo_exists():return
        self.generation_bar["value"]=value;self.generation_status.set(f"{value}% — {text}")
        if text.startswith("Fichier généré :"):
            filename=text.split(":",1)[1].strip();self.generated_files.insert("end",f"✓  {filename}");self.generated_files.see("end")

    def _generation_failed(self,error):
        if self.generation_window and self.generation_window.winfo_exists():
            self.generation_title.set("La génération a rencontré une erreur");self.generation_status.set(str(error));self.generation_close.configure(state="normal")

    def _progress(self,value,text): self.events.put(("progress",(value,text)))
    def _background(self,task,success):
        if self.busy:
            messagebox.showwarning("Traitement en cours","Attendez la fin du traitement actuel avant d’en lancer un autre.")
            return
        self.busy=True;self.status.set("Traitement en cours…");self.progress["value"]=0
        def worker():
            try:self.events.put(("success",(success,task())))
            except Exception as exc:self.events.put(("error",exc))
        threading.Thread(target=worker,daemon=True).start()
    def _poll_events(self):
        try:
            while True:
                kind,payload=self.events.get_nowait()
                if kind=="progress":self.progress["value"],text=payload;self.status.set(text);self._update_generation_dialog(self.progress["value"],text)
                elif kind=="success":callback,result=payload;self.busy=False;self.status.set("Prêt");self.progress["value"]=100;self._refresh_dashboard();self._refresh_explorer_tables();callback(result)
                else:self.busy=False;self.status.set("Erreur");self._generation_failed(payload);messagebox.showerror("Erreur",str(payload))
        except queue.Empty:pass
        self.after(100,self._poll_events)
