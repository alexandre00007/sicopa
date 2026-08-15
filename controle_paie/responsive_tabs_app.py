from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .performance_final_app import PayrollAppWithPerformanceFinal


class PayrollAppWithResponsiveTabs(PayrollAppWithPerformanceFinal):
    """Finition UI : titres d'onglets et titres de pages lisibles sur toutes les largeurs."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._install_responsive_notebooks()
        self._install_responsive_headings()

    def _install_responsive_notebooks(self):
        """Compacte les onglets quand nécessaire sans tronquer leurs libellés."""
        style = ttk.Style(self)
        style.configure("TNotebook.Tab", padding=(10, 9), font=("DejaVu Sans", 9, "bold"))
        self.after_idle(self._refresh_notebook_layouts)
        self.bind("<Configure>", self._schedule_notebook_refresh, add="+")

    def _schedule_notebook_refresh(self, _event=None):
        pending = getattr(self, "_responsive_tabs_after", None)
        if pending:
            try:
                self.after_cancel(pending)
            except tk.TclError:
                pass
        self._responsive_tabs_after = self.after(120, self._refresh_notebook_layouts)

    def _refresh_notebook_layouts(self):
        self._responsive_tabs_after = None
        for notebook in self._walk_widgets(self, ttk.Notebook):
            try:
                width = max(1, notebook.winfo_width())
                tabs = notebook.tabs()
                if not tabs:
                    continue
                # Retire les espaces décoratifs historiques : ils consommaient une largeur
                # importante sans apporter d'information.
                labels = []
                for tab_id in tabs:
                    label = str(notebook.tab(tab_id, "text") or "").strip()
                    labels.append(label)
                    notebook.tab(tab_id, text=label)
                # Si un notebook contient beaucoup d'onglets, une police/padding plus compacts
                # permettent de garder les titres complets au lieu de les couper visuellement.
                if len(tabs) >= 7 or width < 1100:
                    notebook.configure(style="Compact.TNotebook")
            except tk.TclError:
                continue

    def _install_responsive_headings(self):
        """Autorise les titres/descriptions longs à utiliser toute la largeur disponible."""
        for label in self._walk_widgets(self, ttk.Label):
            try:
                style_name = str(label.cget("style") or "")
                if style_name in {"PageTitle.TLabel", "PageHint.TLabel"}:
                    label.configure(justify="left", anchor="w")
                    label.bind("<Configure>", self._wrap_heading_label, add="+")
                    self._wrap_heading_label_for(label)
            except tk.TclError:
                continue

    def _wrap_heading_label(self, event):
        self._wrap_heading_label_for(event.widget)

    @staticmethod
    def _wrap_heading_label_for(label):
        try:
            parent_width = label.master.winfo_width()
            if parent_width > 80:
                label.configure(wraplength=max(120, parent_width - 12))
        except tk.TclError:
            pass

    @staticmethod
    def _walk_widgets(root, widget_type):
        found = []
        stack = [root]
        while stack:
            current = stack.pop()
            try:
                children = current.winfo_children()
            except tk.TclError:
                continue
            for child in children:
                if isinstance(child, widget_type):
                    found.append(child)
                stack.append(child)
        return found

    def _build_style(self):
        super()._build_style()
        style = ttk.Style(self)
        style.configure("Compact.TNotebook", background="#F3F6FA", borderwidth=0)
        style.configure("Compact.TNotebook.Tab", padding=(7, 8), font=("DejaVu Sans", 8, "bold"))
        style.map("Compact.TNotebook.Tab", background=[("selected", "white")], foreground=[("selected", "#12355B")])
