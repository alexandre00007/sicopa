from __future__ import annotations

from .regime_comparison_strict_export import StrictExportRegimeComparisonService
from .regime_comparison_ui import PayrollAppWithRegimeComparison


class PayrollAppWithFinalRegimeComparison(PayrollAppWithRegimeComparison):
    """Assemble l'UI de comparaison avec le moteur strict d'identite."""

    def _build_matching(self):
        super()._build_matching()
        self.regime_comparison = StrictExportRegimeComparisonService(self.db)
        if hasattr(self, "compare_filter_combo"):
            self.compare_filter_combo["values"] = [
                "Tous",
                "Payés dans les deux (identité exacte)",
                *StrictExportRegimeComparisonService.STATUSES,
            ]

    def _refresh_regime_comparison_results(self):
        if not self.compare_last_id:
            return
        selected = self.compare_result_filter.get()
        status = (
            "" if selected == "Tous"
            else "DOUBLE_PAIEMENT" if selected in {"Payés dans les deux", "Payés dans les deux (identité exacte)"}
            else selected
        )
        rows = self.regime_comparison.list_results(self.compare_last_id, status)
        self.compare_result_tree.delete(*self.compare_result_tree.get_children())
        for row in rows:
            values = list(row)
            for index in [6, 7, 8, 9, 10, 11]:
                values[index] = f"{float(values[index] or 0):,.2f}".replace(",", " ")
            values[12] = f"{float(values[12] or 0):.2f}%"
            self.compare_result_tree.insert("", "end", values=values)
        self.compare_status.set(f"{len(rows)} résultat(s) affiché(s) pour le filtre « {selected} ».")

    def _regime_comparison_completed(self, summary):
        self.compare_last_id = summary["id"]
        self._display_regime_comparison_summary(summary)
        self.compare_result_filter.set("Tous")
        self._refresh_regime_comparison_results()
        self.compare_export_button.configure(state="normal")
        self.compare_status.set(
            f"Comparaison stricte terminée : {summary['common']} identité(s) exacte(s) commune(s), "
            f"{summary['only_a']} uniquement A, {summary['only_b']} uniquement B."
        )
