from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .strict_identity_app import PayrollAppWithStrictIdentityPolicy


class PayrollAppWithRawOccurrenceDetails(PayrollAppWithStrictIdentityPolicy):
    """Expose les occurrences physiques et la qualité des communs dans l'interface RAW."""

    def _build_matching(self):
        super()._build_matching()
        self._configure_occurrence_columns()
        self._configure_occurrence_filters()
        if hasattr(self, "rpc_tree"):
            self.rpc_tree.bind("<Double-1>", self._rpc_open_occurrence_details)

    def _configure_occurrence_filters(self):
        values = [
            "Tous",
            "COMMUN_PAR_MATRICULE_ET_NOM",
            "COMMUN_EXACT_1_VS_1",
            "COMMUN_EXACT_REPETE_A",
            "COMMUN_EXACT_REPETE_B",
            "COMMUN_EXACT_REPETE_A_ET_B",
            "COMMUN_PAR_MATRICULE",
            "COMMUN_PAR_NOM",
            "MATCH_AMBIGU_MATRICULE",
            "MATCH_AMBIGU_NOM",
            "UNIQUEMENT_A",
            "UNIQUEMENT_B",
            "MEME_MATRICULE_NOM_DIFFERENT",
            "MEME_NOM_MATRICULE_DIFFERENT",
            "DOUBLON_MATRICULE_A",
            "DOUBLON_MATRICULE_B",
            "DOUBLON_NOM_A",
            "DOUBLON_NOM_B",
        ]
        if hasattr(self, "_set_combo_values_for_variable"):
            self._set_combo_values_for_variable(getattr(self, "rpc_filter", None), values)

    def _configure_occurrence_columns(self):
        if not hasattr(self, "rpc_tree"):
            return
        cols = (
            "status","ma","mb","na","nb","pa","pb","cm","cn","ra","rb","ia","ib",
            "repa","repb","linesa","linesb","linediff","situation",
            "ba","bb","eb","neta","netb","en","sa","sb","ca","cb","ga","gb","ua","ub","pra","prb",
            "execa","execb","line_ref_a","line_ref_b","amounts_a","amounts_b","diag",
        )
        self.rpc_tree.configure(columns=cols)
        specs = [
            ("status","Statut identité",220),("ma","Matricule A",115),("mb","Matricule B",115),
            ("na","Nom A",160),("nb","Nom B",160),("pa","Prénom A",120),("pb","Prénom B",120),
            ("cm","Commun mat.",90),("cn","Commun nom",90),("ra","Régime A",100),("rb","Régime B",100),
            ("ia","Institution A",150),("ib","Institution B",150),
            ("repa","Répétitions A",95),("repb","Répétitions B",95),
            ("linesa","Nb lignes A",85),("linesb","Nb lignes B",85),("linediff","Écart lignes",85),
            ("situation","Situation commun",190),
            ("ba","Brut A",110),("bb","Brut B",110),("eb","Écart brut",110),
            ("neta","Net A",110),("netb","Net B",110),("en","Écart net",110),
            ("sa","Section A",130),("sb","Section B",130),("ca","Catégorie A",120),("cb","Catégorie B",120),
            ("ga","Grade A",110),("gb","Grade B",110),("ua","Unité A",170),("ub","Unité B",170),
            ("pra","Province A",120),("prb","Province B",120),("execa","Exécutions A",85),("execb","Exécutions B",85),
            ("line_ref_a","Lignes source A",220),("line_ref_b","Lignes source B",220),
            ("amounts_a","Montants distincts A",125),("amounts_b","Montants distincts B",125),("diag","Diagnostic",400),
        ]
        for col, title, width in specs:
            self.rpc_tree.heading(col, text=title)
            self.rpc_tree.column(col, width=width, anchor="w")

    def _rpc_refresh_summary(self):
        if not self.rpc_last_id:
            return
        super()._rpc_refresh_summary()
        if hasattr(self.raw_period_comparison_service, "occurrence_summary"):
            m = self.raw_period_comparison_service.occurrence_summary(self.rpc_last_id)
            base = self.rpc_metrics.get()
            self.rpc_metrics.set(
                base + "\n"
                + f"Communs exacts 1 vs 1 : {m['communs_1_vs_1']}   •   "
                  f"Répétés A : {m['communs_repetes_a']}   •   Répétés B : {m['communs_repetes_b']}   •   "
                  f"Répétés A+B : {m['communs_repetes_a_b']}   •   "
                  f"Répétitions totales A/B : {m['repetitions_a']} / {m['repetitions_b']}"
            )

    def _rpc_refresh_results(self):
        if not self.rpc_last_id:
            return
        selected = self.rpc_filter.get()
        status = "" if selected == "Tous" else selected
        rows = self.raw_period_comparison_service.list_results_enriched(self.rpc_last_id, status)
        self.rpc_tree.delete(*self.rpc_tree.get_children())
        for row in rows:
            vals = list(row)
            for index in (19,20,21,22,23,24):
                vals[index] = f"{float(vals[index] or 0):,.2f}".replace(",", " ")
            self.rpc_tree.insert("", "end", values=vals)
        self.rpc_status.set(
            f"{len(rows)} résultat(s) — Répétitions = lignes supplémentaires après la première ligne source."
        )

    def _rpc_open_occurrence_details(self, _event=None):
        if not self.rpc_last_id:
            return
        selection = self.rpc_tree.selection()
        if not selection:
            return
        values = self.rpc_tree.item(selection[0], "values")
        if not values:
            return
        mat_a, mat_b = values[1], values[2]
        nom_a, nom_b = values[3], values[4]

        with self.db.connect() as con:
            row = con.execute("""SELECT matricule_a,matricule_b,nom_norm_a,nom_norm_b
                FROM resultats_comparaison_raw_periode
                WHERE comparaison_id=? AND COALESCE(matricule_a,'')=COALESCE(?, '')
                  AND COALESCE(matricule_b,'')=COALESCE(?, '')
                  AND COALESCE(nom_a,'')=COALESCE(?, '')
                  AND COALESCE(nom_b,'')=COALESCE(?, '')
                LIMIT 1""", [self.rpc_last_id,mat_a,mat_b,nom_a,nom_b]).fetchone()
        if not row:
            return

        win = tk.Toplevel(self)
        win.title("Occurrences réelles de l'identité")
        tabs = ttk.Notebook(win)
        tabs.pack(fill="both", expand=True, padx=10, pady=10)
        headers = ["Table","Execution","Ligne","Matricule","Nom","Prénom","Institution","Régime","Section",
                   "Catégorie","Grade","Unité","Province","Brut","Net"]
        for side, mat, norm_name in (("A",row[0],row[2]),("B",row[1],row[3])):
            frame = ttk.Frame(tabs, padding=8)
            tabs.add(frame, text=f"Source {side}")
            details = self.raw_period_comparison_service.list_occurrence_details(self.rpc_last_id, side, mat or "", norm_name or "")
            cols = tuple(f"c{i}" for i in range(len(headers)))
            tree = ttk.Treeview(frame, columns=cols, show="headings", height=18)
            for i, title in enumerate(headers):
                tree.heading(cols[i], text=title)
                tree.column(cols[i], width=120 if i not in (4,11) else 180, anchor="w")
            sy = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
            sx = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
            tree.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
            tree.grid(row=0,column=0,sticky="nsew"); sy.grid(row=0,column=1,sticky="ns"); sx.grid(row=1,column=0,sticky="ew")
            frame.rowconfigure(0,weight=1); frame.columnconfigure(0,weight=1)
            for detail in details:
                tree.insert("", "end", values=detail)
            ttk.Label(frame, text=f"{len(details)} ligne(s) physique(s) retrouvée(s) dans la source {side}.").grid(row=2,column=0,sticky="w",pady=(6,0))
        win.after_idle(lambda:self._center_child_window(win,1250,650))
