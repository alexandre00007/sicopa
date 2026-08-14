from __future__ import annotations

from pathlib import Path
from tkinter import messagebox, ttk

from .runtime import backup_database
from .ui import PayrollApp, validate_scope_values


class PayrollDeletionService:
    """Suppression auditable d'un perimetre de paie sans toucher au declaratif."""

    def __init__(self, db):
        self.db = db

    def inspect_scope(self, institution_id: str, regime: str, quarter: str, year: int) -> dict:
        params = [institution_id, regime, quarter, int(year)]
        where = "institution_id=? AND regime=? AND trimestre=? AND annee=?"
        with self.db.connect() as con:
            rows = int(con.execute(f"SELECT COUNT(*) FROM paie_standardisee WHERE {where}", params).fetchone()[0])
            executions = [row[0] for row in con.execute(
                f"SELECT DISTINCT execution_id FROM paie_standardisee WHERE {where} AND execution_id IS NOT NULL", params
            ).fetchall()]
            matching = int(con.execute(
                """SELECT COUNT(DISTINCT r.execution_id) FROM resultats_rapprochement r
                   JOIN paie_standardisee p ON p.ligne_paie_id=r.ligne_paie_id
                   WHERE p.institution_id=? AND p.regime=? AND p.trimestre=? AND p.annee=?""", params
            ).fetchone()[0])
            multi = 0
            listing = 0
            if executions:
                placeholders = ",".join("?" for _ in executions)
                multi = int(con.execute(
                    f"SELECT COUNT(*) FROM sources_analyse_multi WHERE execution_id IN ({placeholders})", executions
                ).fetchone()[0])
                listing = int(con.execute(
                    f"SELECT COUNT(*) FROM sources_analyse_listing WHERE execution_id IN ({placeholders})", executions
                ).fetchone()[0])
        return {"rows": rows, "executions": executions, "matching": matching, "multi": multi, "listing": listing}

    def delete_scope(self, institution_id: str, regime: str, quarter: str, year: int) -> dict:
        info = self.inspect_scope(institution_id, regime, quarter, year)
        if not info["rows"]:
            raise ValueError("Aucune donnee de paie n'existe pour ce perimetre.")
        usages = []
        if info["matching"]:
            usages.append(f"{info['matching']} rapprochement(s)")
        if info["multi"]:
            usages.append(f"{info['multi']} analyse(s) multi-regimes")
        if info["listing"]:
            usages.append(f"{info['listing']} analyse(s) groupee(s) de listings")
        if usages:
            raise ValueError(
                "Suppression bloquee : ces donnees sont utilisees par " + ", ".join(usages) +
                ". Supprimez ou archivez d'abord les traitements dependants afin de conserver la tracabilite."
            )

        executions = info["executions"]
        params = [institution_id, regime, quarter, int(year)]
        with self.db.connect() as con:
            con.execute("BEGIN")
            try:
                if executions:
                    placeholders = ",".join("?" for _ in executions)
                    raw_tables = con.execute(
                        f"""SELECT DISTINCT table_destination FROM journal_executions
                            WHERE execution_id IN ({placeholders}) AND type_operation='IMPORT_ACCESS'
                              AND table_destination IS NOT NULL""", executions
                    ).fetchall()
                    for (table_name,) in raw_tables:
                        safe = str(table_name).replace('"', '""')
                        exists = con.execute(
                            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name=?", [table_name]
                        ).fetchone()[0]
                        if exists:
                            con.execute(f'DELETE FROM "{safe}" WHERE execution_id IN ({placeholders})', executions)
                    con.execute(f"DELETE FROM rejets_importation WHERE execution_id IN ({placeholders})", executions)
                    con.execute(f"DELETE FROM schemas_sources WHERE execution_id IN ({placeholders})", executions)
                    con.execute(
                        f"""UPDATE journal_executions SET statut='SUPPRIME',
                            message='Donnees de paie supprimees par utilisateur',date_fin=CURRENT_TIMESTAMP
                            WHERE execution_id IN ({placeholders})""", executions
                    )
                con.execute(
                    "DELETE FROM paie_standardisee WHERE institution_id=? AND regime=? AND trimestre=? AND annee=?", params
                )
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
        return info


