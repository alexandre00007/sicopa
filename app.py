import logging
import tkinter as tk
from tkinter import messagebox

from controle_paie.raw_period_comparison_fusion_aware_app import PayrollAppWithFusionAwareRawPeriodComparison as PayrollApp


if __name__ == "__main__":
    try:
        PayrollApp().mainloop()
    except Exception as exc:
        logging.exception("Erreur fatale au démarrage de SICORPA")
        try:
            root=tk.Tk();root.withdraw();messagebox.showerror("SICORPA — Erreur de démarrage",f"L’application ne peut pas démarrer :\n{exc}\n\nConsultez sicorpa.log pour le diagnostic.");root.destroy()
        except Exception:
            pass
        raise
