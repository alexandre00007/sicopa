from __future__ import annotations

import logging
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from .help_content import USER_GUIDE
from .manual_content import QUICK_GUIDE_ADDENDUM
from .manual_pdf import generate_user_manual_pdf
from .responsive_tabs_app import PayrollAppWithResponsiveTabs


class PayrollAppWithUserManual(PayrollAppWithResponsiveTabs):
    """Enrichit Aide > Mode d'emploi avec un guide rapide et un manuel PDF complet."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._install_manual_menu_entry()

    def _install_manual_menu_entry(self):
        """Ajoute Aide > Manuel PDF complet sans recopier tout le menu historique."""
        try:
            menubar = self.nametowidget(self.cget("menu"))
            end = menubar.index("end")
            if end is None:
                return
            for index in range(end + 1):
                if str(menubar.type(index)) != "cascade":
                    continue
                if str(menubar.entrycget(index, "label")) != "Aide":
                    continue
                help_menu = self.nametowidget(menubar.entrycget(index, "menu"))
                labels = []
                help_end = help_menu.index("end")
                if help_end is not None:
                    for item in range(help_end + 1):
                        try:
                            labels.append(str(help_menu.entrycget(item, "label")))
                        except tk.TclError:
                            pass
                if "Manuel PDF complet" not in labels:
                    help_menu.insert_command(
                        1,
                        label="Manuel PDF complet",
                        command=lambda: self._generate_and_open_manual(self),
                    )
                return
        except tk.TclError:
            logging.exception("Impossible d'ajouter l'entree Manuel PDF dans le menu Aide")

    def _manual_pdf_path(self) -> Path:
        folder = Path(self.config_data.results_dir) / "Documentation SICORPA"
        return folder / "Manuel_utilisateur_SICORPA.pdf"

    def _generate_and_open_manual(self, parent=None):
        try:
            path = generate_user_manual_pdf(self._manual_pdf_path())
            self._open_runtime_path(path)
        except Exception as exc:
            logging.exception("Generation du manuel PDF impossible")
            messagebox.showerror(
                "Manuel PDF",
                f"Le manuel PDF n'a pas pu etre genere.\n\n{exc}",
                parent=parent or self,
            )

    def _show_user_guide(self):
        window = tk.Toplevel(self)
        window.title("Mode d'emploi de SICORPA")
        window.transient(self)

        header = tk.Frame(window, background="#12355B", padx=20, pady=15)
        header.pack(fill="x")
        tk.Label(
            header, text="Mode d'emploi de SICORPA", background="#12355B",
            foreground="white", font=("DejaVu Sans", 16, "bold"),
        ).pack(anchor="w")
        tk.Label(
            header,
            text="Guide rapide dans l'application + manuel PDF complet d'utilisation et d'interpretation des annexes",
            background="#12355B", foreground="#CFE2F3", font=("DejaVu Sans", 9),
        ).pack(anchor="w", pady=(4, 0))

        actions = ttk.Frame(window, padding=(16, 12, 16, 4))
        actions.pack(fill="x")
        ttk.Button(
            actions, text="Ouvrir le manuel PDF complet", style="Primary.TButton",
            command=lambda: self._generate_and_open_manual(window),
        ).pack(side="left")
        ttk.Label(
            actions,
            text="Le PDF est genere dans Resultats / Documentation SICORPA et peut etre conserve ou imprime.",
            style="PageHint.TLabel",
        ).pack(side="left", padx=12)

        body = ttk.Frame(window, padding=(16, 8, 16, 10))
        body.pack(fill="both", expand=True)
        scroll = ttk.Scrollbar(body)
        scroll.pack(side="right", fill="y")
        text = tk.Text(
            body, wrap="word", yscrollcommand=scroll.set, font=("DejaVu Sans", 10),
            background="white", foreground="#243247", padx=14, pady=14,
            relief="solid", borderwidth=1,
        )
        text.pack(side="left", fill="both", expand=True)
        scroll.configure(command=text.yview)
        text.insert("1.0", USER_GUIDE + QUICK_GUIDE_ADDENDUM)
        text.configure(state="disabled")

        footer = ttk.Frame(window, padding=(16, 0, 16, 14))
        footer.pack(fill="x")
        ttk.Button(
            footer, text="Regenerer le PDF", style="Secondary.TButton",
            command=lambda: self._generate_and_open_manual(window),
        ).pack(side="left")
        ttk.Button(
            footer, text="Fermer", style="Primary.TButton", command=window.destroy,
        ).pack(side="right")

        window.after_idle(lambda: self._center_child_window(window, 940, 720))