class PayrollAppWithPayrollDeletion(PayrollApp):
    """PayrollApp enrichie d'une suppression securisee dans l'onglet Paie Access."""

    def __init__(self, *args, **kwargs):
        self.payroll_deletion = None
        super().__init__(*args, **kwargs)
        self.payroll_deletion = PayrollDeletionService(self.db)

    def _build_access(self):
        super()._build_access()
        self.payroll_deletion = PayrollDeletionService(self.db)
        notebooks = [child for child in self.access_page.winfo_children() if isinstance(child, ttk.Notebook)]
        if not notebooks:
            return
        source_tabs = notebooks[0]
        for tab_id in source_tabs.tabs():
            tab = source_tabs.nametowidget(tab_id)
            actions = ttk.Frame(tab)
            actions.grid(row=5, column=0, columnspan=4, sticky="ew", padx=5, pady=(10, 0))
            ttk.Label(
                actions,
                text="Gestion du perimetre charge : la suppression ne touche pas au declaratif.",
                style="PageHint.TLabel",
            ).pack(side="left")
            ttk.Button(
                actions,
                text="Supprimer les donnees de paie du perimetre",
                style="Secondary.TButton",
                command=self._delete_payroll_scope,
            ).pack(side="right")

    def _delete_payroll_scope(self):
        try:
            institution_name, regime, quarter, year = validate_scope_values(
                self.access_scope["institution"].get(), self.access_scope["regime"].get(),
                self.access_scope["quarter"].get(), self.access_scope["year"].get()
            )
        except ValueError as exc:
            messagebox.showwarning("Suppression de la paie", str(exc))
            return
        institution_id = self.institution_ids_by_name.get(institution_name)
        if not institution_id:
            messagebox.showwarning("Suppression de la paie", "Institution introuvable dans la base.")
            return
        info = self.payroll_deletion.inspect_scope(institution_id, regime, quarter, year)
        if not info["rows"]:
            messagebox.showinfo("Suppression de la paie", "Aucune donnee de paie n'existe pour ce perimetre.")
            return
        if info["matching"] or info["multi"] or info["listing"]:
            usages = []
            if info["matching"]: usages.append(f"{info['matching']} rapprochement(s)")
            if info["multi"]: usages.append(f"{info['multi']} analyse(s) multi-regimes")
            if info["listing"]: usages.append(f"{info['listing']} analyse(s) groupee(s)")
            messagebox.showwarning(
                "Suppression bloquee",
                "Ces donnees sont deja utilisees par " + ", ".join(usages) + ".\n\nLa suppression est bloquee pour conserver la tracabilite."
            )
            return
        question = (
            f"Supprimer definitivement {info['rows']:,} ligne(s) de paie ?\n\n"
            f"Institution : {institution_name}\nRegime : {regime}\nPeriode : {quarter} {year}\n\n"
            "Le declaratif n'est pas supprime. Une sauvegarde de la base sera creee avant l'operation."
        ).replace(",", " ")
        if not messagebox.askyesno("Confirmer la suppression", question):
            return
        try:
            backup = backup_database(Path(self.config_data.database_path), Path(self.config_data.backups_dir), "avant_suppression_paie")
            deleted = self.payroll_deletion.delete_scope(institution_id, regime, quarter, year)
        except Exception as exc:
            messagebox.showerror("Suppression de la paie", f"La suppression a echoue :\n{exc}")
            return
        self._refresh_dashboard()
        message = f"{deleted['rows']:,} ligne(s) de paie supprimee(s).".replace(",", " ")
        if backup:
            message += f"\n\nSauvegarde creee :\n{backup}"
        messagebox.showinfo("Suppression terminee", message)
