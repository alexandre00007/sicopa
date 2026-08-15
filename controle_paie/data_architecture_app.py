from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from .data_architecture import (
    DataQualityService,
    ObservedIngestionProxy,
    RawCatalogService,
    TreatmentJournalService,
    migrate_governance,
)
from .export_reliability_app import PayrollAppWithReliableExports
from .sql_console import SqlConsoleService


class CatalogSqlConsoleService(SqlConsoleService):
    """Console SQL utilisant le catalogue RAW au lieu de recompter toutes les tables."""
    def __init__(self, db, catalog):
        super().__init__(db)
        self.catalog = catalog

    def list_raw_tables(self):
        return self.catalog.list()


class PayrollAppWithDataArchitecture(PayrollAppWithReliableExports):
    """Point d'entree Lot 2 : migrations, catalogue, qualite et journal transversal."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        migrate_governance(self.db)
        self.data_quality_service = DataQualityService(self.db)
        self.raw_catalog_service = RawCatalogService(self.db)
        self.treatment_journal_service = TreatmentJournalService(self.db)
        self.ingestion = ObservedIngestionProxy(
            self.ingestion, self.db, self.data_quality_service, self.raw_catalog_service
        )
        self.sql_console_service = CatalogSqlConsoleService(self.db, self.raw_catalog_service)
        try:
            self.data_quality_service.backfill(100)
            self.raw_catalog_service.refresh()
        except Exception:
            pass
        self._add_data_governance_tab()
        try:
            if hasattr(self, "_refresh_sql_tables"):
                self._refresh_sql_tables()
            self._refresh_data_governance()
        except Exception:
            pass

    def _add_data_governance_tab(self):
        outer, body = self._make_scrollable_tab()
        self.data_governance_page = body
        self._tab_shells["data_governance_page"] = outer
        self.notebook.add(outer, text="  Qualité & RAW  ")
        self._page_heading(
            body,
            "Qualité des données & catalogue RAW",
            "Contrôlez la qualité des imports, les RAW disponibles et l'historique technique des traitements.",
        )

        actions = ttk.Frame(body)
        actions.pack(fill="x", pady=(0, 10))
        ttk.Button(actions, text="Actualiser", style="Primary.TButton",
                   command=self._refresh_data_governance).pack(side="left")
        ttk.Button(actions, text="Recalculer les imports récents", style="Secondary.TButton",
                   command=self._backfill_data_quality).pack(side="left", padx=6)
        self.data_governance_status = tk.StringVar(value="")
        ttk.Label(actions, textvariable=self.data_governance_status, style="PageHint.TLabel").pack(side="left", padx=12)

        raw_box = ttk.LabelFrame(body, text="Catalogue RAW", style="Section.TLabelframe", padding=10)
        raw_box.pack(fill="both", expand=True, pady=(0, 10))
        raw_cols = ("table","type","periode","regimes","institutions","lignes","colonnes","score","niveau")
        self.raw_catalog_tree = ttk.Treeview(raw_box, columns=raw_cols, show="headings", height=8)
        raw_headers = {
            "table":"RAW", "type":"Type", "periode":"Période", "regimes":"Régimes",
            "institutions":"Institutions", "lignes":"Lignes", "colonnes":"Colonnes",
            "score":"Score", "niveau":"Qualité",
        }
        for col in raw_cols:
            self.raw_catalog_tree.heading(col, text=raw_headers[col])
            self.raw_catalog_tree.column(col, width=110 if col != "table" else 250, anchor="w")
        ry = ttk.Scrollbar(raw_box, orient="vertical", command=self.raw_catalog_tree.yview)
        rx = ttk.Scrollbar(raw_box, orient="horizontal", command=self.raw_catalog_tree.xview)
        self.raw_catalog_tree.configure(yscrollcommand=ry.set, xscrollcommand=rx.set)
        self.raw_catalog_tree.grid(row=0, column=0, sticky="nsew"); ry.grid(row=0, column=1, sticky="ns"); rx.grid(row=1, column=0, sticky="ew")
        raw_box.rowconfigure(0, weight=1); raw_box.columnconfigure(0, weight=1)

        quality_box = ttk.LabelFrame(body, text="Qualité des imports", style="Section.TLabelframe", padding=10)
        quality_box.pack(fill="both", expand=True, pady=(0, 10))
        qcols = ("execution","source","destination","lignes","mat","nom","dup_mat","dup_nom","score","niveau","date")
        self.quality_tree = ttk.Treeview(quality_box, columns=qcols, show="headings", height=8)
        qheaders = {
            "execution":"Exécution", "source":"Source", "destination":"Destination", "lignes":"Lignes",
            "mat":"Matricules %", "nom":"Noms %", "dup_mat":"Rép. matricule", "dup_nom":"Rép. nom",
            "score":"Score", "niveau":"Niveau", "date":"Calculé le",
        }
        for col in qcols:
            self.quality_tree.heading(col, text=qheaders[col])
            self.quality_tree.column(col, width=110 if col != "execution" else 220, anchor="w")
        qy = ttk.Scrollbar(quality_box, orient="vertical", command=self.quality_tree.yview)
        qx = ttk.Scrollbar(quality_box, orient="horizontal", command=self.quality_tree.xview)
        self.quality_tree.configure(yscrollcommand=qy.set, xscrollcommand=qx.set)
        self.quality_tree.grid(row=0, column=0, sticky="nsew"); qy.grid(row=0, column=1, sticky="ns"); qx.grid(row=1, column=0, sticky="ew")
        quality_box.rowconfigure(0, weight=1); quality_box.columnconfigure(0, weight=1)

        journal_box = ttk.LabelFrame(body, text="Journal des traitements", style="Section.TLabelframe", padding=10)
        journal_box.pack(fill="both", expand=True)
        jcols = ("operation","statut","debut","fin","duree","lignes","objet","message")
        self.treatment_tree = ttk.Treeview(journal_box, columns=jcols, show="headings", height=7)
        jheaders = {"operation":"Opération","statut":"Statut","debut":"Début","fin":"Fin","duree":"Durée s","lignes":"Lignes","objet":"Objet","message":"Message"}
        for col in jcols:
            self.treatment_tree.heading(col, text=jheaders[col])
            self.treatment_tree.column(col, width=120 if col != "message" else 320, anchor="w")
        jy = ttk.Scrollbar(journal_box, orient="vertical", command=self.treatment_tree.yview)
        jx = ttk.Scrollbar(journal_box, orient="horizontal", command=self.treatment_tree.xview)
        self.treatment_tree.configure(yscrollcommand=jy.set, xscrollcommand=jx.set)
        self.treatment_tree.grid(row=0, column=0, sticky="nsew"); jy.grid(row=0, column=1, sticky="ns"); jx.grid(row=1, column=0, sticky="ew")
        journal_box.rowconfigure(0, weight=1); journal_box.columnconfigure(0, weight=1)

    def _backfill_data_quality(self):
        count = self.data_quality_service.backfill(500)
        self.raw_catalog_service.refresh()
        self._refresh_data_governance()
        self.data_governance_status.set(f"{count} import(s) recalculé(s).")

    def _refresh_data_governance(self):
        if not hasattr(self, "raw_catalog_tree"):
            return
        for tree in (self.raw_catalog_tree, self.quality_tree, self.treatment_tree):
            tree.delete(*tree.get_children())
        raw_rows = self.raw_catalog_service.list_detailed()
        for row in raw_rows:
            table, typ, quarter, year, regimes, institutions, lines, columns, score, level, _updated = row
            period = f"{quarter or ''} {year or ''}".strip()
            self.raw_catalog_tree.insert("", "end", values=(table,typ,period,regimes or "",institutions or "",
                lines,columns,"" if score is None else score,level or "NON_CALCULEE"))
        for row in self.data_quality_service.list_recent(300):
            execution, source, destination, lines, mat, name, dup_mat, dup_name, score, level, date = row
            self.quality_tree.insert("", "end", values=(execution,source,destination,lines,
                f"{float(mat or 0):.1f}",f"{float(name or 0):.1f}",dup_mat,dup_name,
                f"{float(score or 0):.1f}",level,date))
        for row in self.treatment_journal_service.list_recent(300):
            self.treatment_tree.insert("", "end", values=row)
        self.data_governance_status.set(
            f"{len(raw_rows)} RAW catalogué(s) — qualité et traitements centralisés."
        )

    def _raw_quality_decision(self, tables: list[str]) -> bool:
        with self.db.connect() as con:
            rows = con.execute("""SELECT table_name,niveau_qualite,score_qualite FROM catalogue_raw
                WHERE table_name IN (SELECT UNNEST(?))""", [tables]).fetchall()
        blocked = [name for name, level, _score in rows if level == "INEXPLOITABLE_POUR_MATCHING"]
        if blocked:
            messagebox.showerror(
                "Qualité insuffisante",
                "Analyse bloquée : aucune identité exploitable dans " + ", ".join(blocked) + ".\n\n"
                "Consultez l'onglet Qualité & RAW avant de relancer.",
            )
            return False
        weak = [(name, score) for name, level, score in rows if level == "FAIBLE"]
        if weak:
            detail = "\n".join(f"• {name} — score {float(score or 0):.1f}/100" for name, score in weak)
            return messagebox.askyesno(
                "Qualité faible",
                "La comparaison peut produire beaucoup de correspondances incertaines :\n\n"
                + detail + "\n\nContinuer malgré tout ?",
            )
        return True

    def _rpc_analyze(self):
        a = self.rpc_table_a.get().strip() if hasattr(self, "rpc_table_a") else ""
        b = self.rpc_table_b.get().strip() if hasattr(self, "rpc_table_b") else ""
        if a and b and not self._raw_quality_decision([a, b]):
            return
        return super()._rpc_analyze()

    def _background(self, task, success, refresh_data=False, operation=""):
        journal = getattr(self, "treatment_journal_service", None)
        if journal is None:
            return super()._background(task, success, refresh_data=refresh_data, operation=operation)
        token = journal.start(operation or "Traitement SICORPA")

        def observed_task():
            try:
                result = task()
                journal.finish(token, result)
                label = (operation or "").lower()
                if any(word in label for word in ("import", "fusion", "suppression", "chargement")):
                    try:
                        self.raw_catalog_service.refresh()
                    except Exception:
                        pass
                return result
            except Exception as exc:
                journal.fail(token, exc)
                raise

        started = super()._background(observed_task, success, refresh_data=refresh_data, operation=operation)
        if not started:
            try:
                journal.fail(token, RuntimeError("Traitement non lance : application deja occupee"))
            except Exception:
                pass
        return started
