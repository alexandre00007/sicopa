from __future__ import annotations

from .raw_period_comparison_app import PayrollAppWithRawPeriodComparison


class PayrollAppWithResilientRawPeriodComparison(PayrollAppWithRawPeriodComparison):
    """Garantit la restauration des actions de comparaison RAW apres succes ou erreur."""

    def _rpc_restore_actions(self):
        for name in ("rpc_analyze_btn", "rpc_reanalyze_btn"):
            widget = getattr(self, name, None)
            if widget is not None:
                try:
                    widget.configure(state="normal")
                except Exception:
                    pass

    def _rpc_analysis_done(self, info):
        try:
            return super()._rpc_analysis_done(info)
        finally:
            self._rpc_restore_actions()

    def _generation_failed(self, summary):
        try:
            return super()._generation_failed(summary)
        finally:
            self._rpc_restore_actions()
            if hasattr(self, "rpc_status"):
                try:
                    self.rpc_status.set("Le traitement a echoue. Corrigez l'erreur puis relancez l'analyse.")
                except Exception:
                    pass
