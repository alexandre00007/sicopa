from __future__ import annotations

from .matching_versioned import VersionedMatchingService
from .strict_consistency_app import PayrollAppWithStrictConsistency


class PayrollAppWithStrictIdentityPolicy(PayrollAppWithStrictConsistency):
    """Point d'entrée consolidé : politique d'identité stricte + versionnement global."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.matching = VersionedMatchingService(self.db)
