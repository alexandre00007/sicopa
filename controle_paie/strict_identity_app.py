from __future__ import annotations

from .matching_versioned import VersionedMatchingService
from .task_managed_app import PayrollAppWithTaskManager


class PayrollAppWithStrictIdentityPolicy(PayrollAppWithTaskManager):
    """Point d'entrée consolidé : politique d'identité stricte + versionnement global."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.matching = VersionedMatchingService(self.db)

    def _build_matching(self):
        super()._build_matching()
        if hasattr(self, "raw_fusion_filter"):
            filters = [
                "Tous",
                "MATRICULE_PARTAGE_IDENTITES_DIFFERENTES",
                "DEUX_REGIMES",
                "TROIS_REGIMES_OU_PLUS",
                "PAIEMENT_MULTIPLE_MEME_REGIME",
                "PLUSIEURS_INSTITUTIONS",
                "IDENTITE_INCOHERENTE",
                "DOUBLON_MATRICULE",
                "DOUBLON_NOM",
                "UN_SEUL_REGIME",
            ]
            try:
                combo = self._find_filter_combo(self)
                if combo is not None:
                    combo["values"] = filters
            except Exception:
                pass
