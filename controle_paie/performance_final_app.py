from __future__ import annotations

import math
import tkinter as tk
from tkinter import ttk

from .performance_continuation_app import PayrollAppWithPerformanceContinuation


class PayrollAppWithPerformanceFinal(PayrollAppWithPerformanceContinuation):
    """Clôture Lot 3 : pagination serveur des historiques secondaires lourds."""

    HISTORY_PAGE_SIZE = 100

    def __init__(self, *args, **kwargs):
        self.multi_history_page = 1
        self.listing_history_page = 1
        super().__init__(*args, **kwargs)

    @staticmethod
    def _history_bounds(total: int, page: int, page_size: int = 100):
        page_size = max(25, min(int(page_size), 500))
        total_pages = max(1, math.ceil(int(total or 0) / page_size))
        page = max(1, min(int(page), total_pages))
        return page, total_pages, (page - 1) * page_size

    def _add_history_pager(self, parent, label_var, prev_cmd, next_cmd):
        bar = ttk.Frame(parent)
        bar.pack(fill="x", pady=(0, 8))
        prev = ttk.Button(bar, text="◀ Précédent", command=prev_cmd)
        prev.pack(side="left")
        nxt = ttk.Button(bar, text="Suivant ▶", command=next_cmd)
        nxt.pack(side="left", padx=6)
        ttk.Label(bar, textvariable=label_var, style="PageHint.TLabel").pack(side="left", padx=10)
        return prev, nxt

    # ------------------------------------------------------------------
    # Historique campagnes multi-régimes
    # ------------------------------------------------------------------
    def _open_multi_history(self):
        super()._open_multi_history()
        if not hasattr(self, "multi_history_tree") or not self.multi_history_tree.winfo_exists():
            return
        body = self.multi_history_tree.master
        self.multi_history_label = tk.StringVar(value="Page 1 / 1")
        self.multi_history_prev, self.multi_history_next = self._add_history_pager(
            body, self.multi_history_label, self._multi_history_prev_page, self._multi_history_next_page
        )
        self._refresh_multi_history()

    def _multi_history_prev_page(self):
        if self.multi_history_page > 1:
            self.multi_history_page -= 1
            self._refresh_multi_history()

    def _multi_history_next_page(self):
        if self.multi_history_page < getattr(self, "multi_history_total_pages", 1):
            self.multi_history_page += 1
            self._refresh_multi_history()

    def _refresh_multi_history(self):
        if not hasattr(self, "multi_history_tree") or not self.multi_history_tree.winfo_exists():
            return
        with self.db.connect() as con:
            total = int(con.execute("""SELECT COUNT(*) FROM campagnes_analyse_multi
                WHERE NOT COALESCE(archivee,FALSE)""").fetchone()[0])
            page, total_pages, offset = self._history_bounds(total, self.multi_history_page, self.HISTORY_PAGE_SIZE)
            rows = con.execute("""SELECT c.campagne_id,i.nom_officiel,c.regime_declaratif,
                    c.trimestre,c.annee,c.statut,c.lignes_base,c.lignes_declaratives,
                    c.declaratif_execution_id,c.cree_le,c.termine_le,c.dossier_export,
                    COALESCE(c.archivee,FALSE)
                FROM campagnes_analyse_multi c
                LEFT JOIN institutions i ON i.institution_id=c.institution_declarative_id
                WHERE NOT COALESCE(c.archivee,FALSE)
                ORDER BY c.cree_le DESC LIMIT ? OFFSET ?""",
                [self.HISTORY_PAGE_SIZE, offset]).fetchall()
        self.multi_history_page = page
        self.multi_history_total_pages = total_pages
        self.multi_history_tree.delete(*self.multi_history_tree.get_children())
        for row in rows:
            campaign,institution,regime,quarter,year,status,base,declaration,_decl_exec,created,_ended,folder,_archived=row
            stamp=created.strftime("%d/%m/%Y %H:%M") if created else ""
            self.multi_history_tree.insert("","end",iid=campaign,
                values=(institution,regime,f"{quarter} {year}",status,base,declaration,stamp,folder or ""))
        if hasattr(self, "multi_history_label"):
            self.multi_history_label.set(f"Page {page}/{total_pages} — {total} campagne(s)")
            self.multi_history_prev.configure(state="normal" if page > 1 else "disabled")
            self.multi_history_next.configure(state="normal" if page < total_pages else "disabled")

    # ------------------------------------------------------------------
    # Historique analyses groupées de listings
    # ------------------------------------------------------------------
    def _open_listing_history(self):
        super()._open_listing_history()
        if not hasattr(self, "listing_history_tree") or not self.listing_history_tree.winfo_exists():
            return
        body = self.listing_history_tree.master
        self.listing_history_label = tk.StringVar(value="Page 1 / 1")
        self.listing_history_prev, self.listing_history_next = self._add_history_pager(
            body, self.listing_history_label, self._listing_history_prev_page, self._listing_history_next_page
        )
        self._refresh_listing_history()

    def _listing_history_prev_page(self):
        if self.listing_history_page > 1:
            self.listing_history_page -= 1
            self._refresh_listing_history()

    def _listing_history_next_page(self):
        if self.listing_history_page < getattr(self, "listing_history_total_pages", 1):
            self.listing_history_page += 1
            self._refresh_listing_history()

    def _refresh_listing_history(self):
        if not hasattr(self, "listing_history_tree") or not self.listing_history_tree.winfo_exists():
            return
        with self.db.connect() as con:
            total = int(con.execute("""SELECT COUNT(*) FROM groupes_analyse_listing
                WHERE NOT COALESCE(archive,FALSE)""").fetchone()[0])
            page, total_pages, offset = self._history_bounds(total, self.listing_history_page, self.HISTORY_PAGE_SIZE)
            rows = con.execute("""SELECT groupe_id,nom,trimestre,annee,statut,lignes_base,
                    cree_le,termine_le,dossier_export,COALESCE(archive,FALSE)
                FROM groupes_analyse_listing
                WHERE NOT COALESCE(archive,FALSE)
                ORDER BY cree_le DESC LIMIT ? OFFSET ?""",
                [self.HISTORY_PAGE_SIZE, offset]).fetchall()
        self.listing_history_page = page
        self.listing_history_total_pages = total_pages
        self.listing_history_tree.delete(*self.listing_history_tree.get_children())
        for group,name,quarter,year,status,rows_count,created,_ended,folder,_archived in rows:
            stamp=created.strftime("%d/%m/%Y %H:%M") if created else ""
            self.listing_history_tree.insert("","end",iid=group,
                values=(name,f"{quarter} {year}",status,rows_count,stamp,folder or ""))
        if hasattr(self, "listing_history_label"):
            self.listing_history_label.set(f"Page {page}/{total_pages} — {total} groupe(s)")
            self.listing_history_prev.configure(state="normal" if page > 1 else "disabled")
            self.listing_history_next.configure(state="normal" if page < total_pages else "disabled")
