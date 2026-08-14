from __future__ import annotations

import logging
import os
import platform
import queue
import shutil
import struct
import threading
import time
import tkinter as tk
import traceback
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from .config import AppConfig, RegimeConfig
from .database import Database
from .loaders import (IngestionService, describe_declaration_structure, excel_sheets,
                      list_access_tables, preview_excel)
from .matching import MatchingService
from .multiregime import MultiRegimeAnalysisService
from .listing_analysis import ListingGroupAnalysisService
from .reports import ReportService
from .explorer import DataExplorerService
from .errors import explain_error
from .file_tools import ocr_available, pdf_to_excel, pdf_to_word, rotate_pdf, tesseract_path
from .help_content import USER_GUIDE
from .licensing import CLOCK_ROLLBACK, EXPIRED, EXPIRING, INVALID, TrialManager
from .runtime import APP_NAME, APP_VERSION, CURRENT_SCHEMA_VERSION, DEVELOPER, backup_database, configure_logging, database_schema_version, initialize_runtime, open_path, resource_path

IMPACT_MODE_AUTO="Automatique par régime et rubrique"
IMPACT_MODE_SELECTED="Forcer une formule globale sélectionnée"


def fitted_window_geometry(screen_width: int, screen_height: int, requested_width: int, requested_height: int, center_x: int, center_y: int) -> tuple[int, int, int, int]:
    """Fit a child window inside the visible screen and keep it centered."""
    margin_x, margin_top, margin_bottom = 24, 48, 72
    maximum_width=max(320,screen_width-margin_x*2);maximum_height=max(280,screen_height-margin_top-margin_bottom)
    width=min(max(480,requested_width),maximum_width);height=min(max(360,requested_height),maximum_height)
    x=max(margin_x,min(center_x-width//2,screen_width-width-margin_x))
    y=max(margin_top,min(center_y-height//2,screen_height-height-margin_bottom))
    return width,height,x,y


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
        self.trial_manager=TrialManager(Path(self.config_data.database_path).parent);self.trial_status=self.trial_manager.check()
        logging.info("État de la version d’essai : %s — %s",self.trial_status.code,self.trial_status.message)
        current_schema=database_schema_version(Path(self.config_data.database_path))
        pre_migration_backup=backup_database(Path(self.config_data.database_path),Path(self.config_data.backups_dir),"avant_migration") if current_schema<CURRENT_SCHEMA_VERSION else None
        if pre_migration_backup:logging.info("Sauvegarde avant migration du schéma %s vers %s : %s",current_schema,CURRENT_SCHEMA_VERSION,pre_migration_backup)
        self.db = Database(self.config_data.database_path)
        self.db.migrate();logging.info("SICORPA %s démarré avec la base %s",APP_VERSION,self.config_data.database_path)
        self._sync_regimes_from_database()
        self.ingestion = IngestionService(self.db, self.config_data)
        self.matching = MatchingService(self.db)
        self.multi_analysis = MultiRegimeAnalysisService(self.db)
        self.listing_analysis = ListingGroupAnalysisService(self.db)
        self.reports = ReportService(self.db)
        self.explorer = DataExplorerService(self.db)
        self.institution_ids_by_name = {}
        self.events: queue.Queue = queue.Queue()
        self.busy = False
        self._progress_lock=threading.Lock()
        self._last_progress_emit=(0.0,None,"")
        self.generation_window = None
        self.title(f"{APP_NAME} {APP_VERSION} — Contrôle et rapprochement de la paie")
        self._apply_window_icon()
        self.geometry("1280x820")
        screen_width=self.winfo_screenwidth();screen_height=self.winfo_screenheight()
        self.minsize(min(1000,max(760,screen_width-120)),min(680,max(560,screen_height-160)))
        self.configure(background="#F3F6FA")
        self.after_idle(self._center_main_window)
        self.after(120,self._maximize_main_window)
        self._build_style()
        self._build_menu()
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW",self._request_close)
        self.after(100, self._poll_events)
        self.after(700,self._notify_trial_status)


    def _apply_window_icon(self):
        """Apply the packaged icon to the main window and all child dialogs."""
        try:
            icon_path=resource_path("assets/sicorpa.png")
            self._window_icon=tk.PhotoImage(file=str(icon_path))
            self.iconphoto(True,self._window_icon)
            if platform.system()=="Windows":
                ico_path=resource_path("assets/sicorpa.ico")
                if ico_path.exists():self.iconbitmap(default=str(ico_path))
        except (tk.TclError,OSError) as exc:
            logging.warning("Icône SICORPA indisponible : %s",exc)

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
        self.update_idletasks();screen_width=self.winfo_screenwidth();screen_height=self.winfo_screenheight()
        current_width=self.winfo_width();current_height=self.winfo_height()
        width=min(current_width if current_width>1 else 1280,max(760,screen_width-48));height=min(current_height if current_height>1 else 820,max(560,screen_height-96))
        self.geometry(f"{width}x{height}+{max(0,(screen_width-width)//2)}+{max(0,(screen_height-height)//2)}")

    def _maximize_main_window(self):
        """Use the operating system maximized mode, with a centered safe fallback."""
        self._center_main_window();self.update_idletasks()
        try:
            if platform.system()=="Windows":self.state("zoomed")
            else:self.attributes("-zoomed",True)
        except tk.TclError:
            screen_width=self.winfo_screenwidth();screen_height=self.winfo_screenheight()
            self.geometry(f"{max(760,screen_width)}x{max(560,screen_height-48)}+0+0")

    def _center_child_window(self,window,preferred_width=None,preferred_height=None):
        window.update_idletasks();requested_width=max(preferred_width or 0,window.winfo_width(),window.winfo_reqwidth());requested_height=max(preferred_height or 0,window.winfo_height(),window.winfo_reqheight())
        center_x=self.winfo_rootx()+self.winfo_width()//2;center_y=self.winfo_rooty()+self.winfo_height()//2
        width,height,x,y=fitted_window_geometry(window.winfo_screenwidth(),window.winfo_screenheight(),requested_width,requested_height,center_x,center_y)
        window.geometry(f"{width}x{height}+{x}+{y}");window.minsize(min(520,width),min(360,height));window.resizable(True,True)
        window.lift();window.focus_set()

    def _scrollable_dialog_body(self,window,padding=20):
        host=ttk.Frame(window);host.pack(fill="both",expand=True)
        canvas=tk.Canvas(host,background="#F3F6FA",highlightthickness=0)
        scrollbar=ttk.Scrollbar(host,orient="vertical",command=canvas.yview);canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right",fill="y");canvas.pack(side="left",fill="both",expand=True)
        body=ttk.Frame(canvas,padding=padding);body_id=canvas.create_window((0,0),window=body,anchor="nw")
        body.bind("<Configure>",lambda _event:canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",lambda event:canvas.itemconfigure(body_id,width=event.width))
        def wheel(event):
            if getattr(event,"num",None)==4:delta=-1
            elif getattr(event,"num",None)==5:delta=1
            else:delta=-1 if event.delta>0 else 1
            canvas.yview_scroll(delta,"units")
        def enable_wheel(_event):
            canvas.bind_all("<MouseWheel>",wheel)
            canvas.bind_all("<Button-4>",wheel)
            canvas.bind_all("<Button-5>",wheel)
        def disable_wheel(_event):
            canvas.unbind_all("<MouseWheel>")
            canvas.unbind_all("<Button-4>")
            canvas.unbind_all("<Button-5>")
        return body

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
        tools_menu=tk.Menu(menu,tearoff=False)
        tools_menu.add_command(label="Faire pivoter un PDF…",command=lambda:self._show_file_tool("ROTATE"))
        tools_menu.add_separator()
        tools_menu.add_command(label="Convertir un PDF en Excel…",command=lambda:self._show_file_tool("EXCEL"))
        tools_menu.add_command(label="Convertir un PDF en Word…",command=lambda:self._show_file_tool("WORD"))
        menu.add_cascade(label="Outils fichiers",menu=tools_menu)
        help_menu=tk.Menu(menu,tearoff=False);help_menu.add_command(label="Mode d’emploi",command=self._show_user_guide);help_menu.add_command(label="État de la version d’essai",command=self._show_trial_status);help_menu.add_command(label="Diagnostic",command=self._show_diagnostic);help_menu.add_separator();help_menu.add_command(label="À propos de SICORPA",command=self._show_about);menu.add_cascade(label="Aide",menu=help_menu);self.configure(menu=menu)


    def _refresh_trial_status(self):
        self.trial_status=self.trial_manager.check()
        if hasattr(self,"trial_indicator"):self.trial_indicator.set(self.trial_status.short_label)
        return self.trial_status

    def _trial_date(self,value):
        return value.astimezone().strftime("%d/%m/%Y à %H:%M") if value else "Non disponible"

    def _show_trial_status(self):
        status=self._refresh_trial_status()
        content=f"""VERSION D’ESSAI SICORPA

État : {status.short_label}
Durée configurée : {status.days_total} jours
Premier lancement : {self._trial_date(status.first_run)}
Dernier lancement enregistré : {self._trial_date(status.last_run)}
Expiration : {self._trial_date(status.expires_at)}
Identifiant de construction : {status.build_id}

{status.message}

Après expiration, la consultation et l’export des données existantes restent disponibles. Les nouveaux imports, rapprochements, rapports et traitements de fichiers sont bloqués."""
        self._text_dialog("État de la version d’essai",content,"760x600")

    def _notify_trial_status(self):
        status=self._refresh_trial_status()
        if status.code==EXPIRING:messagebox.showwarning("Version d’essai",status.message+f"\n\nIl reste {status.days_remaining} jour(s).")
        elif status.code in {EXPIRED,CLOCK_ROLLBACK,INVALID}:messagebox.showerror("Version d’essai",status.message+"\n\nLes données existantes restent consultables.")

    def _require_active_trial(self,action="ce traitement"):
        status=self._refresh_trial_status()
        if status.allowed:return True
        messagebox.showerror("Traitement indisponible",f"Impossible de lancer {action}.\n\n{status.message}\n\nConsultez Aide > État de la version d’essai.")
        return False

    def _show_file_tool(self, operation: str):
        labels={"ROTATE":("Faire pivoter un PDF","Créez une copie du PDF dont toutes les pages sont orientées selon l’angle choisi."),"EXCEL":("Convertir un PDF en Excel","Extrayez les tableaux détectés, ou le texte page par page, dans un classeur structuré."),"WORD":("Convertir un PDF en Word","Extrayez le texte et les tableaux dans un document Word modifiable.")}
        title,hint=labels[operation];window=tk.Toplevel(self);window.title(f"{title} — SICORPA");window.geometry("760x480");window.minsize(680,440);window.transient(self)
        header=tk.Frame(window,background="#12355B",padx=22,pady=17);header.pack(fill="x")
        tk.Label(header,text=title,background="#12355B",foreground="white",font=("DejaVu Sans",16,"bold")).pack(anchor="w")
        tk.Label(header,text=hint,background="#12355B",foreground="#CFE2F3",wraplength=690,justify="left").pack(anchor="w",pady=(4,0))
        body=self._scrollable_dialog_body(window,padding=22)
        source=tk.StringVar();target=tk.StringVar();degrees=tk.StringVar(value="90");ocr_enabled=tk.BooleanVar(value=True);ocr_language=tk.StringVar(value="fra+eng — Français + anglais")
        ttk.Label(body,text="Fichier PDF source").grid(row=0,column=0,columnspan=2,sticky="w")
        ttk.Entry(body,textvariable=source).grid(row=1,column=0,sticky="ew",pady=(4,14));ttk.Button(body,text="Parcourir…",command=lambda:self._choose_pdf_source(source,target,operation)).grid(row=1,column=1,padx=(8,0),pady=(4,14))
        ttk.Label(body,text="Fichier de destination").grid(row=2,column=0,columnspan=2,sticky="w")
        ttk.Entry(body,textvariable=target).grid(row=3,column=0,sticky="ew",pady=(4,14));ttk.Button(body,text="Choisir…",command=lambda:self._choose_file_tool_target(target,operation)).grid(row=3,column=1,padx=(8,0),pady=(4,14))
        if operation=="ROTATE":
            angle=ttk.LabelFrame(body,text="Angle de rotation vers la droite",style="Section.TLabelframe",padding=10);angle.grid(row=4,column=0,columnspan=2,sticky="ew",pady=(0,12))
            for value in ("90","180","270"):ttk.Radiobutton(angle,text=f"{value}°",variable=degrees,value=value).pack(side="left",padx=14)
        else:
            ocr_box=ttk.LabelFrame(body,text="Reconnaissance des pages scannées",style="Section.TLabelframe",padding=10);ocr_box.grid(row=4,column=0,columnspan=2,sticky="ew",pady=(0,12))
            ttk.Checkbutton(ocr_box,text="Activer automatiquement l’OCR si une page ne contient pas de texte",variable=ocr_enabled).pack(anchor="w")
            language_row=ttk.Frame(ocr_box);language_row.pack(fill="x",pady=(8,0));ttk.Label(language_row,text="Langue").pack(side="left")
            ttk.Combobox(language_row,textvariable=ocr_language,state="readonly",values=["fra+eng — Français + anglais","fra — Français","eng — Anglais"],width=31).pack(side="left",padx=(10,0))
            status="Tesseract détecté : OCR disponible" if ocr_available() else "Tesseract absent : installez-le pour les PDF scannés"
            ttk.Label(ocr_box,text=status,style="PageHint.TLabel").pack(anchor="w",pady=(7,0))
        actions=ttk.Frame(window,padding=(22,8,22,18));actions.pack(fill="x")
        ttk.Button(actions,text="Lancer le traitement",style="Primary.TButton",command=lambda:self._run_file_tool(window,operation,source.get(),target.get(),degrees.get(),ocr_enabled.get(),ocr_language.get().split(" ",1)[0])).pack(side="right",padx=4)
        ttk.Button(actions,text="Annuler",style="Secondary.TButton",command=window.destroy).pack(side="right",padx=4)
        body.columnconfigure(0,weight=1);window.after_idle(lambda:self._center_child_window(window,760,480))

    def _choose_pdf_source(self,source,target,operation):
        path=filedialog.askopenfilename(title="Choisir le PDF",filetypes=[("Document PDF","*.pdf")])
        if not path:return
        source.set(path)
        if not target.get().strip():
            suffix={"ROTATE":"_rotation.pdf","EXCEL":"_converti.xlsx","WORD":"_converti.docx"}[operation]
            target.set(str(Path(path).with_name(f"{Path(path).stem}{suffix}")))

    def _choose_file_tool_target(self,target,operation):
        extension={"ROTATE":".pdf","EXCEL":".xlsx","WORD":".docx"}[operation]
        types={"ROTATE":[("Document PDF","*.pdf")],"EXCEL":[("Classeur Excel","*.xlsx")],"WORD":[("Document Word","*.docx")]}[operation]
        path=filedialog.asksaveasfilename(title="Choisir la destination",defaultextension=extension,filetypes=types,initialfile=Path(target.get()).name if target.get() else None)
        if path:target.set(path)

    def _run_file_tool(self,window,operation,source,target,degrees,use_ocr=True,ocr_language="fra+eng"):
        if not self._require_active_trial("le traitement de ce fichier"):return
        if self.busy:messagebox.showwarning("Traitement en cours","Attendez la fin du traitement actuel avant d’en lancer un autre.",parent=window);return
        if not source.strip() or not target.strip():messagebox.showwarning("Fichiers incomplets","Sélectionnez le PDF source et le fichier de destination.",parent=window);return
        window.destroy();title={"ROTATE":"Rotation du PDF","EXCEL":"Conversion du PDF en Excel","WORD":"Conversion du PDF en Word"}[operation]
        self._open_generation_dialog(title,"Le fichier est traité page par page. Vous pouvez suivre sa progression ci-dessous.")
        tasks={"ROTATE":lambda:rotate_pdf(source,target,int(degrees),self._progress),"EXCEL":lambda:pdf_to_excel(source,target,self._progress,use_ocr,ocr_language),"WORD":lambda:pdf_to_word(source,target,self._progress,use_ocr,ocr_language)}
        self._background(tasks[operation],self._file_tool_completed)

    def _file_tool_completed(self,path):
        if self.generation_window and self.generation_window.winfo_exists():
            self.generation_title.set("Traitement terminé avec succès");self.generation_status.set(f"Fichier créé : {path}");self.generation_bar["value"]=100
            if not self.generated_files.get(0,"end"):self.generated_files.insert("end",f"✓  {Path(path).name}")
            self.generation_close.configure(state="normal")
        messagebox.showinfo("Outil fichiers",f"Le fichier a été généré :\n{path}")

    def _open_runtime_path(self,path: Path):
        try:open_path(path)
        except Exception as exc:logging.exception("Ouverture du dossier impossible");self._show_explicit_error(exc,"Ouverture du dossier",traceback.format_exc())

    def _manual_backup(self):
        try:target=backup_database(Path(self.config_data.database_path),Path(self.config_data.backups_dir),"manuel")
        except Exception as exc:logging.exception("Sauvegarde impossible");self._show_explicit_error(exc,"Sauvegarde de la base",traceback.format_exc());return
        if target:messagebox.showinfo("Sauvegarde terminée",f"Base sauvegardée dans :\n{target}")
        else:messagebox.showwarning("Sauvegarde","La base n’existe pas encore.")

    def _text_dialog(self,title: str,content: str,geometry: str="820x650"):
        window=tk.Toplevel(self);window.title(title);window.geometry(geometry);window.minsize(620,420);window.transient(self)
        header=tk.Frame(window,background="#12355B",padx=20,pady=14);header.pack(fill="x");tk.Label(header,text=title,background="#12355B",foreground="white",font=("DejaVu Sans",15,"bold")).pack(anchor="w")
        body=ttk.Frame(window,padding=16);body.pack(fill="both",expand=True);scroll=ttk.Scrollbar(body);scroll.pack(side="right",fill="y")
        text=tk.Text(body,wrap="word",yscrollcommand=scroll.set,font=("DejaVu Sans",10),background="white",foreground="#243247",padx=14,pady=14,relief="solid",borderwidth=1);text.pack(side="left",fill="both",expand=True);scroll.configure(command=text.yview);text.insert("1.0",content);text.configure(state="disabled")
        ttk.Button(window,text="Fermer",style="Primary.TButton",command=window.destroy).pack(anchor="e",padx=16,pady=(0,14))
        preferred_width,preferred_height=(int(value) for value in geometry.split("x",1));window.after_idle(lambda:self._center_child_window(window,preferred_width,preferred_height));return window

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
                bits=struct.calcsize("P")*8;drivers=[driver for driver in pyodbc.drivers() if "Access" in driver]
                add("Lecture Access",bool(drivers),f"SICORPA {bits} bits — "+(", ".join(drivers) if drivers else f"Pilote Microsoft Access {bits} bits absent"))
            except Exception as exc:add("Lecture Access",False,str(exc))
        else:add("Lecture Access",bool(shutil.which("mdb-tables") and shutil.which("mdb-export")),"mdbtools installé" if shutil.which("mdb-tables") else "Installez mdbtools")
        add("OCR des PDF scannés",ocr_available(),str(tesseract_path()) if ocr_available() else "Installez Tesseract OCR et la langue française")
        trial=self._refresh_trial_status();add("Version d’essai",trial.allowed,trial.short_label+" — "+trial.message)
        add("Espace disque",shutil.disk_usage(database.parent).free>500*1024*1024,f"{shutil.disk_usage(database.parent).free/(1024**3):.1f} Go libres")
        tuning=self.db.tuning_info()
        add("Optimisation DuckDB",True,
            f"{tuning['threads']} threads — mémoire {tuning['memory_limit_mb']} Mo — temporaire : {tuning['temp_directory']}")
        return f"DIAGNOSTIC SICORPA {APP_VERSION}\nSystème : {platform.system()} {platform.release()}\n\n"+"\n\n".join(checks)

    def _show_diagnostic(self):self._text_dialog("Diagnostic de SICORPA",self._diagnostic_text(),"760x600")

    def _show_explicit_error(self,error,operation="",traceback_text=""):
        report=explain_error(error,traceback_text,operation)
        window=tk.Toplevel(self);window.title(f"SICORPA — {report.category}");window.transient(self)
        header=tk.Frame(window,background="#8F1D1D",padx=20,pady=15);header.pack(fill="x")
        tk.Label(header,text=report.category,background="#8F1D1D",foreground="white",
                 font=("DejaVu Sans",15,"bold")).pack(anchor="w")
        tk.Label(header,text=f"Référence {report.reference}",background="#8F1D1D",
                 foreground="#FADDDD",font=("DejaVu Sans",9)).pack(anchor="w",pady=(3,0))
        body=self._scrollable_dialog_body(window,padding=18)
        if report.operation:
            ttk.Label(body,text=f"Opération interrompue : {report.operation}",
                      style="PageTitle.TLabel").pack(anchor="w",pady=(0,8))
        ttk.Label(body,text=report.summary,wraplength=720,justify="left").pack(anchor="w",fill="x")
        ttk.Label(body,text="Actions recommandées",style="PageTitle.TLabel").pack(anchor="w",pady=(14,5))
        for index,action in enumerate(report.actions,1):
            ttk.Label(body,text=f"{index}. {action}",wraplength=700,justify="left").pack(anchor="w",fill="x",pady=2)
        ttk.Label(body,text="Détails techniques — à transmettre au support",
                  style="PageTitle.TLabel").pack(anchor="w",pady=(14,5))
        details=tk.Text(body,height=8,wrap="word",font=("DejaVu Sans Mono",9),relief="solid",borderwidth=1)
        details.insert("1.0",report.technical);details.configure(state="disabled");details.pack(fill="both",expand=True)
        actions=ttk.Frame(body);actions.pack(fill="x",pady=(12,0))
        def copy_diagnostic():
            self.clipboard_clear();self.clipboard_append(report.user_text+"\n\nDétails techniques\n"+report.technical)
            self.update();messagebox.showinfo("Diagnostic copié","Le diagnostic a été copié dans le presse-papiers.",parent=window)
        ttk.Button(actions,text="Copier le diagnostic",style="Secondary.TButton",
                   command=copy_diagnostic).pack(side="left")
        log_path=Path(self.config_data.logs_dir)/"sicorpa.log"
        if log_path.exists():
            ttk.Button(actions,text="Ouvrir le journal",style="Secondary.TButton",
                       command=lambda:self._open_runtime_path(log_path)).pack(side="left",padx=6)
        ttk.Button(actions,text="Fermer",style="Primary.TButton",
                   command=window.destroy).pack(side="right")
        window.after_idle(lambda:self._center_child_window(window,780,620))
        return report

    def _build_ui(self):
        header = tk.Frame(self, background="#12355B", padx=24, pady=17); header.pack(fill="x")
        identity = tk.Frame(header, background="#12355B"); identity.pack(side="left")
        ttk.Label(identity, text="SICORPA", style="Title.TLabel").pack(anchor="w")
        ttk.Label(identity, text="Système Intégré de Contrôle et de Rapprochement de la Paie", style="Subtitle.TLabel").pack(anchor="w")
        self.trial_indicator=tk.StringVar(value=self.trial_status.short_label)
        tk.Label(header,textvariable=self.trial_indicator,background="#8A4B08",foreground="white",font=("DejaVu Sans",9,"bold"),padx=12,pady=8).pack(side="right",padx=(8,0))
        tk.Label(header, text=f"●  DuckDB connecté  •  v{APP_VERSION}\n{self.config_data.database_path}", background="#0D2947", foreground="#D7E9FA", padx=14, pady=8).pack(side="right")
        self.notebook = ttk.Notebook(self); self.notebook.pack(fill="both", expand=True, padx=22, pady=(18,10))
        self.dashboard_page=ttk.Frame(self.notebook,padding=20);self.access_page=ttk.Frame(self.notebook,padding=20);self.excel_page=ttk.Frame(self.notebook,padding=20);self.match_page=ttk.Frame(self.notebook,padding=20);self.explorer_page=ttk.Frame(self.notebook,padding=20);self.admin_page=ttk.Frame(self.notebook,padding=20);self.mapping_page=ttk.Frame(self.notebook,padding=20);self.finance_page=ttk.Frame(self.notebook,padding=20)
        for page,label in [(self.dashboard_page,"  Tableau de bord  "),(self.access_page,"  1. Paie Access  "),(self.excel_page,"  2. Déclaratif Excel  "),(self.match_page,"  3. Rapprochement  "),(self.explorer_page,"  Explorer les données  "),(self.admin_page,"  Configuration  "),(self.mapping_page,"  Mapping colonnes  "),(self.finance_page,"  Calculs financiers  ")]:self.notebook.add(page,text=label)
        self._build_dashboard();self._build_access();self._build_excel();self._build_matching();self._build_explorer();self._build_admin();self._build_mapping();self._build_finance()
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
        options=["Charger uniquement une table de paie Access","Charger uniquement un déclaratif Excel","Lancer un rapprochement existant","Générer le rapport, la lettre et les annexes","Traitement complet : paie + déclaratif + rapprochement + rapport"]
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
        elif choice.startswith("Générer uniquement"):self.notebook.select(3);messagebox.showinfo("Rapport","Sélectionnez le périmètre puis cliquez sur Générer le rapport, la lettre et les annexes.")
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
                if self.config_data.regimes:var.set(next(iter(self.config_data.regimes)))
            elif key == "quarter":
                combo["values"] = ["T1", "T2", "T3", "T4"]
                var.set(f"T{((datetime.now().month-1)//3)+1}")
            elif key == "year":
                combo["values"] = list(range(datetime.now().year + 1, 2019, -1))
                var.set(str(datetime.now().year))
            else: values["institution_combo"] = combo
            frame.columnconfigure(col, weight=1)
        self._refresh_institution_combo(values["institution_combo"])
        institutions=values["institution_combo"]["values"]
        if institutions:values["institution"].set(institutions[0])
        return values

    def _build_access(self):
        self._page_heading(self.access_page,"Importer un listing de paie","Chargez la paie depuis une table Access ou un fichier Excel, puis standardisez-la dans DuckDB.")
        self.access_scope = self._common_scope(self.access_page)
        source_tabs=ttk.Notebook(self.access_page)

        access_source=ttk.Frame(source_tabs,padding=12)
        payroll_excel_source=ttk.Frame(source_tabs,padding=12)
        source_tabs.add(access_source,text="  Base Access  ")
        source_tabs.add(payroll_excel_source,text="  Listing Excel  ")

        self.access_path = tk.StringVar(); self.access_table = tk.StringVar()
        ttk.Label(access_source,text="Fichier Access (.accdb ou .mdb)").grid(row=0,column=0,sticky="w",padx=5)
        ttk.Entry(access_source,textvariable=self.access_path).grid(row=1,column=0,sticky="ew",padx=5,pady=(3,8))
        ttk.Button(access_source,text="Parcourir",command=self._choose_access).grid(row=1,column=1,padx=5,pady=(3,8))
        ttk.Label(access_source,text="Table de paie").grid(row=2,column=0,sticky="w",padx=5)
        self.table_combo=ttk.Combobox(access_source,textvariable=self.access_table,state="readonly")
        self.table_combo.grid(row=3,column=0,sticky="ew",padx=5,pady=(3,8))
        self.table_combo.bind("<<ComboboxSelected>>",lambda _event:self._autofill_table(self.access_table.get()))
        ttk.Button(access_source,text="Lister les tables",command=self._scan_access).grid(row=3,column=1,padx=5,pady=(3,8))
        self.access_load=ttk.Button(access_source,text="Charger la table sélectionnée",style="Primary.TButton",command=self._load_access)
        self.access_load.grid(row=4,column=0,columnspan=2,sticky="e",padx=5,pady=(4,0))
        access_source.columnconfigure(0,weight=1)

        self.payroll_excel_path=tk.StringVar();self.payroll_excel_sheet=tk.StringVar();self.payroll_header_row=tk.IntVar(value=1)
        ttk.Label(payroll_excel_source,text="Fichier").grid(row=0,column=0,sticky="w",padx=5)
        ttk.Entry(payroll_excel_source,textvariable=self.payroll_excel_path).grid(row=0,column=1,sticky="ew",padx=5,pady=(0,6))
        ttk.Button(payroll_excel_source,text="Parcourir",command=self._choose_payroll_excel).grid(row=0,column=2,padx=5,pady=(0,6))
        ttk.Label(payroll_excel_source,text="Feuille").grid(row=1,column=0,sticky="w",padx=5)
        self.payroll_sheet_combo=ttk.Combobox(payroll_excel_source,textvariable=self.payroll_excel_sheet,state="readonly")
        self.payroll_sheet_combo.grid(row=1,column=1,sticky="ew",padx=5,pady=(0,6))
        ttk.Label(payroll_excel_source,text="En-tête").grid(row=1,column=2,sticky="e",padx=(10,2))
        ttk.Spinbox(payroll_excel_source,from_=1,to=100,textvariable=self.payroll_header_row,width=7).grid(row=1,column=3,sticky="w",padx=5,pady=(0,6))
        payroll_actions=ttk.Frame(payroll_excel_source)
        payroll_actions.grid(row=2,column=0,columnspan=4,sticky="e",padx=5)
        ttk.Button(payroll_actions,text="Afficher l’aperçu",command=self._preview_payroll_excel).pack(side="left",padx=(0,6))
        self.payroll_excel_load=ttk.Button(payroll_actions,text="Charger le listing",style="Primary.TButton",command=self._load_payroll_excel)
        self.payroll_excel_load.pack(side="left")
        preview_frame=ttk.Frame(payroll_excel_source)
        preview_frame.grid(row=3,column=0,columnspan=4,sticky="nsew",padx=5,pady=(6,0))
        self.payroll_preview=ttk.Treeview(preview_frame,show="headings",height=5)
        preview_y=ttk.Scrollbar(preview_frame,orient="vertical",command=self.payroll_preview.yview)
        preview_x=ttk.Scrollbar(preview_frame,orient="horizontal",command=self.payroll_preview.xview)
        self.payroll_preview.configure(yscrollcommand=preview_y.set,xscrollcommand=preview_x.set)
        self.payroll_preview.grid(row=0,column=0,sticky="nsew");preview_y.grid(row=0,column=1,sticky="ns");preview_x.grid(row=1,column=0,sticky="ew")
        preview_frame.columnconfigure(0,weight=1);preview_frame.rowconfigure(0,weight=1)
        payroll_excel_source.columnconfigure(1,weight=1);payroll_excel_source.rowconfigure(3,weight=1)

        standards=ttk.LabelFrame(self.access_page,text="Champs standards acceptés pour la paie",style="Section.TLabelframe",padding=8)
        standards.pack(side="bottom",fill="x",pady=(0,4))
        columns=("field","type","description")
        self.payroll_standard_tree=ttk.Treeview(standards,columns=columns,show="headings",height=2)
        for column,title,width in [("field","Champ standard",230),("type","Type",110),("description","Utilisation",650)]:
            self.payroll_standard_tree.heading(column,text=title);self.payroll_standard_tree.column(column,width=width,anchor="w")
        accepted=[
            ("matricule_source","Texte","Matricule original de l’agent — utilisé pour le rapprochement"),
            ("nom / prenom","Texte","Identité de l’agent et rapprochement secondaire par nom"),
            ("section / categorie / grade","Texte","Classement administratif de l’agent"),
            ("unite_affectation / province","Texte","Affectation et localisation"),
            ("remuneration_base","Montant","Traitement ou rémunération de base"),
            ("transport / prime / logement","Montant","Composantes de la rémunération"),
            ("pension_rente / autres_remunerations","Montant","Autres composantes financières"),
            ("retenues / montant_net","Montant","Retenues opérées et net payé"),
            ("composante_<CODE>","Montant","Composante financière supplémentaire configurable"),
        ]
        for row in accepted:self.payroll_standard_tree.insert("","end",values=row)
        standard_y=ttk.Scrollbar(standards,orient="vertical",command=self.payroll_standard_tree.yview)
        self.payroll_standard_tree.configure(yscrollcommand=standard_y.set)
        self.payroll_standard_tree.pack(side="left",fill="x",expand=True);standard_y.pack(side="right",fill="y")
        source_tabs.pack(side="top",fill="both",expand=True,pady=8)

    def _build_excel(self):
        self._page_heading(self.excel_page,"Importer une liste déclarative","Analysez la structure, contrôlez l’aperçu puis chargez une version traçable dans DuckDB.")
        self.excel_scope = self._common_scope(self.excel_page)
        src=ttk.LabelFrame(self.excel_page,text="Chargeur de la liste déclarative",style="Section.TLabelframe",padding=10);src.pack(fill="x",pady=8)
        self.excel_path=tk.StringVar();self.excel_sheet=tk.StringVar();self.header_row=tk.IntVar(value=1)
        self.declaration_mode=tk.StringVar(value="Ajouter une nouvelle version")
        ttk.Label(src,text="1. Fichier Excel (.xlsx, .xls ou .xlsm)").grid(row=0,column=0,sticky="w",padx=5)
        ttk.Label(src,text="2. Feuille").grid(row=0,column=2,sticky="w",padx=5)
        ttk.Label(src,text="3. Ligne d’en-tête").grid(row=0,column=3,sticky="w",padx=5)
        ttk.Label(src,text="4. Mode d’importation").grid(row=0,column=4,sticky="w",padx=5)
        ttk.Entry(src,textvariable=self.excel_path).grid(row=1,column=0,sticky="ew",padx=5,pady=(3,7))
        ttk.Button(src,text="Parcourir",command=self._choose_excel).grid(row=1,column=1,padx=5,pady=(3,7))
        self.sheet_combo=ttk.Combobox(src,textvariable=self.excel_sheet,state="readonly");self.sheet_combo.grid(row=1,column=2,sticky="ew",padx=5,pady=(3,7))
        ttk.Spinbox(src,from_=1,to=100,textvariable=self.header_row,width=8).grid(row=1,column=3,sticky="ew",padx=5,pady=(3,7))
        ttk.Combobox(src,textvariable=self.declaration_mode,state="readonly",values=["Ajouter une nouvelle version","Remplacer le périmètre actuel"],width=29).grid(row=1,column=4,sticky="ew",padx=5,pady=(3,7))
        excel_actions=ttk.Frame(src)
        excel_actions.grid(row=2,column=0,columnspan=5,sticky="e",padx=5,pady=(2,4))
        ttk.Button(excel_actions,text="Analyser la structure",style="Secondary.TButton",command=self._analyze_declaration_structure).pack(side="left",padx=(0,6))
        ttk.Button(excel_actions,text="Afficher l’aperçu",command=self._preview_excel).pack(side="left",padx=(0,6))
        self.excel_load=ttk.Button(excel_actions,text="Charger le déclaratif",style="Primary.TButton",command=self._load_excel)
        self.excel_load.pack(side="left");self.excel_load.configure(state="disabled")
        src.columnconfigure(0,weight=3);src.columnconfigure(2,weight=1);src.columnconfigure(4,weight=1)

        self.declaration_tabs=ttk.Notebook(self.excel_page);self.declaration_tabs.pack(fill="both",expand=True,pady=(4,0))
        preview_tab=ttk.Frame(self.declaration_tabs,padding=8);structure_tab=ttk.Frame(self.declaration_tabs,padding=8);deletion_tab=ttk.Frame(self.declaration_tabs,padding=8)
        self.declaration_tabs.add(preview_tab,text="  Aperçu du fichier  ")
        self.declaration_tabs.add(structure_tab,text="  Structure d’importation  ")
        self.declaration_tabs.add(deletion_tab,text="  Historique et suppression  ")

        preview_frame=ttk.Frame(preview_tab);preview_frame.pack(fill="both",expand=True)
        self.preview=ttk.Treeview(preview_frame,show="headings",height=10)
        preview_y=ttk.Scrollbar(preview_frame,orient="vertical",command=self.preview.yview);preview_x=ttk.Scrollbar(preview_frame,orient="horizontal",command=self.preview.xview)
        self.preview.configure(yscrollcommand=preview_y.set,xscrollcommand=preview_x.set)
        self.preview.grid(row=0,column=0,sticky="nsew");preview_y.grid(row=0,column=1,sticky="ns");preview_x.grid(row=1,column=0,sticky="ew")
        preview_frame.columnconfigure(0,weight=1);preview_frame.rowconfigure(0,weight=1)

        self.declaration_structure_status=tk.StringVar(value="Sélectionnez un fichier puis cliquez sur Analyser la structure.")
        self.declaration_structure_status_label=tk.Label(structure_tab,textvariable=self.declaration_structure_status,background="#EAF2FB",foreground="#12355B",anchor="w",justify="left",padx=12,pady=9)
        self.declaration_structure_status_label.pack(fill="x",pady=(0,8))
        structure_frame=ttk.Frame(structure_tab);structure_frame.pack(fill="both",expand=True)
        structure_columns=("field","type","source","status","usage");self.declaration_structure_tree=ttk.Treeview(structure_frame,columns=structure_columns,show="headings",height=8)
        for column,title,width in [("field","Champ standard",190),("type","Type",90),("source","Colonne Excel reconnue",220),("status","État",155),("usage","Utilisation",430)]:
            self.declaration_structure_tree.heading(column,text=title);self.declaration_structure_tree.column(column,width=width,anchor="w",stretch=column=="usage")
        structure_y=ttk.Scrollbar(structure_frame,orient="vertical",command=self.declaration_structure_tree.yview);structure_x=ttk.Scrollbar(structure_frame,orient="horizontal",command=self.declaration_structure_tree.xview)
        self.declaration_structure_tree.configure(yscrollcommand=structure_y.set,xscrollcommand=structure_x.set)
        self.declaration_structure_tree.grid(row=0,column=0,sticky="nsew");structure_y.grid(row=0,column=1,sticky="ns");structure_x.grid(row=1,column=0,sticky="ew")
        structure_frame.columnconfigure(0,weight=1);structure_frame.rowconfigure(0,weight=1)
        self.declaration_structure_tree.tag_configure("ok",foreground="#166534");self.declaration_structure_tree.tag_configure("warning",foreground="#9A6700");self.declaration_structure_tree.tag_configure("error",foreground="#A11D1D")
        structure_actions=ttk.Frame(structure_tab);structure_actions.pack(fill="x",pady=(7,0))
        ttk.Label(structure_actions,text="Le type de source à configurer est EXCEL.").pack(side="left")
        ttk.Button(structure_actions,text="Ouvrir Mapping colonnes",style="Secondary.TButton",command=lambda:self.notebook.select(self.mapping_page)).pack(side="right")

        warning=tk.Label(deletion_tab,text="ZONE DE SUPPRESSION — seuls les imports non utilisés par un traitement peuvent être supprimés.",background="#FFF4E5",foreground="#8A4B08",anchor="w",padx=12,pady=9,font=("DejaVu Sans",9,"bold"));warning.pack(fill="x",pady=(0,8))
        history_frame=ttk.Frame(deletion_tab);history_frame.pack(fill="both",expand=True)
        history_columns=("institution","regime","period","file","sheet","rows","state","usage","date");self.declaration_history_tree=ttk.Treeview(history_frame,columns=history_columns,show="headings",height=8,selectmode="browse")
        for column,title,width in [("institution","Institution",210),("regime","Régime",120),("period","Période",90),("file","Fichier",230),("sheet","Feuille",120),("rows","Lignes",85),("state","État",115),("usage","Utilisation",170),("date","Importé le",145)]:
            self.declaration_history_tree.heading(column,text=title);self.declaration_history_tree.column(column,width=width,anchor="e" if column=="rows" else "w",stretch=column in {"institution","file","usage"})
        history_y=ttk.Scrollbar(history_frame,orient="vertical",command=self.declaration_history_tree.yview);history_x=ttk.Scrollbar(history_frame,orient="horizontal",command=self.declaration_history_tree.xview)
        self.declaration_history_tree.configure(yscrollcommand=history_y.set,xscrollcommand=history_x.set)
        self.declaration_history_tree.grid(row=0,column=0,sticky="nsew");history_y.grid(row=0,column=1,sticky="ns");history_x.grid(row=1,column=0,sticky="ew")
        history_frame.columnconfigure(0,weight=1);history_frame.rowconfigure(0,weight=1)
        deletion_actions=ttk.Frame(deletion_tab);deletion_actions.pack(fill="x",pady=(7,0))
        ttk.Button(deletion_actions,text="Actualiser",style="Secondary.TButton",command=self._refresh_declaration_imports).pack(side="left")
        ttk.Button(deletion_actions,text="Supprimer l’import sélectionné",command=self._delete_declaration_import).pack(side="right")
        self._refresh_declaration_imports()
        for variable in [self.excel_scope["institution"],self.excel_scope["regime"],self.excel_scope["quarter"],self.excel_scope["year"]]:
            variable.trace_add("write",lambda *_args:self.after_idle(self._refresh_declaration_imports))
        self.sheet_combo.bind("<<ComboboxSelected>>",lambda _event:self._invalidate_declaration_structure())
        self.header_row.trace_add("write",lambda *_args:self.after_idle(self._invalidate_declaration_structure))
        self.excel_scope["regime"].trace_add("write",lambda *_args:self.after_idle(self._invalidate_declaration_structure))
        self._invalidate_declaration_structure()

    def _build_matching(self):
        self._page_heading(self.match_page,"Rapprochement et restitution","Exécutez le contrôle institutionnel ou constituez une analyse transversale de plusieurs régimes.")
        matching_tabs=self.matching_tabs=ttk.Notebook(self.match_page)
        matching_tabs.pack(fill="both",expand=True,pady=(6,0))
        standard_tab=self.standard_matching_tab=ttk.Frame(matching_tabs)
        multi_tab=ttk.Frame(matching_tabs,padding=12)
        listing_tab=ttk.Frame(matching_tabs,padding=12)
        report_tab=ttk.Frame(matching_tabs,padding=12)
        matching_tabs.add(standard_tab,text="  Traitement institutionnel  ")
        matching_tabs.add(multi_tab,text="  Analyse multi-régimes  ")
        matching_tabs.add(listing_tab,text="  Analyse groupée des listings  ")
        matching_tabs.add(report_tab,text="  Listing + annexes & rapport  ")
        buttons=ttk.Frame(standard_tab,padding=(12,7,12,10));buttons.pack(side="bottom",fill="x")
        self.match_button=ttk.Button(buttons,text="Lancer le rapprochement",style="Primary.TButton",command=self._run_matching);self.match_button.pack(side="right",padx=5)
        ttk.Button(buttons,text="Générer le rapport, la lettre et les annexes",style="Secondary.TButton",command=self._export_report).pack(side="right",padx=5)
        standard_body=self.standard_matching_body=self._scrollable_dialog_body(standard_tab,padding=12)

        self.match_scope=self._common_scope(standard_body)
        self.match_scope["institution_combo"].bind("<<ComboboxSelected>>",lambda _e:self._matching_scope_changed())
        self.match_scope["regime_combo"].bind("<<ComboboxSelected>>",lambda _e:self._matching_scope_changed())
        self.match_scope["quarter"].trace_add("write",lambda *_args:self.after_idle(self._refresh_matching_formula_choices))
        self.match_scope["year"].trace_add("write",lambda *_args:self.after_idle(self._refresh_matching_formula_choices))
        filtres=ttk.LabelFrame(standard_body,text="Filtres métier du listing — appliqués avant toute comparaison",style="Section.TLabelframe",padding=12);filtres.pack(fill="x",pady=8)
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
        info=ttk.LabelFrame(standard_body,text="Règles du traitement",style="Section.TLabelframe",padding=10);info.pack(fill="x",pady=4)
        ttk.Label(info,text="Les filtres sont combinés avec ET. NU / N.U est traité comme matricule non exploitable et exclu des doublons.").pack(anchor="w")
        impact=ttk.LabelFrame(standard_body,text="Calcul de l’impact",style="Section.TLabelframe",padding=10);impact.pack(fill="x",pady=4)
        self.match_impact_mode=tk.StringVar(value=IMPACT_MODE_AUTO)
        self.match_formula_choice=tk.StringVar();self.match_formula_ids={}
        ttk.Label(impact,text="Mode de calcul").grid(row=0,column=0,sticky="w",padx=4)
        ttk.Label(impact,text="Version de formule").grid(row=0,column=1,sticky="w",padx=4)
        mode_combo=ttk.Combobox(impact,textvariable=self.match_impact_mode,state="readonly",
            values=[IMPACT_MODE_AUTO,IMPACT_MODE_SELECTED],width=38)
        mode_combo.grid(row=1,column=0,sticky="ew",padx=4)
        mode_combo.bind("<<ComboboxSelected>>",lambda _e:self._impact_mode_changed())
        self.match_formula_combo=ttk.Combobox(impact,textvariable=self.match_formula_choice,
            state="disabled",width=54)
        self.match_formula_combo.grid(row=1,column=1,sticky="ew",padx=4)
        self.match_formula_combo.bind("<<ComboboxSelected>>",lambda _e:self._update_matching_formula_status())
        ttk.Button(impact,text="Configurer les formules",style="Secondary.TButton",
            command=self._open_finance_configuration).grid(row=1,column=2,padx=4)
        self.match_formula_status=tk.StringVar(value="Résolution automatique selon le régime et la rubrique.")
        ttk.Label(impact,textvariable=self.match_formula_status,style="PageHint.TLabel",
            wraplength=980).grid(row=2,column=0,columnspan=3,sticky="w",padx=4,pady=(6,0))
        impact.columnconfigure(0,weight=1);impact.columnconfigure(1,weight=2)
        self._refresh_matching_formula_choices()

        self._build_multi_matching(multi_tab)
        self._build_listing_analysis(listing_tab)
        self._build_listing_reporting(report_tab)

    def _build_listing_reporting(self,parent):
        title = ttk.LabelFrame(parent, text="Rapport final à partir d’un groupe de listings", style="Section.TLabelframe", padding=12)
        title.pack(fill="both", expand=True)

        self.listing_report_group = tk.StringVar()
        ttk.Label(title, text="Groupe analytique disponible").grid(row=0, column=0, sticky="w", padx=4, pady=(0, 4))
        self.listing_report_group_combo = ttk.Combobox(title, textvariable=self.listing_report_group, state="readonly", width=60)
        self.listing_report_group_combo.grid(row=1, column=0, sticky="ew", padx=4)
        title.columnconfigure(0, weight=1)

        actions = ttk.Frame(title)
        actions.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        ttk.Button(actions, text="Actualiser les groupes", style="Secondary.TButton", command=self._refresh_listing_reporting_groups).pack(side="left")
        ttk.Button(actions, text="Utiliser le dernier groupe", style="Secondary.TButton", command=self._use_last_listing_group).pack(side="left", padx=6)
        ttk.Button(actions, text="Générer rapport, annexes et lettre", style="Primary.TButton", command=self._run_listing_reporting_export).pack(side="right")

        info = ttk.LabelFrame(parent, text="Informations", style="Section.TLabelframe", padding=12)
        info.pack(fill="x", pady=(10, 0))
        self.listing_report_status = tk.StringVar(value="Sélectionnez un groupe de listings puis générez les livrables.")
        ttk.Label(info, textvariable=self.listing_report_status, style="PageHint.TLabel", wraplength=900, justify="left").pack(anchor="w")

        self._refresh_listing_reporting_groups()

    def _refresh_listing_reporting_groups(self):
        values = []
        for group_id, name, quarter, year, status, rows, created, terminated, folder, archived in self.listing_analysis.list_groups(include_archived=False):
            label = f"{name} — {quarter} {year} — {status}"
            values.append((group_id, label))
        if self.listing_report_group_combo.winfo_exists():
            self.listing_report_group_combo["values"] = [label for _, label in values]
        if self.listing_last_group and self.listing_last_group in [group_id for group_id, _ in values]:
            self.listing_report_group.set(next(label for group_id, label in values if group_id == self.listing_last_group))
        elif values:
            self.listing_report_group.set(values[0][1])
        else:
            self.listing_report_group.set("")
            self.listing_report_status.set("Aucun groupe de listings disponible pour la génération d’annexes et de rapport.")

    def _use_last_listing_group(self):
        if not self.listing_last_group:
            self.listing_report_status.set("Aucun groupe récent n’a encore été analysé.")
            return
        self._refresh_listing_reporting_groups()
        for group_id, label in [(group_id, label) for group_id, label in [(gid, lab) for gid, lab in []]]:
            pass
        candidates = self.listing_analysis.list_groups(include_archived=False)
        for group_id, name, quarter, year, status, rows, created, terminated, folder, archived in candidates:
            if group_id == self.listing_last_group:
                self.listing_report_group.set(f"{name} — {quarter} {year} — {status}")
                self.listing_report_status.set(f"Groupe courant restauré : {name} ({quarter} {year}).")
                return
        self.listing_report_status.set("Le dernier groupe n’est plus disponible dans l’historique.")

    def _run_listing_reporting_export(self):
        selected = self.listing_report_group.get().strip()
        group_id = None
        for candidate_id, candidate_label in [
            (gid, label) for gid, label in [
                (group_id_value, label_value)
                for group_id_value, name, quarter, year, status, rows, created, terminated, folder, archived in self.listing_analysis.list_groups(include_archived=False)
                for label_value in [f"{name} — {quarter} {year} — {status}"]
            ]
        ]:
            if candidate_label == selected:
                group_id = candidate_id
                break

        if not group_id:
            if self.listing_last_group:
                group_id = self.listing_last_group
            else:
                messagebox.showwarning("Génération impossible", "Sélectionnez un groupe de listings ou lancez d’abord une analyse.")
                return

        folder = filedialog.askdirectory(title="Choisir le dossier de destination du rapport et des annexes")
        if not folder:
            return

        self._open_generation_dialog("Rapport et annexes du groupe de listings",
            "Production progressive du rapport, des annexes détaillées, des effectifs et de la lettre d’interprétation.",
            "Fichiers générés", True)
        self._background(lambda:self.listing_analysis.export(group_id, folder, progress=self._progress), self._listing_export_completed)

    def _build_multi_matching(self,parent):
        body=self._scrollable_dialog_body(parent,padding=12)
        selection=ttk.LabelFrame(body,text="Déclaratif et période commune",style="Section.TLabelframe",padding=10)
        selection.grid(row=0,column=0,sticky="ew",pady=(0,8))
        self.multi_institution=tk.StringVar();self.multi_regime=tk.StringVar()
        self.multi_quarter=tk.StringVar(value="T1");self.multi_year=tk.StringVar(value=str(datetime.now().year))
        fields=[("Institution déclarative",self.multi_institution),("Régime déclaratif",self.multi_regime),
                ("Trimestre",self.multi_quarter),("Année",self.multi_year)]
        for col,(label,var) in enumerate(fields):
            ttk.Label(selection,text=label).grid(row=0,column=col,sticky="w",padx=4)
            if col==0:
                widget=self.multi_institution_combo=ttk.Combobox(selection,textvariable=var,state="readonly")
                self._refresh_institution_combo(widget)
            elif col==1:
                widget=self.multi_regime_combo=ttk.Combobox(selection,textvariable=var,state="readonly",values=list(self.config_data.regimes))
            elif col==2:widget=ttk.Combobox(selection,textvariable=var,state="readonly",values=["T1","T2","T3","T4"])
            else:widget=ttk.Combobox(selection,textvariable=var,state="readonly",values=list(range(datetime.now().year+1,2019,-1)))
            widget.grid(row=1,column=col,sticky="ew",padx=4)
            selection.columnconfigure(col,weight=1)
        ttk.Button(selection,text="Rechercher les données de la période",style="Primary.TButton",
                   command=self._refresh_multi_sources).grid(row=1,column=4,padx=6)
        ttk.Label(selection,text="Déclaratif").grid(row=2,column=0,sticky="w",padx=4,pady=(8,0))
        self.multi_declaration=tk.StringVar()
        self.multi_declaration_combo=ttk.Combobox(selection,textvariable=self.multi_declaration,state="readonly")
        self.multi_declaration_combo.grid(row=2,column=1,columnspan=3,sticky="ew",padx=4,pady=(8,0))
        ttk.Button(selection,text="Historique des campagnes",style="Secondary.TButton",
                   command=self._open_multi_history).grid(row=2,column=4,padx=6,pady=(8,0))
        self.multi_declaration_ids={}

        sources=ttk.LabelFrame(body,text="Listings disponibles — sélection multiple",style="Section.TLabelframe",padding=8)
        sources.grid(row=1,column=0,sticky="nsew",pady=4)
        columns=("selected","institution","regime","table","available","retained","filters","formula","diagnostic","file")
        self.multi_source_tree=ttk.Treeview(sources,columns=columns,show="headings",height=7,selectmode="extended")
        specs=[("selected","Utiliser",65),("institution","Institution",220),("regime","Régime",145),
               ("table","Table / feuille",210),("available","Disponibles",95),("retained","Après filtres",95),
               ("filters","Filtres",190),("formula","Formule d’impact",200),
               ("diagnostic","Diagnostic",190),("file","Fichier source",240)]
        for column,title,width in specs:
            self.multi_source_tree.heading(column,text=title);self.multi_source_tree.column(column,width=width,anchor="w")
        sy=ttk.Scrollbar(sources,orient="vertical",command=self.multi_source_tree.yview)
        sx=ttk.Scrollbar(sources,orient="horizontal",command=self.multi_source_tree.xview)
        self.multi_source_tree.configure(yscrollcommand=sy.set,xscrollcommand=sx.set)
        self.multi_source_tree.grid(row=0,column=0,sticky="nsew");sy.grid(row=0,column=1,sticky="ns");sx.grid(row=1,column=0,sticky="ew")
        self.multi_source_tree.bind("<Double-1>",self._toggle_multi_source)
        sources.columnconfigure(0,weight=1);sources.rowconfigure(0,weight=1)
        source_actions=ttk.Frame(sources);source_actions.grid(row=2,column=0,columnspan=2,sticky="ew",pady=(6,0))
        ttk.Button(source_actions,text="Sélectionner les lignes choisies",
                   command=lambda:self._set_chosen_multi_sources(True)).pack(side="left")
        ttk.Button(source_actions,text="Désélectionner les lignes choisies",
                   command=lambda:self._set_chosen_multi_sources(False)).pack(side="left",padx=6)
        ttk.Button(source_actions,text="Tout sélectionner",
                   command=lambda:self._set_all_multi_sources(True)).pack(side="left")
        ttk.Button(source_actions,text="Tout désélectionner",
                   command=lambda:self._set_all_multi_sources(False)).pack(side="left",padx=6)
        ttk.Button(source_actions,text="Aperçu après filtres existants",style="Secondary.TButton",
                   command=self._preview_multi_sources).pack(side="right")
        ttk.Button(source_actions,text="Voir un échantillon",command=self._show_multi_source_sample).pack(side="right",padx=6)
        ttk.Button(source_actions,text="Modifier ses filtres",command=self._edit_selected_source_filters).pack(side="right")

        results=ttk.LabelFrame(body,text="Synthèse de la dernière analyse",style="Section.TLabelframe",padding=8)
        results.grid(row=2,column=0,sticky="ew",pady=4)
        columns=("status","records","people","mass","impact")
        self.multi_result_tree=ttk.Treeview(results,columns=columns,show="headings",height=2)
        for column,title,width in [("status","Catégorie",330),("records","Enregistrements",115),
                ("people","Concernés",105),("mass","Masse",130),("impact","Impact potentiel",145)]:
            self.multi_result_tree.heading(column,text=title);self.multi_result_tree.column(column,width=width,anchor="w")
        self.multi_result_tree.pack(fill="x",expand=True)
        actions=ttk.Frame(body);actions.grid(row=3,column=0,sticky="ew",pady=(8,0))
        body.columnconfigure(0,weight=1);body.rowconfigure(1,weight=1)
        self.multi_status=tk.StringVar(value="Choisissez la période puis recherchez les sources.")
        ttk.Label(actions,textvariable=self.multi_status,style="PageHint.TLabel").pack(side="left")
        self.multi_export_button=ttk.Button(actions,text="Exporter le rapport et l’annexe",state="disabled",
            style="Secondary.TButton",command=self._export_multi_analysis)
        self.multi_export_button.pack(side="right",padx=5)
        ttk.Button(actions,text="Lancer l’analyse multi-régimes",style="Primary.TButton",
                   command=self._run_multi_analysis).pack(side="right",padx=5)
        self.multi_selected_sources=set();self.multi_last_campaign="";self.multi_diagnosis=None

    def _build_listing_analysis(self,parent):
        body=self._scrollable_dialog_body(parent,padding=12)
        period=ttk.LabelFrame(body,text="Groupe analytique et période commune",style="Section.TLabelframe",padding=10)
        period.grid(row=0,column=0,sticky="ew",pady=(0,6))
        self.listing_group_name=tk.StringVar(value=f"Analyse listings {datetime.now().year}")
        self.listing_quarter=tk.StringVar(value="T1");self.listing_year=tk.StringVar(value=str(datetime.now().year))
        for col,(label,var,values) in enumerate([
                ("Nom du groupe",self.listing_group_name,None),
                ("Trimestre",self.listing_quarter,["T1","T2","T3","T4"]),
                ("Année",self.listing_year,list(range(datetime.now().year+1,2019,-1)))]):
            ttk.Label(period,text=label).grid(row=0,column=col,sticky="w",padx=4)
            widget=(ttk.Entry(period,textvariable=var) if values is None else
                    ttk.Combobox(period,textvariable=var,state="readonly",values=values))
            widget.grid(row=1,column=col,sticky="ew",padx=4);period.columnconfigure(col,weight=2 if col==0 else 1)
        ttk.Button(period,text="Rechercher les listings",style="Primary.TButton",
                   command=self._refresh_listing_sources).grid(row=1,column=3,padx=5)
        ttk.Button(period,text="Historique",style="Secondary.TButton",
                   command=self._open_listing_history).grid(row=1,column=4,padx=5)

        sources=ttk.LabelFrame(body,text="Listings à regrouper — aucune liste déclarative requise",style="Section.TLabelframe",padding=8)
        sources.grid(row=1,column=0,sticky="nsew",pady=4)
        columns=("selected","institution","regime","table","available","retained","filters","diagnostic","file")
        self.listing_source_tree=ttk.Treeview(sources,columns=columns,show="headings",height=7,selectmode="extended")
        for column,title,width in [
                ("selected","Utiliser",65),("institution","Institution",220),("regime","Régime",135),
                ("table","Table / feuille",190),("available","Disponibles",90),("retained","Retenues",90),
                ("filters","Filtres appliqués",230),("diagnostic","Diagnostic",180),("file","Fichier",220)]:
            self.listing_source_tree.heading(column,text=title)
            self.listing_source_tree.column(column,width=width,anchor="w",stretch=column in {"institution","filters"})
        sy=ttk.Scrollbar(sources,orient="vertical",command=self.listing_source_tree.yview)
        sx=ttk.Scrollbar(sources,orient="horizontal",command=self.listing_source_tree.xview)
        self.listing_source_tree.configure(yscrollcommand=sy.set,xscrollcommand=sx.set)
        self.listing_source_tree.grid(row=0,column=0,sticky="nsew");sy.grid(row=0,column=1,sticky="ns");sx.grid(row=1,column=0,sticky="ew")
        self.listing_source_tree.bind("<Double-1>",self._toggle_listing_source)
        sources.columnconfigure(0,weight=1);sources.rowconfigure(0,weight=1)
        buttons=ttk.Frame(sources);buttons.grid(row=2,column=0,columnspan=2,sticky="ew",pady=(6,0))
        ttk.Button(buttons,text="Sélectionner les lignes",command=lambda:self._set_chosen_listing_sources(True)).pack(side="left")
        ttk.Button(buttons,text="Désélectionner les lignes",command=lambda:self._set_chosen_listing_sources(False)).pack(side="left",padx=5)
        ttk.Button(buttons,text="Tout sélectionner",command=lambda:self._set_all_listing_sources(True)).pack(side="left")
        ttk.Button(buttons,text="Tout désélectionner",command=lambda:self._set_all_listing_sources(False)).pack(side="left",padx=5)
        ttk.Button(buttons,text="Vérifier le groupe",style="Secondary.TButton",command=self._preview_listing_sources).pack(side="right")
        ttk.Button(buttons,text="Voir un échantillon",command=self._show_listing_source_sample).pack(side="right",padx=5)
        ttk.Button(buttons,text="Modifier ses filtres",command=self._edit_listing_source_filters).pack(side="right")

        results=ttk.LabelFrame(body,text="Synthèse de la dernière analyse",style="Section.TLabelframe",padding=8)
        results.grid(row=2,column=0,sticky="ew",pady=4)
        columns=("status","records","people","mass","impact")
        self.listing_result_tree=ttk.Treeview(results,columns=columns,show="headings",height=3)
        for column,title,width in [("status","Catégorie",330),("records","Enregistrements",115),
                ("people","Concernés uniques",125),("mass","Masse financière",145),("impact","Impact potentiel",145)]:
            self.listing_result_tree.heading(column,text=title);self.listing_result_tree.column(column,width=width,anchor="w")
        self.listing_result_tree.pack(fill="x",expand=True)

        regime_panel=ttk.LabelFrame(body,text="Comparaison par régime",style="Section.TLabelframe",padding=8)
        regime_panel.grid(row=3,column=0,sticky="ew",pady=(6,0))
        regime_columns=("regime","status","records","people","mass","impact")
        self.listing_regime_summary_tree=ttk.Treeview(regime_panel,columns=regime_columns,show="headings",height=4)
        for column,title,width in [("regime","Régime",140),("status","Catégorie",250),("records","Enregistrements",110),
                ("people","Concernés",110),("mass","Masse",130),("impact","Impact",130)]:
            self.listing_regime_summary_tree.heading(column,text=title);self.listing_regime_summary_tree.column(column,width=width,anchor="w")
        self.listing_regime_summary_tree.pack(fill="x",expand=True)

        actions=ttk.Frame(body);actions.grid(row=4,column=0,sticky="ew",pady=(6,0))
        self.listing_status=tk.StringVar(value="Choisissez une période puis recherchez les listings.")
        ttk.Label(actions,textvariable=self.listing_status,style="PageHint.TLabel").pack(side="left")
        self.listing_export_button=ttk.Button(actions,text="Exporter rapport, annexes et lettre",state="disabled",
            style="Secondary.TButton",command=self._export_listing_analysis);self.listing_export_button.pack(side="right",padx=5)
        ttk.Button(actions,text="Constituer la base et analyser",style="Primary.TButton",
                   command=self._run_listing_analysis).pack(side="right",padx=5)
        body.columnconfigure(0,weight=1);body.rowconfigure(1,weight=1)
        self.listing_selected_sources=set();self.listing_last_group="";self.listing_diagnosis=None

    def _refresh_listing_regime_summary(self,group_id: str | None = None):
        if not hasattr(self, "listing_regime_summary_tree") or not self.listing_regime_summary_tree.winfo_exists():
            return
        self.listing_regime_summary_tree.delete(*self.listing_regime_summary_tree.get_children())
        if not group_id:
            return
        for regime,status,records,people,mass,impact in self.listing_analysis.inter_regime_summary(group_id):
            self.listing_regime_summary_tree.insert("","end",values=(
                regime,status,records,people,f"{mass:,.2f}".replace(","," "),f"{impact:,.2f}".replace(","," ")))

    def _build_admin(self):
        self._page_heading(self.admin_page,"Configuration métier","Gérez les institutions et ajoutez des régimes sans modifier le code.")
        institution=ttk.LabelFrame(self.admin_page,text="Institutions",style="Section.TLabelframe",padding=12);institution.pack(fill="x",pady=(0,12))
        self.inst_code=tk.StringVar();self.inst_name=tk.StringVar()
        ttk.Label(institution,text="Code").grid(row=0,column=0,sticky="w");ttk.Entry(institution,textvariable=self.inst_code).grid(row=1,column=0,sticky="ew",padx=(0,8))
        ttk.Label(institution,text="Nom officiel affiché").grid(row=0,column=1,sticky="w");ttk.Entry(institution,textvariable=self.inst_name).grid(row=1,column=1,sticky="ew")
        ttk.Button(institution,text="Ajouter l’institution",style="Primary.TButton",command=self._add_institution).grid(row=1,column=2,padx=8)
        ttk.Button(institution,text="Supprimer l’institution",style="Secondary.TButton",command=self._delete_institution).grid(row=1,column=3,padx=(0,8));institution.columnconfigure(1,weight=1)
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
        ttk.Button(actions,text="Supprimer le régime",style="Secondary.TButton",command=self._delete_regime).pack(side="right",padx=4)
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

    def _delete_regime(self):
        selected=self.regime_tree.selection()
        if not selected:return
        code=self.regime_tree.item(selected[0],"values")[0]
        if messagebox.askyesno("Supprimer le régime","Supprimer ce régime et ses mappings associés ?"):
            self.db.delete_regime(code)
            self._sync_regimes_from_database();self._refresh_all_regimes();self._refresh_regime_tree();self._clear_regime_form();

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

        delete_scope=ttk.LabelFrame(self.explorer_page,text="Suppression d’un périmètre",style="Section.TLabelframe",padding=12);delete_scope.pack(fill="x",pady=(0,10))
        self.explorer_delete_institution=tk.StringVar();self.explorer_delete_regime=tk.StringVar();self.explorer_delete_quarter=tk.StringVar(value="T1");self.explorer_delete_year=tk.StringVar(value=str(datetime.now().year))
        for col,(label,var) in enumerate([("Institution",self.explorer_delete_institution),("Régime",self.explorer_delete_regime),("Trimestre",self.explorer_delete_quarter),("Année",self.explorer_delete_year)]):
            ttk.Label(delete_scope,text=label).grid(row=0,column=col,sticky="w",padx=4)
            combo=ttk.Combobox(delete_scope,textvariable=var,state="readonly")
            combo.grid(row=1,column=col,sticky="ew",padx=4)
            if label=="Institution":
                self._refresh_institution_combo(combo);combo.set(combo["values"][0] if combo["values"] else "")
            elif label=="Régime":
                combo["values"]=list(self.config_data.regimes);combo.set(next(iter(self.config_data.regimes),""))
            elif label=="Trimestre":combo["values"]=["T1","T2","T3","T4"];combo.set(self.explorer_delete_quarter.get())
            else:combo["values"]=list(range(datetime.now().year+1,2019,-1));combo.set(str(datetime.now().year))
        ttk.Button(delete_scope,text="Supprimer ce périmètre",style="Primary.TButton",command=self._delete_explorer_scope).grid(row=1,column=4,padx=4,sticky="ew")
        delete_scope.columnconfigure(0,weight=1);delete_scope.columnconfigure(1,weight=1);delete_scope.columnconfigure(2,weight=1);delete_scope.columnconfigure(3,weight=1);delete_scope.columnconfigure(4,weight=1)

        result=ttk.LabelFrame(self.explorer_page,text="Résultats",style="Section.TLabelframe",padding=8);result.pack(fill="both",expand=True)
        table_frame=ttk.Frame(result);table_frame.pack(fill="both",expand=True)
        self.explorer_tree=ttk.Treeview(table_frame,show="headings")
        yscroll=ttk.Scrollbar(table_frame,orient="vertical",command=self.explorer_tree.yview);xscroll=ttk.Scrollbar(table_frame,orient="horizontal",command=self.explorer_tree.xview)
        self.explorer_tree.configure(yscrollcommand=yscroll.set,xscrollcommand=xscroll.set);self.explorer_tree.grid(row=0,column=0,sticky="nsew");yscroll.grid(row=0,column=1,sticky="ns");xscroll.grid(row=1,column=0,sticky="ew");table_frame.rowconfigure(0,weight=1);table_frame.columnconfigure(0,weight=1)
        self.explorer_tree.bind("<MouseWheel>",self._scroll_explorer)
        self.explorer_tree.bind("<Button-4>",self._scroll_explorer)
        self.explorer_tree.bind("<Button-5>",self._scroll_explorer)
        actions=ttk.Frame(result);actions.pack(fill="x",pady=(8,0));self.explorer_count=tk.StringVar(value="Aucune donnée affichée");ttk.Label(actions,textvariable=self.explorer_count).pack(side="left")
        ttk.Button(actions,text="Page précédente",style="Secondary.TButton",command=lambda:self._change_explorer_page(-1)).pack(side="right",padx=3);ttk.Button(actions,text="Page suivante",style="Secondary.TButton",command=lambda:self._change_explorer_page(1)).pack(side="right",padx=3);ttk.Button(actions,text="Supprimer les lignes filtrées",style="Secondary.TButton",command=self._delete_explorer_rows).pack(side="right",padx=3);ttk.Button(actions,text="Exporter cette sélection",style="Secondary.TButton",command=self._export_explorer).pack(side="right",padx=3);ttk.Button(actions,text="Réinitialiser les résultats",style="Secondary.TButton",command=self._reset_explorer_results).pack(side="right",padx=3)

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
        self._background(lambda:self.explorer.read(**filters),self._display_explorer_data,
                         operation="Lecture des données DuckDB")

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

    def _delete_explorer_scope(self):
        institution_name=self.explorer_delete_institution.get().strip(); regime=self.explorer_delete_regime.get().strip(); quarter=self.explorer_delete_quarter.get().strip(); year=self.explorer_delete_year.get().strip()
        if not all([institution_name,regime,quarter,year]):
            messagebox.showwarning("Suppression", "Sélectionnez une institution, un régime, un trimestre et une année.")
            return
        institution_id=self.institution_ids_by_name.get(institution_name)
        if not institution_id:
            messagebox.showwarning("Suppression", "Institution introuvable dans la base.")
            return
        if not messagebox.askyesno("Supprimer le périmètre", f"Supprimer toutes les données standardisées de {institution_name} — {regime} — {quarter} {year} ?\n\nCette action efface la paie, le déclaratif et les rapprochements de ce périmètre."):
            return
        try:
            deleted=self.explorer.delete_scope(institution_id,regime,quarter,year)
        except ValueError as exc:
            messagebox.showwarning("Suppression", str(exc));return
        messagebox.showinfo("Supprimer le périmètre", f"Données supprimées : {deleted['paie_rows']} ligne(s) de paie, {deleted['declaratif_rows']} ligne(s) de déclaratif, {deleted['matching_rows']} rapprochement(s).")
        self._refresh_dashboard();self._read_existing_data()

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
        if target:self._background(lambda:self.explorer.export(target,**filters),
            lambda path:messagebox.showinfo("Export",f"Données exportées :\n{path}"),
            operation="Export des données explorées")

    def _delete_explorer_rows(self):
        try:filters=self._explorer_filters()
        except ValueError as exc:messagebox.showwarning("Suppression",str(exc));return
        table=filters["table"]
        if not table:
            messagebox.showwarning("Suppression","Sélectionnez une table avant de supprimer des lignes.");return
        if not table.startswith("raw_"):
            messagebox.showwarning("Suppression","La suppression ne s’applique qu’aux tables RAW sélectionnées (raw_*).");return
        if not filters["column"] or not filters["operator"]:
            messagebox.showwarning("Suppression","Choisissez une colonne et un opérateur pour appliquer le filtre de suppression sur le RAW sélectionné.");return
        if not messagebox.askyesno("Supprimer les lignes filtrées",f"Supprimer les lignes de la table {table} correspondant au filtre actuel ?"):
            return
        try:
            deleted=self.explorer.delete_rows(
                table,
                filters["column"],
                filters["operator"],
                filters["value"],
            )
        except ValueError as exc:
            messagebox.showwarning("Suppression",str(exc));return
        messagebox.showinfo("Suppression",f"{deleted} ligne(s) supprimée(s) dans la table {table}.")
        self._read_existing_data()

    def _build_mapping(self):
        self._page_heading(self.mapping_page,"Mapping des colonnes","Associez les colonnes propres à chaque régime au schéma analytique standard.")
        panel=ttk.LabelFrame(self.mapping_page,text="Nouvelle correspondance",style="Section.TLabelframe",padding=14);panel.pack(fill="x",pady=(0,12))
        self.map_regime=tk.StringVar();self.map_source_type=tk.StringVar(value="ACCESS");self.map_source_column=tk.StringVar();self.map_target_column=tk.StringVar();self.map_required=tk.BooleanVar(value=False)
        targets=["matricule_source","nom","prenom","section","categorie","grade","service","unite_affectation","province","remuneration_base","transport","prime","logement","pension_rente","autres_remunerations","retenues","montant_net","remuneration_declaree","statut_agent"]+[f"composante_{row[0]}" for row in self.db.list_financial_components() if not row[3]]
        fields=[("Régime",self.map_regime),("Type de source",self.map_source_type),("Colonne dans le fichier",self.map_source_column),("Colonne standard",self.map_target_column)]
        for col,(label,var) in enumerate(fields):
            ttk.Label(panel,text=label).grid(row=0,column=col,sticky="w",padx=5)
            if col==0:
                widget=self.map_regime_combo=ttk.Combobox(panel,textvariable=var,state="readonly",values=list(self.config_data.regimes))
            elif col==1:
                widget=self.map_source_combo=ttk.Combobox(panel,textvariable=var,state="readonly",values=["ACCESS","PAIE_EXCEL","EXCEL"])
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

    def _build_finance(self):
        self._page_heading(self.finance_page,"Calculs financiers","Configurez les composantes et versionnez les formules d’impact sans saisir de SQL.")
        catalog=ttk.LabelFrame(self.finance_page,text="Catalogue des composantes",style="Section.TLabelframe",padding=10);catalog.pack(fill="x",pady=(0,10))
        self.component_code=tk.StringVar();self.component_label=tk.StringVar()
        ttk.Label(catalog,text="Code technique").grid(row=0,column=0,sticky="w",padx=4);ttk.Label(catalog,text="Libellé").grid(row=0,column=1,sticky="w",padx=4)
        ttk.Entry(catalog,textvariable=self.component_code).grid(row=1,column=0,sticky="ew",padx=4);ttk.Entry(catalog,textvariable=self.component_label).grid(row=1,column=1,sticky="ew",padx=4)
        ttk.Button(catalog,text="Ajouter la composante",style="Secondary.TButton",command=self._add_financial_component).grid(row=1,column=2,padx=4)
        ttk.Button(catalog,text="Supprimer la composante",style="Secondary.TButton",command=self._delete_financial_component).grid(row=1,column=3,padx=4);catalog.columnconfigure(1,weight=1)
        default_box=ttk.LabelFrame(self.finance_page,text="Formule SICORPA par défaut",style="Section.TLabelframe",padding=10);default_box.pack(fill="x",pady=(0,10))
        default_formula=self.db.default_impact_formula();default_labels={row[0]:row[1] for row in self.db.list_financial_components()}
        default_expression=" + ".join(default_labels.get(term["code"],term["code"]) for term in default_formula["terms"])
        self.default_formula_text=tk.StringVar(value=f"{default_expression}  •  Agrégation : toutes les lignes  •  Version système {default_formula['version']}")
        ttk.Label(default_box,textvariable=self.default_formula_text,style="PageHint.TLabel",wraplength=930).pack(side="left",fill="x",expand=True)
        ttk.Button(default_box,text="Charger dans le constructeur",style="Secondary.TButton",command=self._load_default_formula).pack(side="right",padx=(8,0))
        builder=ttk.LabelFrame(self.finance_page,text="Nouvelle version de formule",style="Section.TLabelframe",padding=10);builder.pack(fill="x",pady=(0,10))
        self.formula_name=tk.StringVar(value="Formule d’impact");self.formula_institution=tk.StringVar(value="Toutes");self.formula_regime=tk.StringVar();self.formula_rubric=tk.StringVar(value="*");self.formula_quarter=tk.StringVar(value="T1");self.formula_year=tk.StringVar(value=str(datetime.now().year));self.formula_aggregation=tk.StringVar(value="TOUTES_LIGNES")
        fields=[("Nom",self.formula_name),("Institution",self.formula_institution),("Régime",self.formula_regime),("Rubrique",self.formula_rubric),("Début",None),("Agrégation",self.formula_aggregation)]
        for col,(label,var) in enumerate(fields):
            ttk.Label(builder,text=label).grid(row=0,column=col,sticky="w",padx=3)
            if col==0:widget=ttk.Entry(builder,textvariable=var)
            elif col==1:widget=self.formula_institution_combo=ttk.Combobox(builder,textvariable=var,state="readonly",values=["Toutes"]+[row[2] for row in self.db.list_institutions()])
            elif col==2:widget=self.formula_regime_combo=ttk.Combobox(builder,textvariable=var,state="readonly",values=list(self.config_data.regimes))
            elif col==3:widget=ttk.Combobox(builder,textvariable=var,state="readonly",values=self.db.FORMULA_RUBRICS)
            elif col==4:
                widget=ttk.Frame(builder);ttk.Combobox(widget,textvariable=self.formula_quarter,state="readonly",values=["T1","T2","T3","T4"],width=4).pack(side="left");ttk.Spinbox(widget,from_=2020,to=2100,textvariable=self.formula_year,width=7).pack(side="left",padx=2)
            else:widget=ttk.Combobox(builder,textvariable=var,state="readonly",values=self.db.FORMULA_AGGREGATIONS)
            widget.grid(row=1,column=col,sticky="ew",padx=3);builder.columnconfigure(col,weight=1)
        available=ttk.Frame(builder);available.grid(row=2,column=0,columnspan=6,sticky="ew",pady=(8,2))
        self.formula_available_status=tk.StringVar(value="Sélectionnez le périmètre pour détecter les champs financiers existants.")
        ttk.Label(available,textvariable=self.formula_available_status,style="PageHint.TLabel",
            wraplength=850).pack(side="left",fill="x",expand=True,padx=3)
        ttk.Button(available,text="Actualiser les champs",style="Secondary.TButton",
            command=self._refresh_available_formula_fields).pack(side="right",padx=3)
        terms=ttk.Frame(builder);terms.grid(row=3,column=0,columnspan=6,sticky="ew",pady=(4,4));self.formula_component=tk.StringVar();self.formula_sign=tk.StringVar(value="+");self.formula_coefficient=tk.StringVar(value="1")
        self.formula_component_codes={}
        self.formula_component_combo=ttk.Combobox(terms,textvariable=self.formula_component,
            state="readonly",width=58);self.formula_component_combo.pack(side="left",padx=3)
        ttk.Combobox(terms,textvariable=self.formula_sign,state="readonly",values=["+","−"],width=4).pack(side="left",padx=3);ttk.Entry(terms,textvariable=self.formula_coefficient,width=9).pack(side="left",padx=3)
        ttk.Button(terms,text="Ajouter le champ à la formule",command=self._add_formula_term).pack(side="left",padx=3);ttk.Button(terms,text="Retirer le terme",command=self._remove_formula_term).pack(side="left",padx=3)
        self.formula_terms=[];self.formula_terms_tree=ttk.Treeview(builder,columns=("component","coefficient"),show="headings",height=4);self.formula_terms_tree.heading("component",text="Champ financier");self.formula_terms_tree.heading("coefficient",text="Coefficient");self.formula_terms_tree.column("component",width=380);self.formula_terms_tree.column("coefficient",width=120,anchor="center");self.formula_terms_tree.grid(row=4,column=0,columnspan=6,sticky="ew",padx=3)
        self.formula_preview=tk.StringVar(value="Formule : ajoutez des champs");ttk.Label(builder,textvariable=self.formula_preview,style="PageHint.TLabel").grid(row=5,column=0,columnspan=4,sticky="w",padx=3,pady=6)
        ttk.Button(builder,text="Simuler sur le périmètre",style="Secondary.TButton",command=self._simulate_formula).grid(row=5,column=4,padx=3);ttk.Button(builder,text="Enregistrer cette version",style="Primary.TButton",command=self._save_impact_formula).grid(row=5,column=5,padx=3)

        versions=ttk.LabelFrame(self.finance_page,text="Versions configurées",style="Section.TLabelframe",padding=8);versions.pack(fill="both",expand=True)
        columns=("nom","portee","regime","rubrique","debut","aggregation","version","actif");self.formula_tree=ttk.Treeview(versions,columns=columns,show="headings",height=7)
        for column,title,width in [("nom","Nom",170),("portee","Institution",160),("regime","Régime",110),("rubrique","Rubrique",170),("debut","Début",90),("aggregation","Agrégation",190),("version","Version",70),("actif","Actif",60)]:self.formula_tree.heading(column,text=title);self.formula_tree.column(column,width=width,anchor="w")
        self.formula_tree.pack(fill="both",expand=True);self.formula_tree.bind("<Double-1>",lambda _event:self._view_formula_details())
        version_actions=ttk.Frame(versions);version_actions.pack(fill="x",pady=(6,0))
        ttk.Label(version_actions,text="Double-cliquez sur une formule pour afficher sa fiche.",style="PageHint.TLabel").pack(side="left")
        ttk.Button(version_actions,text="Voir les détails",command=self._view_formula_details).pack(side="right",padx=3)
        ttk.Button(version_actions,text="Modifier / créer une version",style="Secondary.TButton",command=self._load_selected_formula).pack(side="right",padx=3)
        ttk.Button(version_actions,text="Activer / désactiver",command=self._toggle_impact_formula).pack(side="right",padx=3)
        ttk.Button(version_actions,text="Supprimer la version",command=self._delete_impact_formula).pack(side="right",padx=3)
        for variable in [self.formula_institution,self.formula_regime,self.formula_quarter,self.formula_year]:
            variable.trace_add("write",lambda *_args:self.after_idle(self._refresh_available_formula_fields))
        self._refresh_formula_tree();self._refresh_available_formula_fields()

    def _selected_formula(self):
        selected=self.formula_tree.selection()
        if not selected:raise ValueError("Sélectionnez une formule dans la liste.")
        return self.db.get_impact_formula(selected[0])

    def _formula_expression_text(self,formula):
        labels={row[0]:row[1] for row in self.db.list_financial_components(active_only=False)};parts=[]
        for term in formula.get("terms",[]):
            coefficient=float(term.get("coefficient",0));sign="+" if coefficient>=0 else "−";amount=abs(coefficient);label=labels.get(term.get("code"),term.get("code"))
            parts.append(f"{sign} {amount:g} × {label}")
        return " ".join(parts).lstrip("+ ") or "0"

    def _view_formula_details(self):
        try:formula=self._selected_formula()
        except ValueError as exc:messagebox.showwarning("Formule",str(exc));return
        names={row[0]:row[2] for row in self.db.list_institutions()};scope=names.get(formula.get("institution_id"),"Toutes les institutions")
        status="Système — toujours disponible" if formula.get("system") else ("Active" if formula.get("active") else "Inactive")
        content=f"""FORMULE D’IMPACT

Nom : {formula['name']}
Identifiant : {formula['id']}
Version : {formula['version']}
Statut : {status}
Institution : {scope}
Régime : {formula.get('regime','Tous les régimes')}
Rubrique : {formula.get('rubric','*')}
Entrée en vigueur : {formula.get('quarter','T1')} {formula.get('year',2020)}
Agrégation : {formula.get('aggregation')}

Expression
{self._formula_expression_text(formula)}

Règle de modification
Toute modification est enregistrée comme une nouvelle version afin de préserver la traçabilité des anciens traitements."""
        self._text_dialog(f"Détails — {formula['name']}",content,"760x600")

    def _load_selected_formula(self):
        try:formula=self._selected_formula()
        except ValueError as exc:messagebox.showwarning("Formule",str(exc));return
        if formula.get("system"):
            self._load_default_formula();return
        names={row[0]:row[2] for row in self.db.list_institutions()};self.formula_name.set(f"{formula['name']} — modification")
        self.formula_institution.set(names.get(formula.get("institution_id"),"Toutes"));self.formula_regime.set(formula["regime"]);self.formula_rubric.set(formula["rubric"]);self.formula_quarter.set(formula["quarter"]);self.formula_year.set(str(formula["year"]));self.formula_aggregation.set(formula["aggregation"])
        self.formula_terms=[dict(term) for term in formula.get("terms",[])];self._refresh_formula_terms()
        messagebox.showinfo("Modification versionnée",f"La formule {formula['name']} v{formula['version']} est chargée dans le constructeur. L’enregistrement créera une nouvelle version; l’original ne sera pas écrasé.")

    def _load_default_formula(self):
        formula=self.db.default_impact_formula();self.formula_terms=[dict(term) for term in formula["terms"]]
        self.formula_name.set("Variante de la formule SICORPA par défaut");self.formula_rubric.set("*");self.formula_aggregation.set(formula["aggregation"]);self._refresh_formula_terms()
        messagebox.showinfo("Formule par défaut","La formule système a été copiée dans le constructeur. Modifiez les termes, choisissez le périmètre, simulez puis enregistrez une nouvelle version.")

    def _add_financial_component(self):
        try:self.db.add_financial_component(self.component_code.get(),self.component_label.get())
        except ValueError as exc:messagebox.showwarning("Composante invalide",str(exc));return
        self.component_code.set("");self.component_label.set("");self._refresh_financial_components();messagebox.showinfo("Composante","La composante peut maintenant être mappée à un champ Access ou Excel puis utilisée dans une formule.")

    def _refresh_financial_components(self):
        if hasattr(self,"map_target_combo"):
            base=[value for value in self.map_target_combo["values"] if not str(value).startswith("composante_")]
            self.map_target_combo["values"]=base+[f"composante_{row[0]}"
                for row in self.db.list_financial_components() if not row[3]]
        self._refresh_available_formula_fields()

    def _refresh_available_formula_fields(self):
        if not hasattr(self,"formula_component_combo"):return
        institution=self.formula_institution.get().strip()
        institution_id="" if institution in {"","Toutes"} else self.institution_ids_by_name.get(institution,"")
        regime=self.formula_regime.get().strip();quarter=self.formula_quarter.get().strip()
        try:year=int(self.formula_year.get())
        except (TypeError,ValueError):year=None
        if not regime or not quarter or year is None:
            self.formula_component_codes={};self.formula_component_combo["values"]=[]
            self.formula_component.set("")
            self.formula_available_status.set(
                "Sélectionnez le régime, le trimestre et l’année pour détecter les champs financiers existants.")
            return

        previous_code=self.formula_component_codes.get(self.formula_component.get(),"")
        rows=self.db.available_financial_components(institution_id,regime,quarter,year)
        self.formula_component_codes={};labels=[]
        for code,label,target,mapped,populated,total in rows:
            evidence=(f"mappé — {populated} ligne(s) avec montant non nul" if mapped else
                      f"{populated} ligne(s) avec montant non nul")
            display=f"{label} [{target}] — {evidence}"
            labels.append(display);self.formula_component_codes[display]=code
        self.formula_component_combo["values"]=labels
        retained=next((label for label,code in self.formula_component_codes.items()
                       if code==previous_code),None)
        self.formula_component.set(retained or (labels[0] if labels else ""))
        if labels:
            total=rows[0][5]
            self.formula_available_status.set(
                f"{len(labels)} champ(s) financier(s) disponible(s) dans le périmètre — {total} ligne(s) de paie. "
                "Seuls les champs mappés ou contenant un montant non nul sont proposés.")
        else:
            self.formula_available_status.set(
                "Aucun champ financier exploitable détecté dans ce périmètre. Vérifiez le chargement du listing "
                "et le mapping de ses colonnes financières.")


    def _add_formula_term(self):
        try:coefficient=float(self.formula_coefficient.get().replace(",","."))
        except ValueError:messagebox.showwarning("Coefficient","Saisissez un nombre valide.");return
        display=self.formula_component.get();code=self.formula_component_codes.get(display,"")
        if not code:
            messagebox.showwarning("Champ financier","Sélectionnez un champ existant dans le périmètre.");return
        coefficient=coefficient*(-1 if self.formula_sign.get()=="−" else 1)
        self.formula_terms.append({"code":code,"coefficient":coefficient});self._refresh_formula_terms()

    def _remove_formula_term(self):
        selected=self.formula_terms_tree.selection()
        if selected:self.formula_terms.pop(int(selected[0]));self._refresh_formula_terms()

    def _refresh_formula_terms(self):
        self.formula_terms_tree.delete(*self.formula_terms_tree.get_children())
        components={row[0]:(row[1],row[2] or f"composante_{row[0]}")
                    for row in self.db.list_financial_components(active_only=False)}
        for index,term in enumerate(self.formula_terms):
            label,field=components.get(term["code"],(term["code"],term["code"]))
            self.formula_terms_tree.insert("","end",iid=str(index),
                values=(f"{label} [{field}]",f'{term["coefficient"]:g}'))
        expression=" + ".join(
            f'{term["coefficient"]:g} × {components.get(term["code"],(term["code"],))[0]}'
            for term in self.formula_terms) or "0";self.formula_preview.set(f"Formule : {expression} — {self.formula_aggregation.get()}")

    def _formula_scope_values(self):
        institution=self.formula_institution.get();institution_id="" if institution=="Toutes" else self.institution_ids_by_name.get(institution,"")
        if institution!="Toutes" and not institution_id:raise ValueError("Institution inconnue.")
        if not self.formula_regime.get():raise ValueError("Sélectionnez le régime.")
        return institution_id,self.formula_regime.get(),self.formula_quarter.get(),int(self.formula_year.get())

    def _save_impact_formula(self):
        try:
            institution_id,regime,quarter,year=self._formula_scope_values();self.db.save_impact_formula(self.formula_name.get(),institution_id,regime,self.formula_rubric.get(),quarter,year,self.formula_aggregation.get(),self.formula_terms)
        except (ValueError,TypeError) as exc:messagebox.showwarning("Formule invalide",str(exc));return
        self.formula_terms=[];self._refresh_formula_terms();self._refresh_formula_tree()
        self._refresh_matching_formula_choices();messagebox.showinfo("Formule","Nouvelle version enregistrée. Les anciens résultats conservent leur formule d’origine.")

    def _simulate_formula(self):
        try:
            institution_id,regime,quarter,year=self._formula_scope_values()
            if not institution_id:raise ValueError("Choisissez une institution pour la simulation.")
            key="matricule_normalise" if "MATRICULE" in self.formula_rubric.get() else "nom_normalise";rank=f"ROW_NUMBER() OVER(PARTITION BY p.{key} ORDER BY p.ligne_source)"
            expression=self.db.formula_terms_sql(self.formula_terms,self.formula_aggregation.get(),"p",rank)
            with self.db.connect() as con:row=con.execute(f"SELECT COUNT(*),COALESCE(SUM(impact_simule),0),COALESCE(AVG(impact_simule),0) FROM (SELECT {expression} impact_simule FROM paie_standardisee p WHERE institution_id=? AND regime=? AND trimestre=? AND annee=?) simulation",[institution_id,regime,quarter,year]).fetchone()
            messagebox.showinfo("Simulation de la formule en construction",f"Lignes testées : {row[0]:,}\nImpact total : {row[1]:,.2f}\nImpact moyen : {row[2]:,.2f}\n\nAucune donnée n’a été modifiée.".replace(","," "))
        except Exception as exc:messagebox.showwarning("Simulation impossible",str(exc))

    def _refresh_formula_tree(self):
        if not hasattr(self,"formula_tree"):return
        self.formula_tree.delete(*self.formula_tree.get_children())
        default=self.db.default_impact_formula();self.formula_tree.insert("","end",iid="FORMULE_DEFAUT",values=(default["name"],"Toutes",default["regime"],default["rubric"],f'{default["quarter"]} {default["year"]}',default["aggregation"],default["version"],"Système"),tags=("system",))
        names={row[0]:row[2] for row in self.db.list_institutions()}
        for row in self.db.list_impact_formulas():
            fid,name,iid,regime,rubric,quarter,year,aggregation,_terms,version,active=row;self.formula_tree.insert("","end",iid=fid,values=(name,names.get(iid,"Toutes"),regime,rubric,f"{quarter} {year}",aggregation,version,"Oui" if active else "Non"))

    def _toggle_impact_formula(self):
        selected=self.formula_tree.selection()
        if not selected:return
        if selected[0]=="FORMULE_DEFAUT":messagebox.showinfo("Formule système","La formule par défaut garantit le fonctionnement lorsqu’aucune formule personnalisée ne s’applique. Elle ne peut pas être désactivée; créez une version prioritaire pour la remplacer sur un périmètre.");return
        active=self.formula_tree.item(selected[0],"values")[-1]=="Oui";self.db.set_impact_formula_active(selected[0],not active)
        self._refresh_formula_tree();self._refresh_matching_formula_choices()

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
        if hasattr(self,"multi_institution_combo"):self._refresh_institution_combo(self.multi_institution_combo)
        if hasattr(self,"formula_institution_combo"):
            names=[row[2] for row in self.db.list_institutions()];self.formula_institution_combo["values"]=["Toutes"]+names
        if hasattr(self,"dashboard_institution_combo"):
            names=[row[2] for row in self.db.list_institutions()];self.dashboard_institution_combo["values"]=["Toutes"]+names
            if self.dashboard_institution.get() not in names:self.dashboard_institution.set("Toutes")

    def _refresh_all_regimes(self):
        values=list(self.config_data.regimes)
        for scope in [self.access_scope,self.excel_scope,self.match_scope]:
            scope["regime_combo"]["values"]=values
            if scope["regime"].get() not in values:scope["regime"].set("")
        if hasattr(self,"multi_regime_combo"):
            self.multi_regime_combo["values"]=values
            if self.multi_regime.get() not in values:self.multi_regime.set("")
        if hasattr(self,"map_regime_combo"):
            self.map_regime_combo["values"]=values
            if self.map_regime.get() not in values:self.map_regime.set("")
        if hasattr(self,"formula_regime_combo"):
            self.formula_regime_combo["values"]=values
        if hasattr(self,"dashboard_regime_combo"):
            self.dashboard_regime_combo["values"]=["Tous"]+values
            if self.dashboard_regime.get() not in values:self.dashboard_regime.set("Tous")

    def _choose_access(self):
        path=filedialog.askopenfilename(filetypes=[("Access","*.accdb *.mdb")]); self.access_path.set(path or self.access_path.get())

    def _choose_payroll_excel(self):
        path=filedialog.askopenfilename(title="Choisir le listing de paie",filetypes=[("Excel","*.xlsx *.xls")])
        if not path:return
        try:sheets=excel_sheets(path)
        except Exception as exc:self._show_explicit_error(exc,"Lecture du classeur Excel",traceback.format_exc());return
        self.payroll_excel_path.set(path);self.payroll_sheet_combo["values"]=sheets
        if sheets:self.payroll_excel_sheet.set(sheets[0])

    def _choose_excel(self):
        path=filedialog.askopenfilename(title="Choisir la liste déclarative",filetypes=[("Excel","*.xlsx *.xls *.xlsm")])
        if not path:return
        try:sheets=excel_sheets(path)
        except Exception as exc:self._show_explicit_error(exc,"Lecture de la liste déclarative",traceback.format_exc());return
        self.excel_path.set(path);self.sheet_combo["values"]=sheets
        if sheets:self.excel_sheet.set(sheets[0])
        self._invalidate_declaration_structure()
    def _scan_access(self):
        if not self.access_path.get().strip():
            messagebox.showwarning("Fichier manquant", "Sélectionnez d’abord une base Access.")
            return
        self._background(lambda: list_access_tables(self.access_path.get(),self.config_data.access_driver),
                         self._tables_loaded,operation="Lecture des tables Microsoft Access")
    def _tables_loaded(self,tables):
        self.table_combo["values"]=tables
        if tables: self.access_table.set(tables[0]); self._autofill_table(tables[0])
    def _autofill_table(self,table):
        regime=self.config_data.detect_regime(table); quarter,year=self.config_data.detect_period(table)
        if regime:self.access_scope["regime"].set(regime)
        if quarter:self.access_scope["quarter"].set(quarter)
        if year:self.access_scope["year"].set(str(year))
    def _preview_payroll_excel(self):
        if not self.payroll_excel_path.get().strip() or not self.payroll_excel_sheet.get().strip():
            messagebox.showwarning("Source incomplète","Sélectionnez un listing Excel et une feuille.")
            return
        try:frame=preview_excel(self.payroll_excel_path.get(),self.payroll_excel_sheet.get(),self.payroll_header_row.get())
        except Exception as exc:self._show_explicit_error(exc,"Aperçu du listing Excel",traceback.format_exc());return
        self.payroll_preview.delete(*self.payroll_preview.get_children())
        columns=[str(column) for column in frame.columns];self.payroll_preview["columns"]=columns
        for column in columns:
            self.payroll_preview.heading(column,text=column);self.payroll_preview.column(column,width=140,minwidth=80,stretch=False)
        for row in frame.fillna("").itertuples(index=False,name=None):self.payroll_preview.insert("","end",values=row)

    def _preview_excel(self):
        if not self.excel_path.get().strip() or not self.excel_sheet.get().strip():
            messagebox.showwarning("Source incomplète", "Sélectionnez un fichier Excel et une feuille.")
            return
        try:
            frame=preview_excel(self.excel_path.get(),self.excel_sheet.get(),self.header_row.get())
        except Exception as exc:
            self._show_explicit_error(exc,"Aperçu du déclaratif Excel",traceback.format_exc())
            return
        columns=[str(column) for column in frame.columns]
        self.preview.delete(*self.preview.get_children());self.preview["columns"]=columns
        for c in columns:self.preview.heading(c,text=c);self.preview.column(c,width=145,minwidth=80,stretch=False)
        for row in frame.fillna("").itertuples(index=False,name=None):self.preview.insert("", "end", values=row)
        structure=describe_declaration_structure(columns,
            self.db.get_column_mapping(self.excel_scope["regime"].get(),"EXCEL"),
            self.db.required_source_columns(self.excel_scope["regime"].get(),"EXCEL"))
        self._declaration_structure_loaded(structure)
        self.declaration_tabs.select(0)

    def _analyze_declaration_structure(self):
        if not self.excel_path.get().strip() or not self.excel_sheet.get().strip():
            messagebox.showwarning("Source incomplète","Sélectionnez un fichier Excel et une feuille.");return
        regime=self.excel_scope["regime"].get().strip()
        if not regime:messagebox.showwarning("Régime manquant","Sélectionnez le régime du déclaratif.");return
        self._background(lambda:self.ingestion.inspect_declaration_structure(
            self.excel_path.get(),self.excel_sheet.get(),self.header_row.get(),regime),
            self._declaration_structure_loaded,operation="Analyse de la structure déclarative")

    def _invalidate_declaration_structure(self):
        if not hasattr(self,"declaration_structure_tree"):return
        regime=self.excel_scope["regime"].get().strip()
        structure=describe_declaration_structure([],self.db.get_column_mapping(regime,"EXCEL"),
            self.db.required_source_columns(regime,"EXCEL"))
        self._declaration_structure_loaded(structure,initial=True,select_tab=False)

    def _declaration_structure_loaded(self,structure,initial=False,select_tab=True):
        self.declaration_structure_tree.delete(*self.declaration_structure_tree.get_children())
        for index,row in enumerate(structure["rows"]):
            status=row[3];tag="error" if status.startswith("✗") else "ok" if status.startswith("✓") else "warning"
            self.declaration_structure_tree.insert("","end",iid=str(index),values=row,tags=(tag,))
        recognized=sum(1 for row in structure["rows"] if row[3].startswith("✓"))
        if initial:
            text="Champs obligatoires avant rapprochement : Matricule ET Nom / noms de l’agent. Sélectionnez le fichier puis analysez sa structure."
            self.declaration_structure_status_label.configure(background="#EAF2FB",foreground="#12355B")
            self.excel_load.configure(state="disabled")
        elif structure["issues"]:
            text="Structure non exploitable : "+"; ".join(structure["issues"])+". Corrigez le fichier ou le mapping avant de charger."
            self.declaration_structure_status_label.configure(background="#FDECEC",foreground="#A11D1D")
            self.excel_load.configure(state="disabled")
            messagebox.showwarning("Champs déclaratifs obligatoires manquants",text)
        else:
            extra=f" • {len(structure['unmapped'])} colonne(s) non mappée(s), donc non intégrée(s)" if structure["unmapped"] else ""
            text=f"Structure exploitable : Matricule et Nom présents • {recognized} champ(s) standard reconnu(s){extra}."
            self.declaration_structure_status_label.configure(background="#EAF7EE",foreground="#166534")
            self.excel_load.configure(state="normal")
        self.declaration_structure_status.set(text)
        if select_tab:self.declaration_tabs.select(1)

    def _refresh_declaration_imports(self):
        if not hasattr(self,"declaration_history_tree"):return
        self.declaration_history_tree.delete(*self.declaration_history_tree.get_children())
        institution_name=self.excel_scope["institution"].get().strip() if hasattr(self,"excel_scope") else ""
        institution_id=self.institution_ids_by_name.get(institution_name,"")
        regime=self.excel_scope["regime"].get().strip() if hasattr(self,"excel_scope") else ""
        quarter=self.excel_scope["quarter"].get().strip() if hasattr(self,"excel_scope") else ""
        try:year=int(self.excel_scope["year"].get()) if self.excel_scope["year"].get() else None
        except ValueError:year=None
        for row in self.db.list_declaration_imports(institution_id,regime,quarter,year):
            execution,institution,reg,trim,annee,file_path,sheet,mode,lines,imported,matching_refs,campaign_refs=row
            references=int(matching_refs or 0)+int(campaign_refs or 0)
            usage=(f"Utilisé — {matching_refs or 0} rapproch., {campaign_refs or 0} campagne(s)" if references else "Libre — suppression autorisée")
            state="Disponible" if lines else "Vide / remplacé"
            date_text=imported.strftime("%d/%m/%Y %H:%M") if hasattr(imported,"strftime") else str(imported or "")
            self.declaration_history_tree.insert("","end",iid=execution,values=(institution,reg,f"{trim} {annee}",Path(file_path).name,sheet,f"{int(lines):,}".replace(","," "),state,usage,date_text),tags=("used" if references else "free",))
        self.declaration_history_tree.tag_configure("used",foreground="#8A4B08");self.declaration_history_tree.tag_configure("free",foreground="#166534")

    def _delete_declaration_import(self):
        selected=self.declaration_history_tree.selection()
        if not selected:messagebox.showwarning("Suppression","Sélectionnez un import déclaratif à supprimer.");return
        execution_id=selected[0];values=self.declaration_history_tree.item(execution_id,"values")
        if str(values[7]).startswith("Utilisé"):
            messagebox.showwarning("Suppression bloquée","Cet import est déjà utilisé par un traitement. SICORPA le conserve pour garantir la traçabilité des résultats.");return
        if not messagebox.askyesno("Confirmer la suppression",f"Supprimer définitivement les {values[5]} lignes de l’import suivant ?\n\nFichier : {values[3]}\nFeuille : {values[4]}\nPérimètre : {values[0]} — {values[1]} — {values[2]}\n\nLe fichier Excel d’origine ne sera pas supprimé."):
            return
        self._background(lambda:self.db.delete_declaration_import(execution_id),
            self._declaration_import_deleted,refresh_data=True,operation="Suppression d’un import déclaratif")

    def _declaration_import_deleted(self,result):
        self._refresh_declaration_imports()
        messagebox.showinfo("Import supprimé",f"{result['lines']:,} lignes déclaratives ont été supprimées de DuckDB.\nLa trace de l’opération est conservée dans le journal.".replace(","," "))
    def _scope_values(self,scope):
        institution_name=scope["institution"].get().strip()
        institution_id=self.institution_ids_by_name.get(institution_name, "")
        return validate_scope_values(institution_id,scope["regime"].get(),scope["quarter"].get(),scope["year"].get())
    def _validated_scope(self,scope):
        try:return self._scope_values(scope)
        except ValueError as exc:
            messagebox.showwarning("Périmètre incomplet",str(exc));return None
    def _load_access(self):
        if not self._require_active_trial("l’importation Access"):return
        if self.busy:messagebox.showwarning("Traitement en cours","Attendez la fin du traitement actuel avant d’en lancer un autre.");return
        args=self._validated_scope(self.access_scope)
        if args is None:return
        if not self.access_path.get().strip() or not self.access_table.get().strip():
            messagebox.showwarning("Source incomplète","Sélectionnez une base Access et une table.");return
        self._open_generation_dialog("Chargement des données Access",f"Source : {Path(self.access_path.get()).name}  •  Table : {self.access_table.get()}\nLa lecture et l’écriture dans DuckDB s’exécutent en arrière-plan.","Étapes du chargement",True)
        self._background(lambda:self.ingestion.load_access(self.access_path.get(),self.access_table.get(),*args,progress=self._progress),self._access_load_completed,refresh_data=True)

    def _access_load_completed(self,execution_id):
        if self.generation_window and self.generation_window.winfo_exists():
            self.generation_title.set("Chargement Access terminé avec succès");self.generation_status.set("100% — Les données sont disponibles dans DuckDB.")
            self.generation_bar.stop();self.generation_bar.configure(mode="determinate");self.generation_bar["value"]=100
            self.generated_files.insert("end",f"✓  Exécution : {execution_id}");self.generated_files.see("end");self.generation_close.configure(state="normal")
        messagebox.showinfo("Chargement terminé","La table Access a été chargée et standardisée dans DuckDB.")
    def _load_payroll_excel(self):
        if not self._require_active_trial("l’importation du listing Excel"):return
        if self.busy:messagebox.showwarning("Traitement en cours","Attendez la fin du traitement actuel avant d’en lancer un autre.");return
        args=self._validated_scope(self.access_scope)
        if args is None:return
        if not self.payroll_excel_path.get().strip() or not self.payroll_excel_sheet.get().strip():
            messagebox.showwarning("Source incomplète","Sélectionnez un listing Excel et une feuille.");return
        self._open_generation_dialog("Chargement du listing Excel",f"Source : {Path(self.payroll_excel_path.get()).name}  •  Feuille : {self.payroll_excel_sheet.get()}\nLa standardisation et l’écriture dans DuckDB s’exécutent en arrière-plan.","Étapes du chargement",True)
        self._background(lambda:self.ingestion.load_payroll_excel(self.payroll_excel_path.get(),self.payroll_excel_sheet.get(),self.payroll_header_row.get(),*args,progress=self._progress),self._payroll_excel_load_completed,refresh_data=True)

    def _payroll_excel_load_completed(self,execution_id):
        if self.generation_window and self.generation_window.winfo_exists():
            self.generation_title.set("Listing Excel chargé avec succès");self.generation_status.set("100% — Les données de paie sont disponibles dans DuckDB.")
            self.generation_bar.stop();self.generation_bar.configure(mode="determinate");self.generation_bar["value"]=100
            self.generated_files.insert("end",f"✓  Exécution : {execution_id}");self.generated_files.see("end");self.generation_close.configure(state="normal")
        messagebox.showinfo("Chargement terminé","Le listing Excel a été chargé et standardisé comme données de paie.")

    def _load_excel(self):
        if not self._require_active_trial("l’importation Excel"):return
        if self.busy:messagebox.showwarning("Traitement en cours","Attendez la fin du traitement actuel avant d’en lancer un autre.");return
        args=self._validated_scope(self.excel_scope)
        if args is None:return
        if not self.excel_path.get().strip() or not self.excel_sheet.get().strip():
            messagebox.showwarning("Source incomplète","Sélectionnez un fichier Excel et une feuille.");return
        mode="replace_period" if self.declaration_mode.get().startswith("Remplacer") else "append"
        if mode=="replace_period" and not messagebox.askyesno("Remplacer le périmètre",f"Les listes déclaratives actuellement chargées pour {self.excel_scope['institution'].get()} — {args[1]} — {args[2]} {args[3]} seront retirées avant l’import.\n\nContinuer ?"):
            return
        self._open_generation_dialog("Chargement de la liste déclarative",f"Source : {Path(self.excel_path.get()).name}  •  Feuille : {self.excel_sheet.get()}\nMode : {self.declaration_mode.get()}\nLa lecture, la validation de structure et l’écriture DuckDB s’exécutent en arrière-plan.","Étapes du chargement",True)
        self._background(lambda:self.ingestion.load_excel(self.excel_path.get(),self.excel_sheet.get(),self.header_row.get(),*args,mode=mode,progress=self._progress),
            self._declaration_load_completed,refresh_data=True,
            operation="Chargement du déclaratif Excel")

    def _declaration_load_completed(self,execution_id):
        if self.generation_window and self.generation_window.winfo_exists():
            self.generation_title.set("Liste déclarative chargée avec succès");self.generation_status.set("100% — Les données déclaratives sont disponibles dans DuckDB.")
            self.generation_bar.stop();self.generation_bar.configure(mode="determinate");self.generation_bar["value"]=100
            self.generated_files.insert("end",f"✓  Exécution : {execution_id}");self.generated_files.see("end");self.generation_close.configure(state="normal")
        self._refresh_declaration_imports()
        messagebox.showinfo("Chargement terminé","La liste déclarative a été contrôlée, standardisée et chargée dans DuckDB.")
    def _matching_formula_scope_values(self):
        name=self.match_scope["institution"].get().strip()
        institution_id=self.institution_ids_by_name.get(name,"")
        regime=self.match_scope["regime"].get().strip()
        quarter=self.match_scope["quarter"].get().strip()
        year=self.match_scope["year"].get().strip()
        if not all([institution_id,regime,quarter,year]):return None
        try:return institution_id,regime,quarter,int(year)
        except ValueError:return None

    def _matching_scope_changed(self):
        self._refresh_treatment_filters();self._refresh_matching_formula_choices()

    def _refresh_matching_formula_choices(self):
        if not hasattr(self,"match_formula_combo"):return
        scope=self._matching_formula_scope_values();current_id=self.match_formula_ids.get(
            self.match_formula_choice.get(),"") if hasattr(self,"match_formula_ids") else ""
        self.match_formula_ids={};labels=[]
        if scope:
            for formula in self.db.selectable_impact_formulas(*scope):
                reach="Toutes institutions" if not formula.get("institution_id") else "Institution sélectionnée"
                label=f"{formula['name']} — v{formula['version']} — {reach} — depuis {formula.get('quarter','T1')} {formula.get('year',2020)}"
                labels.append(label);self.match_formula_ids[label]=formula["id"]
        self.match_formula_combo["values"]=labels
        retained=next((label for label,fid in self.match_formula_ids.items() if fid==current_id),None)
        if retained:self.match_formula_choice.set(retained)
        elif labels:self.match_formula_choice.set(labels[0])
        else:self.match_formula_choice.set("")
        self._impact_mode_changed()

    def _impact_mode_changed(self):
        if not hasattr(self,"match_formula_combo"):return
        selected=self.match_impact_mode.get()==IMPACT_MODE_SELECTED
        self.match_formula_combo.configure(state="readonly" if selected else "disabled")
        self._update_matching_formula_status()

    def _update_matching_formula_status(self):
        if not hasattr(self,"match_formula_status"):return
        scope=self._matching_formula_scope_values()
        if not scope:
            self.match_formula_status.set("Complétez l’institution, le régime, le trimestre et l’année pour voir les formules applicables.")
            return
        institution_id,regime,quarter,year=scope
        if self.match_impact_mode.get()==IMPACT_MODE_SELECTED:
            formula_id=self.match_formula_ids.get(self.match_formula_choice.get(),"")
            if not formula_id:
                self.match_formula_status.set("Aucune formule globale applicable. Créez une formule avec la rubrique « * » dans Calculs financiers.")
                return
            formula=self.db.selected_impact_formula(formula_id,*scope)
            self.match_formula_status.set(
                f"Formule forcée pour toutes les catégories d’impact du régime {regime} : "
                f"{formula['name']} v{formula['version']} — {formula['aggregation']}.")
            return
        rubrics=["DOUBLON_MATRICULE","DOUBLON_NOM","MATRICULE_MANQUANT",
                 "PAYE_NON_DECLARE","PAYE_HORS_PERIMETRE","CONFORME_MATRICULE","CONFORME_NOM"]
        resolved={}
        for rubric in rubrics:
            formula=self.db.resolve_impact_formula(institution_id,regime,quarter,year,rubric)
            resolved[formula["id"]]=f"{formula['name']} v{formula['version']}"
        self.match_formula_status.set(
            f"Automatique par régime {regime} et par rubrique : "+", ".join(resolved.values())+".")

    def _matching_impact_formula_id(self):
        if self.match_impact_mode.get()!=IMPACT_MODE_SELECTED:return ""
        formula_id=self.match_formula_ids.get(self.match_formula_choice.get(),"")
        if not formula_id:
            raise ValueError("Choisissez une formule globale applicable avant de lancer le rapprochement.")
        scope=self._matching_formula_scope_values()
        if not scope:raise ValueError("Complétez le périmètre du rapprochement.")
        self.db.selected_impact_formula(formula_id,*scope)
        return formula_id

    def _open_finance_configuration(self):
        scope=self._matching_formula_scope_values()
        if scope and hasattr(self,"formula_regime"):
            institution_id,regime,quarter,year=scope
            institution_name=self.match_scope["institution"].get()
            self.formula_institution.set(institution_name)
            self.formula_regime.set(regime);self.formula_quarter.set(quarter)
            self.formula_year.set(str(year));self._refresh_available_formula_fields()
        self.notebook.select(self.finance_page)


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

    def _open_multi_history(self):
        window=tk.Toplevel(self);window.title("Historique des campagnes multi-régimes")
        window.transient(self)
        body=ttk.Frame(window,padding=14);body.pack(fill="both",expand=True)
        ttk.Label(body,text="Campagnes d’analyse multi-régimes",style="PageTitle.TLabel").pack(anchor="w")
        columns=("institution","regime","period","status","base","declaration","created","export")
        self.multi_history_tree=ttk.Treeview(body,columns=columns,show="headings",height=13)
        for column,title,width in [("institution","Institution",220),("regime","Régime",130),
                ("period","Période",90),("status","État",100),("base","Base",90),
                ("declaration","Déclaratif",90),("created","Créée le",145),("export","Dossier export",260)]:
            self.multi_history_tree.heading(column,text=title);self.multi_history_tree.column(column,width=width,anchor="w")
        frame=ttk.Frame(body);frame.pack(fill="both",expand=True,pady=10)
        self.multi_history_tree.pack(in_=frame,side="left",fill="both",expand=True)
        scroll=ttk.Scrollbar(frame,orient="vertical",command=self.multi_history_tree.yview)
        self.multi_history_tree.configure(yscrollcommand=scroll.set);scroll.pack(side="right",fill="y")
        actions=ttk.Frame(body);actions.pack(fill="x")
        ttk.Button(actions,text="Actualiser",command=self._refresh_multi_history).pack(side="left")
        ttk.Button(actions,text="Archiver la campagne",command=self._archive_multi_campaign).pack(side="left",padx=5)
        ttk.Button(actions,text="Ouvrir le dossier",command=self._open_multi_campaign_folder).pack(side="right")
        ttk.Button(actions,text="Réexporter",style="Primary.TButton",
                   command=self._reexport_multi_campaign).pack(side="right",padx=5)
        ttk.Button(actions,text="Charger les résultats",style="Secondary.TButton",
                   command=self._load_multi_campaign).pack(side="right")
        self._refresh_multi_history();window.after_idle(lambda:self._center_child_window(window,1100,560))

    def _refresh_multi_history(self):
        if not hasattr(self,"multi_history_tree") or not self.multi_history_tree.winfo_exists():return
        self.multi_history_tree.delete(*self.multi_history_tree.get_children())
        for row in self.multi_analysis.list_campaigns():
            campaign,institution,regime,quarter,year,status,base,declaration,_decl_exec,created,_ended,folder,_archived=row
            stamp=created.strftime("%d/%m/%Y %H:%M") if created else ""
            self.multi_history_tree.insert("","end",iid=campaign,
                values=(institution,regime,f"{quarter} {year}",status,base,declaration,stamp,folder or ""))

    def _selected_multi_campaign(self):
        selected=self.multi_history_tree.selection() if hasattr(self,"multi_history_tree") else ()
        if not selected:raise ValueError("Sélectionnez une campagne dans l’historique.")
        return selected[0]

    def _load_multi_campaign(self):
        try:campaign=self._selected_multi_campaign();summary=self.multi_analysis.summary(campaign)
        except ValueError as exc:messagebox.showwarning("Historique",str(exc));return
        self.multi_last_campaign=campaign;self.multi_export_button.configure(state="normal")
        self.multi_result_tree.delete(*self.multi_result_tree.get_children())
        for row in summary:self.multi_result_tree.insert("","end",values=(row[0],row[1],row[2],
            f"{row[3]:,.2f}".replace(","," "),f"{row[4]:,.2f}".replace(","," ")))
        self.multi_status.set(f"Campagne historique chargée : {campaign}")
        messagebox.showinfo("Historique","Les résultats de la campagne sont chargés et peuvent être réexportés.")

    def _reexport_multi_campaign(self):
        try:self.multi_last_campaign=self._selected_multi_campaign()
        except ValueError as exc:messagebox.showwarning("Historique",str(exc));return
        self.multi_export_button.configure(state="normal");self._export_multi_analysis()

    def _archive_multi_campaign(self):
        try:campaign=self._selected_multi_campaign()
        except ValueError as exc:messagebox.showwarning("Historique",str(exc));return
        if messagebox.askyesno("Archiver","Archiver cette campagne ? Ses données resteront conservées."):
            self.multi_analysis.archive_campaign(campaign,True);self._refresh_multi_history()

    def _open_multi_campaign_folder(self):
        try:campaign=self._selected_multi_campaign()
        except ValueError as exc:messagebox.showwarning("Historique",str(exc));return
        row=next((item for item in self.multi_analysis.list_campaigns(True) if item[0]==campaign),None)
        folder=row[11] if row else ""
        if not folder or not Path(folder).exists():
            messagebox.showwarning("Dossier indisponible","Cette campagne n’a pas encore été exportée ou son dossier a été déplacé.")
            return
        self._open_runtime_path(Path(folder))

    def _multi_period(self):
        quarter=self.multi_quarter.get().strip();year=self.multi_year.get().strip()
        if quarter not in {"T1","T2","T3","T4"} or not year:
            raise ValueError("Sélectionnez un trimestre et une année valides.")
        return quarter,int(year)

    def _refresh_multi_sources(self):
        try:
            institution_id,regime,quarter,year=self._multi_scope_values()
            rows=self.multi_analysis.available_sources(quarter,year)
            declarations=self.multi_analysis.available_declarations(institution_id,regime,quarter,year)
        except Exception as exc:messagebox.showwarning("Données indisponibles",str(exc));return
        self.multi_declaration_ids={};labels=[]
        for execution,file_source,sheet,count,date_end in declarations:
            stamp=date_end.strftime("%d/%m/%Y %H:%M") if date_end else "date inconnue"
            label=f"{Path(file_source).name if file_source else execution} — {sheet or 'feuille'} — {count:,} lignes — {stamp}".replace(","," ")
            labels.append(label);self.multi_declaration_ids[label]=execution
        self.multi_declaration_combo["values"]=labels
        self.multi_declaration.set(labels[0] if labels else "")
        self.multi_source_tree.delete(*self.multi_source_tree.get_children())
        self.multi_selected_sources.clear();self.multi_diagnosis=None
        for row in rows:
            execution,name,_institution,source_regime,table,count,file_source=row
            self.multi_source_tree.insert("","end",iid=execution,
                values=("Non",name,source_regime,table,count,"—","—","—","À vérifier",
                        Path(file_source).name if file_source else ""))
        self.multi_status.set(f"{len(declarations)} déclaratif(s) et {len(rows)} source(s) trouvés pour {quarter} {year}.")
        if not declarations:messagebox.showwarning("Déclaratif","Aucune version déclarative ne correspond au périmètre.")
        if not rows:messagebox.showinfo("Sources","Aucun listing standardisé n’est disponible pour cette période.")


    def _set_multi_source_state(self,execution,selected):
        if not self.multi_source_tree.exists(execution):return
        if selected:self.multi_selected_sources.add(execution)
        else:self.multi_selected_sources.discard(execution)
        values=list(self.multi_source_tree.item(execution,"values"));values[0]="Oui" if selected else "Non"
        self.multi_source_tree.item(execution,values=values)

    def _update_multi_selection_status(self):
        total=len(self.multi_source_tree.get_children());selected=len(self.multi_selected_sources)
        self.multi_status.set(f"{selected} source(s) sélectionnée(s) sur {total}. Double-cliquez sur une ligne pour inverser son état.")

    def _toggle_multi_source(self,event=None):
        execution=self.multi_source_tree.identify_row(event.y) if event is not None else ""
        if not execution:
            selected=self.multi_source_tree.selection()
            if not selected:return
            execution=selected[0]
        self._set_multi_source_state(execution,execution not in self.multi_selected_sources)
        self._update_multi_selection_status()

    def _set_chosen_multi_sources(self,selected):
        chosen=self.multi_source_tree.selection()
        if not chosen:
            messagebox.showwarning("Sources","Sélectionnez d’abord une ou plusieurs lignes dans le tableau.")
            return
        for execution in chosen:self._set_multi_source_state(execution,selected)
        self._update_multi_selection_status()

    def _set_all_multi_sources(self,selected):
        for execution in self.multi_source_tree.get_children():
            self._set_multi_source_state(execution,selected)
        self._update_multi_selection_status()

    def _edit_selected_source_filters(self):
        selected=self.multi_source_tree.selection()
        if len(selected)!=1:
            messagebox.showwarning("Filtres","Sélectionnez exactement une source dans le tableau.")
            return
        values=self.multi_source_tree.item(selected[0],"values")
        institution,regime=values[1],values[2]
        self.match_scope["institution"].set(institution);self.match_scope["regime"].set(regime)
        self._refresh_treatment_filters();self.matching_tabs.select(self.standard_matching_tab)
        messagebox.showinfo("Filtres",f"Vous pouvez modifier les filtres de {institution} — {regime}. Revenez ensuite dans Analyse multi-régimes et relancez l’aperçu.")

    def _show_multi_source_sample(self):
        selected=self.multi_source_tree.selection()
        if len(selected)!=1:
            messagebox.showwarning("Échantillon","Sélectionnez exactement une source dans le tableau.")
            return
        try:columns,rows=self.multi_analysis.sample_source(selected[0],50)
        except Exception as exc:self._show_explicit_error(exc,"Échantillon du listing multi-régimes",traceback.format_exc());return
        window=tk.Toplevel(self);window.title("Échantillon du listing après filtres")
        body=ttk.Frame(window,padding=10);body.pack(fill="both",expand=True)
        ttk.Label(body,text=f"50 premières lignes maximum — {len(rows)} ligne(s) affichée(s)",
                  style="PageHint.TLabel").pack(anchor="w",pady=(0,6))
        frame=ttk.Frame(body);frame.pack(fill="both",expand=True)
        tree=ttk.Treeview(frame,columns=columns,show="headings")
        for column in columns:
            tree.heading(column,text=column);tree.column(column,width=145,anchor="w",stretch=False)
        for row in rows:tree.insert("","end",values=row)
        sy=ttk.Scrollbar(frame,orient="vertical",command=tree.yview)
        sx=ttk.Scrollbar(frame,orient="horizontal",command=tree.xview)
        tree.configure(yscrollcommand=sy.set,xscrollcommand=sx.set)
        tree.grid(row=0,column=0,sticky="nsew");sy.grid(row=0,column=1,sticky="ns");sx.grid(row=1,column=0,sticky="ew")
        frame.columnconfigure(0,weight=1);frame.rowconfigure(0,weight=1)
        ttk.Button(body,text="Fermer",command=window.destroy).pack(anchor="e",pady=(8,0))
        window.after_idle(lambda:self._center_child_window(window,1050,580))

    def _selected_declaration_execution(self):
        label=self.multi_declaration.get().strip()
        execution=self.multi_declaration_ids.get(label,"")
        if not execution:raise ValueError("Sélectionnez une version précise du déclaratif.")
        return execution

    def _preview_multi_sources(self):
        try:
            institution_id,regime,quarter,year=self._multi_scope_values()
            if not self.multi_selected_sources:raise ValueError("Sélectionnez au moins une source.")
            declaration_execution=self._selected_declaration_execution()
            diagnosis=self.multi_analysis.diagnose(institution_id,regime,quarter,year,
                declaration_execution,list(self.multi_selected_sources))
            self.multi_diagnosis=diagnosis
            for item in diagnosis["sources"]:
                execution=item["execution_id"]
                if not self.multi_source_tree.exists(execution):continue
                values=list(self.multi_source_tree.item(execution,"values"))
                filters=item["filters"]
                values[5]=item["retained"]
                values[6]="; ".join(f"{row[1]} {row[2]} {row[3]}" for row in filters) if filters else "Aucun filtre"
                formula=item["formula"];values[7]=f"{formula['name']} (v{formula['version']})"
                values[8]=(f"Prête — {item['mapping']}" if item["ready"]
                           else "; ".join(item["issues"])+f" — {item['mapping']}")
                self.multi_source_tree.item(execution,values=values,
                    tags=("ready" if item["ready"] else "error",))
            self.multi_source_tree.tag_configure("ready",foreground="#176B3A")
            self.multi_source_tree.tag_configure("error",foreground="#B42318")
            self.multi_status.set(
                f"Déclaratif : {diagnosis['declaration_rows']:,} lignes — Projection : "
                f"{diagnosis['retained_rows']:,}/{diagnosis['available_rows']:,} lignes — "
                f"{'Prête' if diagnosis['ready'] else 'Anomalies à corriger'}.".replace(","," "))
            return diagnosis
        except Exception as exc:
            self.multi_diagnosis=None;messagebox.showwarning("Diagnostic impossible",str(exc));return None


    def _multi_scope_values(self):
        institution_name=self.multi_institution.get().strip()
        institution_id=self.institution_ids_by_name.get(institution_name,"")
        return validate_scope_values(institution_id,self.multi_regime.get(),
                                     self.multi_quarter.get(),self.multi_year.get())

    def _run_multi_analysis(self):
        if not self._require_active_trial("l’analyse multi-régimes"):return
        try:
            args=self._multi_scope_values()
            if not self.multi_selected_sources:raise ValueError("Sélectionnez au moins une source de paie.")
            diagnosis=self._preview_multi_sources()
            if not diagnosis:return
            if not diagnosis["ready"]:raise ValueError("Corrigez les sources signalées avant de lancer l’analyse.")
            declaration_execution=self._selected_declaration_execution()
        except ValueError as exc:messagebox.showwarning("Analyse incomplète",str(exc));return
        regimes=", ".join(sorted({item["regime"] for item in diagnosis["sources"]}))
        confirmation=(f"Version déclarative : {self.multi_declaration.get()}\n\n"
            f"Sources sélectionnées : {len(diagnosis['sources'])}\n"
            f"Régimes concernés : {regimes}\n"
            f"Lignes disponibles : {diagnosis['available_rows']:,}\n"
            f"Lignes retenues après filtres : {diagnosis['retained_rows']:,}\n"
            f"Lignes déclaratives : {diagnosis['declaration_rows']:,}\n\n"
            "Confirmez-vous la constitution de cette campagne ?").replace(","," ")
        if not messagebox.askyesno("Confirmer l’analyse multi-régimes",confirmation):return
        self._open_generation_dialog("Analyse multi-régimes",
            "Constitution de la base trimestrielle filtrée, comparaison du déclaratif et calcul des impacts par régime de paiement.",
            "Étapes de l’analyse",True)
        self._background(lambda:self.multi_analysis.run(*args,list(self.multi_selected_sources),
            declaration_execution_id=declaration_execution,progress=self._progress),
            self._multi_analysis_completed,refresh_data=True)


    def _multi_analysis_completed(self,result):
        self.multi_last_campaign=result["campaign_id"];self.multi_export_button.configure(state="normal")
        self.multi_result_tree.delete(*self.multi_result_tree.get_children())
        for row in result["summary"]:
            self.multi_result_tree.insert("","end",values=(row[0],row[1],row[2],
                f"{row[3]:,.2f}".replace(","," "),f"{row[4]:,.2f}".replace(","," ")))
        self.multi_status.set(f"Campagne terminée : {result['base_rows']:,} lignes de paie et {result['declaration_rows']:,} lignes déclaratives.".replace(","," "))
        if self.generation_window and self.generation_window.winfo_exists():
            self.generation_title.set("Analyse multi-régimes terminée")
            self.generation_status.set("Les résultats sont disponibles. Vous pouvez maintenant les exporter.")
            self.generation_close.configure(state="normal")
        messagebox.showinfo("Analyse terminée","La base trimestrielle et le rapprochement multi-régimes ont été constitués.")

    def _export_multi_analysis(self):
        if not self.multi_last_campaign:
            messagebox.showwarning("Export","Lancez d’abord une analyse multi-régimes.");return
        folder=filedialog.askdirectory(title="Choisir le dossier du rapport multi-régimes")
        if not folder:return
        self._open_generation_dialog("Rapport multi-régimes",
            "Génération du rapport synthétique, de la méthodologie et de l’annexe détaillée.",
            "Fichiers générés",True)
        self._background(lambda:self.multi_analysis.export(self.multi_last_campaign,folder,
            progress=self._progress),self._multi_export_completed)

    def _multi_export_completed(self,path):
        if self.generation_window and self.generation_window.winfo_exists():
            self.generation_title.set("Rapport multi-régimes terminé")
            self.generation_status.set(f"Dossier créé : {path}")
            self.generation_close.configure(state="normal")
        messagebox.showinfo("Export terminé",f"Le rapport, les annexes par catégorie, les effectifs et la lettre sont disponibles dans :\n{path}")

    def _listing_period(self):
        quarter=self.listing_quarter.get().strip();year=self.listing_year.get().strip()
        if quarter not in {"T1","T2","T3","T4"} or not year:
            raise ValueError("Sélectionnez un trimestre et une année valides.")
        return quarter,int(year)

    def _refresh_listing_sources(self):
        try:quarter,year=self._listing_period();rows=self.listing_analysis.available_sources(quarter,year)
        except Exception as exc:messagebox.showwarning("Listings indisponibles",str(exc));return
        self.listing_source_tree.delete(*self.listing_source_tree.get_children())
        self.listing_selected_sources.clear();self.listing_diagnosis=None
        for execution,name,_institution,regime,table,count,file_source in rows:
            self.listing_source_tree.insert("","end",iid=execution,
                values=("Non",name,regime,table,count,"—","—","À vérifier",
                        Path(file_source).name if file_source else ""))
        self.listing_status.set(f"{len(rows)} listing(s) disponible(s) pour {quarter} {year}.")
        if not rows:messagebox.showinfo("Listings","Aucun listing standardisé n’est disponible pour cette période.")

    def _set_listing_source_state(self,execution,selected):
        if not self.listing_source_tree.exists(execution):return
        if selected:self.listing_selected_sources.add(execution)
        else:self.listing_selected_sources.discard(execution)
        values=list(self.listing_source_tree.item(execution,"values"));values[0]="Oui" if selected else "Non"
        self.listing_source_tree.item(execution,values=values)

    def _listing_selection_status(self):
        self.listing_status.set(f"{len(self.listing_selected_sources)} source(s) sélectionnée(s) sur {len(self.listing_source_tree.get_children())}.")

    def _toggle_listing_source(self,event=None):
        execution=self.listing_source_tree.identify_row(event.y) if event else ""
        if not execution:
            chosen=self.listing_source_tree.selection()
            if not chosen:return
            execution=chosen[0]
        self._set_listing_source_state(execution,execution not in self.listing_selected_sources)
        self._listing_selection_status()

    def _set_chosen_listing_sources(self,selected):
        chosen=self.listing_source_tree.selection()
        if not chosen:messagebox.showwarning("Sources","Sélectionnez d’abord une ou plusieurs lignes.");return
        for execution in chosen:self._set_listing_source_state(execution,selected)
        self._listing_selection_status()

    def _set_all_listing_sources(self,selected):
        for execution in self.listing_source_tree.get_children():self._set_listing_source_state(execution,selected)
        self._listing_selection_status()

    def _preview_listing_sources(self):
        try:
            quarter,year=self._listing_period()
            if not self.listing_selected_sources:raise ValueError("Sélectionnez au moins un listing.")
            diagnosis=self.listing_analysis.preview(quarter,year,list(self.listing_selected_sources))
            self.listing_diagnosis=diagnosis
            for item in diagnosis:
                values=list(self.listing_source_tree.item(item["execution_id"],"values"))
                values[5]=item["retained"]
                values[6]="; ".join(f"{f[1]} {f[2]} {f[3]}" for f in item["filters"]) if item["filters"] else "Aucun filtre"
                values[7]="Prêt" if item["ready"] else "; ".join(item["issues"])
                self.listing_source_tree.item(item["execution_id"],values=values,tags=("ready" if item["ready"] else "error",))
            self.listing_source_tree.tag_configure("ready",foreground="#176B3A")
            self.listing_source_tree.tag_configure("error",foreground="#B42318")
            retained=sum(item["retained"] for item in diagnosis);available=sum(item["available"] for item in diagnosis)
            self.listing_status.set(f"Projection du groupe : {retained:,}/{available:,} lignes — {'Prête' if all(i['ready'] for i in diagnosis) else 'À corriger'}.".replace(","," "))
            return diagnosis
        except Exception as exc:
            self.listing_diagnosis=None;messagebox.showwarning("Vérification impossible",str(exc));return None

    def _edit_listing_source_filters(self):
        chosen=self.listing_source_tree.selection()
        if len(chosen)!=1:messagebox.showwarning("Filtres","Sélectionnez exactement une source.");return
        values=self.listing_source_tree.item(chosen[0],"values")
        self.match_scope["institution"].set(values[1]);self.match_scope["regime"].set(values[2])
        self._refresh_treatment_filters();self.matching_tabs.select(self.standard_matching_tab)
        messagebox.showinfo("Filtres","Modifiez les filtres du listing, puis revenez dans Analyse groupée des listings et cliquez sur Vérifier le groupe.")

    def _show_listing_source_sample(self):
        chosen=self.listing_source_tree.selection()
        if len(chosen)!=1:messagebox.showwarning("Échantillon","Sélectionnez exactement une source.");return
        try:columns,rows=self.listing_analysis.sample_source(chosen[0],50)
        except Exception as exc:self._show_explicit_error(exc,"Échantillon du groupe de listings",traceback.format_exc());return
        window=tk.Toplevel(self);window.title("Échantillon du listing après filtres")
        body=ttk.Frame(window,padding=10);body.pack(fill="both",expand=True)
        ttk.Label(body,text=f"{len(rows)} ligne(s) affichée(s), 50 maximum",style="PageHint.TLabel").pack(anchor="w",pady=(0,6))
        frame=ttk.Frame(body);frame.pack(fill="both",expand=True)
        tree=ttk.Treeview(frame,columns=columns,show="headings")
        for column in columns:tree.heading(column,text=column);tree.column(column,width=145,anchor="w",stretch=False)
        for row in rows:tree.insert("","end",values=row)
        sy=ttk.Scrollbar(frame,orient="vertical",command=tree.yview);sx=ttk.Scrollbar(frame,orient="horizontal",command=tree.xview)
        tree.configure(yscrollcommand=sy.set,xscrollcommand=sx.set)
        tree.grid(row=0,column=0,sticky="nsew");sy.grid(row=0,column=1,sticky="ns");sx.grid(row=1,column=0,sticky="ew")
        frame.columnconfigure(0,weight=1);frame.rowconfigure(0,weight=1)
        ttk.Button(body,text="Fermer",command=window.destroy).pack(anchor="e",pady=(8,0))
        window.after_idle(lambda:self._center_child_window(window,1050,580))

    def _run_listing_analysis(self):
        if not self._require_active_trial("l’analyse groupée des listings"):return
        try:
            name=self.listing_group_name.get().strip();quarter,year=self._listing_period()
            if not name:raise ValueError("Donnez un nom au groupe.")
            diagnosis=self._preview_listing_sources()
            if not diagnosis:return
            if not all(item["ready"] for item in diagnosis):raise ValueError("Corrigez les sources signalées.")
        except ValueError as exc:messagebox.showwarning("Analyse incomplète",str(exc));return
        regimes=", ".join(sorted({item["regime"] for item in diagnosis}))
        confirmation=(f"Groupe : {name}\nPériode : {quarter} {year}\nSources : {len(diagnosis)}\n"
            f"Régimes : {regimes}\nLignes retenues : {sum(i['retained'] for i in diagnosis):,}\n\n"
            "Constituer cette base et lancer l’analyse ?").replace(","," ")
        if not messagebox.askyesno("Confirmer l’analyse des listings",confirmation):return
        self._open_generation_dialog("Analyse groupée des listings",
            "Fusion des sources filtrées et analyse des doublons, paiements multi-régimes et multi-institutions.",
            "Étapes de l’analyse",True)
        self._background(lambda:self.listing_analysis.run(name,quarter,year,
            list(self.listing_selected_sources),progress=self._progress),self._listing_analysis_completed,
            refresh_data=True)

    def _listing_analysis_completed(self,result):
        self.listing_last_group=result["group_id"];self.listing_export_button.configure(state="normal")
        self.listing_result_tree.delete(*self.listing_result_tree.get_children())
        for row in result["summary"]:
            self.listing_result_tree.insert("","end",values=(row[0],row[1],row[2],
                f"{row[3]:,.2f}".replace(","," "),f"{row[4]:,.2f}".replace(","," ")))
        self._refresh_listing_regime_summary(result["group_id"])
        self.listing_status.set(f"Base constituée et analysée : {result['base_rows']:,} lignes.".replace(","," "))
        if self.generation_window and self.generation_window.winfo_exists():
            self.generation_title.set("Analyse des listings terminée");self.generation_status.set("Les résultats peuvent maintenant être exportés.")
            self.generation_close.configure(state="normal")
        messagebox.showinfo("Analyse terminée","La base groupée et ses contrôles ont été constitués.")

    def _export_listing_analysis(self):
        if not self.listing_last_group:messagebox.showwarning("Export","Lancez ou chargez d’abord une analyse.");return
        folder=filedialog.askdirectory(title="Choisir le dossier des résultats")
        if not folder:return
        self._open_generation_dialog("Rapport de l’analyse groupée",
            "Génération progressive du rapport, des annexes, des effectifs et de la lettre.",
            "Fichiers générés",True)
        self._background(lambda:self.listing_analysis.export(self.listing_last_group,folder,
            progress=self._progress),self._listing_export_completed)

    def _listing_export_completed(self,path):
        if self.generation_window and self.generation_window.winfo_exists():
            self.generation_title.set("Export terminé");self.generation_status.set(f"Dossier créé : {path}")
            self.generation_close.configure(state="normal")
        messagebox.showinfo("Export terminé",f"Le rapport, les annexes, les effectifs et la lettre sont disponibles dans :\n{path}")

    def _open_listing_history(self):
        window=tk.Toplevel(self);window.title("Historique des analyses groupées de listings");window.transient(self)
        body=ttk.Frame(window,padding=12);body.pack(fill="both",expand=True)
        columns=("name","period","status","rows","created","folder")
        self.listing_history_tree=ttk.Treeview(body,columns=columns,show="headings",height=13)
        for column,title,width in [("name","Groupe",230),("period","Période",90),("status","État",100),
                ("rows","Lignes",90),("created","Créé le",150),("folder","Dossier export",300)]:
            self.listing_history_tree.heading(column,text=title);self.listing_history_tree.column(column,width=width,anchor="w")
        self.listing_history_tree.pack(fill="both",expand=True,pady=(0,8))
        actions=ttk.Frame(body);actions.pack(fill="x")
        ttk.Button(actions,text="Actualiser",command=self._refresh_listing_history).pack(side="left")
        ttk.Button(actions,text="Archiver",command=self._archive_listing_group).pack(side="left",padx=5)
        ttk.Button(actions,text="Ouvrir le dossier",command=self._open_listing_folder).pack(side="right")
        ttk.Button(actions,text="Réexporter",style="Primary.TButton",command=self._reexport_listing_group).pack(side="right",padx=5)
        ttk.Button(actions,text="Charger les résultats",style="Secondary.TButton",command=self._load_listing_group).pack(side="right")
        self._refresh_listing_history();window.after_idle(lambda:self._center_child_window(window,1050,550))

    def _refresh_listing_history(self):
        if not hasattr(self,"listing_history_tree") or not self.listing_history_tree.winfo_exists():return
        self.listing_history_tree.delete(*self.listing_history_tree.get_children())
        for group,name,quarter,year,status,rows,created,_ended,folder,_archived in self.listing_analysis.list_groups():
            stamp=created.strftime("%d/%m/%Y %H:%M") if created else ""
            self.listing_history_tree.insert("","end",iid=group,values=(name,f"{quarter} {year}",status,rows,stamp,folder or ""))

    def _selected_listing_group(self):
        chosen=self.listing_history_tree.selection() if hasattr(self,"listing_history_tree") else ()
        if not chosen:raise ValueError("Sélectionnez un groupe dans l’historique.")
        return chosen[0]

    def _load_listing_group(self):
        try:group=self._selected_listing_group();summary=self.listing_analysis.summary(group)
        except ValueError as exc:messagebox.showwarning("Historique",str(exc));return
        self.listing_last_group=group;self.listing_export_button.configure(state="normal")
        self.listing_result_tree.delete(*self.listing_result_tree.get_children())
        for row in summary:self.listing_result_tree.insert("","end",values=(row[0],row[1],row[2],
            f"{row[3]:,.2f}".replace(","," "),f"{row[4]:,.2f}".replace(","," ")))
        self._refresh_listing_regime_summary(group)
        self.listing_status.set("Résultats historiques chargés.")

    def _archive_listing_group(self):
        try:group=self._selected_listing_group()
        except ValueError as exc:messagebox.showwarning("Historique",str(exc));return
        if messagebox.askyesno("Archiver","Archiver ce groupe ? Ses données resteront conservées."):
            self.listing_analysis.archive_group(group);self._refresh_listing_history()

    def _reexport_listing_group(self):
        try:self.listing_last_group=self._selected_listing_group()
        except ValueError as exc:messagebox.showwarning("Historique",str(exc));return
        self.listing_export_button.configure(state="normal");self._export_listing_analysis()

    def _open_listing_folder(self):
        try:group=self._selected_listing_group()
        except ValueError as exc:messagebox.showwarning("Historique",str(exc));return
        row=next((item for item in self.listing_analysis.list_groups(True) if item[0]==group),None)
        folder=row[8] if row else ""
        if not folder or not Path(folder).exists():messagebox.showwarning("Dossier indisponible","Ce groupe n’a pas encore été exporté ou son dossier a été déplacé.");return
        self._open_runtime_path(Path(folder))

    def _run_matching(self):
        if not self._require_active_trial("le rapprochement"):return
        args=self._validated_scope(self.match_scope)
        if args is None:return
        try:formula_id=self._matching_impact_formula_id()
        except ValueError as exc:messagebox.showwarning("Formule d’impact",str(exc));return
        self._background(lambda:self.matching.run(*args,progress=self._progress,
            impact_formula_id=formula_id),
            lambda run_id:self._matching_completed(run_id,args,formula_id),refresh_data=True,
            operation="Rapprochement institutionnel")
    def _matching_completed(self,run_id,args,formula_id=""):
        self.status.set("Génération automatique du rapport, de la lettre et des annexes…")
        self._open_generation_dialog("Génération du rapport, de la lettre et des annexes")
        self._background(lambda:self.reports.generate_package(str(self.config_data.results_dir),
            *args,progress=self._progress,impact_formula_id=formula_id),self._package_completed)
    def _package_completed(self,path):
        if self.generation_window and self.generation_window.winfo_exists():
            self.generation_title.set("Génération terminée avec succès")
            self.generation_status.set(f"Dossier créé : {path}")
            self.generation_bar["value"]=100
            self.generation_close.configure(state="normal")
        messagebox.showinfo("Traitement terminé",f"Le rapprochement, le rapport final, la lettre d’interprétation et les annexes ont été générés dans :\n{path}")
    def _export_report(self):
        if not self._require_active_trial("la génération du rapport"):return
        args=self._validated_scope(self.match_scope)
        if args is None:return
        try:formula_id=self._matching_impact_formula_id()
        except ValueError as exc:messagebox.showwarning("Formule d’impact",str(exc));return
        folder=filedialog.askdirectory(title="Choisir le dossier des résultats")
        if folder:
            self._open_generation_dialog("Génération du rapport, de la lettre et des annexes")
            self._background(lambda:self.reports.generate_package(folder,*args,
                progress=self._progress,impact_formula_id=formula_id),self._package_completed)
    def _add_institution(self):
        if not self.inst_code.get().strip() or not self.inst_name.get().strip(): return
        self.db.add_institution(self.inst_code.get().strip().upper(),self.inst_name.get().strip()); self._refresh_all_institutions(); self._refresh_dashboard(); self.inst_code.set("");self.inst_name.set("")

    def _delete_institution(self):
        code=self.inst_code.get().strip().upper();
        if not code:
            messagebox.showwarning("Institution","Saisissez un code d’institution à supprimer.");return
        rows=self.db.list_institutions();
        match=next((row for row in rows if row[1]==code),None)
        if match is None:
            messagebox.showwarning("Institution","Aucune institution active ne correspond à ce code.");return
        if messagebox.askyesno("Supprimer l’institution",f"Supprimer définitivement l’institution {match[2]} et ses paramètres associés ?"):
            self.db.delete_institution(match[0]); self._refresh_all_institutions(); self._refresh_dashboard(); self.inst_code.set("");self.inst_name.set("")

    def _delete_financial_component(self):
        code=self.component_code.get().strip().upper();
        if not code:
            messagebox.showwarning("Composante","Saisissez un code de composante à supprimer.");return
        if messagebox.askyesno("Supprimer la composante",f"Supprimer la composante {code} ?"):
            self.db.delete_financial_component(code); self.component_code.set("");self.component_label.set(""); self._refresh_available_formula_fields();

    def _delete_impact_formula(self):
        selected=self.formula_tree.selection();
        if not selected:return
        if selected[0]=="FORMULE_DEFAUT":
            messagebox.showinfo("Formule système","La formule par défaut ne peut pas être supprimée.");return
        if messagebox.askyesno("Supprimer la version","Supprimer cette version de formule ?"):
            self.db.delete_impact_formula(selected[0]); self._refresh_formula_tree(); self._refresh_matching_formula_choices();

    def _open_generation_dialog(self,title,description="Ne fermez pas l’application pendant l’écriture des fichiers Excel et Word.",list_title="Fichiers générés",log_progress=False):
        if self.generation_window and self.generation_window.winfo_exists():self.generation_window.destroy()
        window=self.generation_window=tk.Toplevel(self);window.title(title);window.geometry("720x460");window.minsize(620,380);window.transient(self)
        header=tk.Frame(window,background="#12355B",padx=20,pady=16);header.pack(fill="x")
        self.generation_title=tk.StringVar(value=title);tk.Label(header,textvariable=self.generation_title,background="#12355B",foreground="white",font=("DejaVu Sans",15,"bold")).pack(anchor="w")
        tk.Label(header,text=description,background="#12355B",foreground="#CFE2F3",wraplength=660,justify="left").pack(anchor="w",pady=(3,0))
        body=ttk.Frame(window,padding=20);body.pack(fill="both",expand=True)
        self.generation_status=tk.StringVar(value="Initialisation…");ttk.Label(body,textvariable=self.generation_status,style="PageHint.TLabel").pack(anchor="w",pady=(0,8))
        self.generation_bar=ttk.Progressbar(body,maximum=100,mode="indeterminate");self.generation_bar.pack(fill="x",pady=(0,15));self.generation_bar.start(12)
        self.generation_log_progress=log_progress;self.generation_seen_status=set()
        ttk.Label(body,text=list_title,style="PageTitle.TLabel").pack(anchor="w",pady=(0,6))
        list_frame=ttk.Frame(body);list_frame.pack(fill="both",expand=True)
        self.generated_files=tk.Listbox(list_frame,bg="white",fg="#243247",font=("DejaVu Sans",10),relief="solid",borderwidth=1,activestyle="none")
        scroll=ttk.Scrollbar(list_frame,orient="vertical",command=self.generated_files.yview);self.generated_files.configure(yscrollcommand=scroll.set);self.generated_files.pack(side="left",fill="both",expand=True);scroll.pack(side="right",fill="y")
        self.generation_close=ttk.Button(body,text="Fermer",style="Primary.TButton",state="disabled",command=window.destroy);self.generation_close.pack(anchor="e",pady=(12,0))
        window.protocol("WM_DELETE_WINDOW",lambda:messagebox.showwarning("Traitement en cours","Attendez la fin de la génération avant de fermer cette fenêtre."));window.after_idle(lambda:self._center_child_window(window,720,460))

    def _update_generation_dialog(self,value,text):
        if not self.generation_window or not self.generation_window.winfo_exists():return
        if value<0:
            self.generation_bar.stop();self.generation_bar.configure(mode="indeterminate");self.generation_bar.start(12);self.generation_status.set(f"Traitement en cours — {text}")
        else:
            self.generation_bar.stop();self.generation_bar.configure(mode="determinate");self.generation_bar["value"]=value;self.generation_status.set(f"{value}% — {text}")
        if getattr(self,"generation_log_progress",False) and text not in self.generation_seen_status:
            self.generation_seen_status.add(text);symbol="✓" if value==100 else "•";self.generated_files.insert("end",f"{symbol}  {text}");self.generated_files.see("end")
        elif text.startswith("Fichier généré :"):
            filename=text.split(":",1)[1].strip();self.generated_files.insert("end",f"✓  {filename}");self.generated_files.see("end")
        if value==100:
            self.generation_close.configure(state="normal")
            self.generation_window.protocol("WM_DELETE_WINDOW",self.generation_window.destroy)

    def _generation_failed(self,error):
        if self.generation_window and self.generation_window.winfo_exists():
            self.generation_bar.stop();self.generation_bar.configure(mode="determinate");self.generation_title.set("Le traitement a rencontré une erreur");self.generation_status.set(str(error));self.generation_close.configure(state="normal")
            self.generation_window.protocol("WM_DELETE_WINDOW",self.generation_window.destroy)

    def _request_close(self):
        if self.busy:
            messagebox.showwarning("Traitement en cours",
                "SICORPA écrit ou analyse encore des données. Attendez la fin du traitement avant de fermer l’application.")
            return
        self.destroy()

    def _set_busy_ui(self,busy):
        try:self.notebook.state(["disabled"] if busy else ["!disabled"])
        except tk.TclError:pass
        self.configure(cursor="watch" if busy else "")

    def _progress(self,value,text):
        now=time.monotonic();force=value==100 or value<0 or text.startswith("Fichier généré :")
        with self._progress_lock:
            previous_time,previous_value,previous_text=self._last_progress_emit
            if not force and now-previous_time<0.12:
                return
            if not force and value==previous_value and text==previous_text:
                return
            self._last_progress_emit=(now,value,text)
        self.events.put(("progress",(value,text)))

    def _background(self,task,success,refresh_data=False,operation=""):
        if self.busy:
            messagebox.showwarning("Traitement en cours","Attendez la fin du traitement actuel avant d’en lancer un autre.")
            return False
        if not operation:
            operation=(self.generation_title.get() if self.generation_window
                       and self.generation_window.winfo_exists() else "Traitement SICORPA")
        self.busy=True;self._set_busy_ui(True);self.status.set("Traitement en cours…");self.progress.stop();self.progress.configure(mode="indeterminate");self.progress.start(12)
        def worker():
            try:self.events.put(("success",(success,task(),refresh_data)))
            except Exception as exc:
                logging.exception("Échec d’un traitement en arrière-plan")
                self.events.put(("error",(exc,traceback.format_exc(),operation)))
        threading.Thread(target=worker,daemon=True).start()
        return True

    def _poll_events(self):
        try:
            processed=0
            while True:
                kind,payload=self.events.get_nowait()
                processed+=1
                if kind=="progress":
                    value,text=payload;self.status.set(text)
                    if value<0:self.progress.stop();self.progress.configure(mode="indeterminate");self.progress.start(12)
                    else:self.progress.stop();self.progress.configure(mode="determinate");self.progress["value"]=value
                    self._update_generation_dialog(value,text)
                elif kind=="success":
                    callback,result,refresh_data=payload
                    self.busy=False;self._set_busy_ui(False);self.status.set("Prêt");self.progress.stop();self.progress.configure(mode="determinate");self.progress["value"]=100
                    if refresh_data:
                        try:self._refresh_dashboard();self._refresh_explorer_tables()
                        except Exception:logging.exception("Échec du rafraîchissement de l’interface")
                    try:callback(result)
                    except Exception as exc:
                        logging.exception("Échec de la finalisation d’un traitement")
                        self._show_explicit_error(exc,"Finalisation du traitement",traceback.format_exc())
                else:
                    error,traceback_text,operation=payload
                    self.busy=False;self._set_busy_ui(False);self.status.set("Erreur");self.progress.stop();self.progress.configure(mode="determinate")
                    report=explain_error(error,traceback_text,operation)
                    self._generation_failed(report.summary)
                    self._show_explicit_error(error,operation,traceback_text)
                if processed>=100:break
        except queue.Empty:pass
        self.after(10 if not self.events.empty() else 100,self._poll_events)
