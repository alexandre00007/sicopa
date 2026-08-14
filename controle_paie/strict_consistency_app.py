from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .task_managed_app import PayrollAppWithTaskManager


class PayrollAppWithStrictConsistency(PayrollAppWithTaskManager):
    """Expose dans l'UI les statuts stricts et ambigus des moteurs de controle."""

    def _build_matching(self):
        super()._build_matching()
        self._apply_strict_filter_values()

    def _apply_strict_filter_values(self):
        rpc_values = [
            "Tous",
            "COMMUN_PAR_MATRICULE_ET_NOM",
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
        fusion_values = [
            "Tous",
            "DEUX_REGIMES",
            "TROIS_REGIMES_OU_PLUS",
            "PAIEMENT_MULTIPLE_MEME_REGIME",
            "PLUSIEURS_INSTITUTIONS",
            "IDENTITE_INCOHERENTE",
            "MATRICULE_PARTAGE_IDENTITES_DIFFERENTES",
            "DOUBLON_MATRICULE",
            "DOUBLON_NOM",
            "UN_SEUL_REGIME",
        ]
        self._set_combo_values_for_variable(getattr(self, "rpc_filter", None), rpc_values)
        self._set_combo_values_for_variable(getattr(self, "raw_fusion_filter", None), fusion_values)

    def _set_combo_values_for_variable(self, variable, values):
        if variable is None:
            return

        def walk(widget):
            try:
                if isinstance(widget, ttk.Combobox) and str(widget.cget("textvariable")) == str(variable):
                    widget["values"] = values
            except tk.TclError:
                pass
            for child in widget.winfo_children():
                walk(child)

        walk(self)
