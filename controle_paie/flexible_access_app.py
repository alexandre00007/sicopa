from __future__ import annotations

from .flexible_ingestion import FlexibleIngestionService
from .matching_deletion_app import PayrollAppWithMatchingDeletion


class PayrollAppWithFlexibleAccess(PayrollAppWithMatchingDeletion):
    """Active l'import flexible pour Access, paie Excel et déclaratif Excel."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ingestion = FlexibleIngestionService(self.db, self.config_data)
