from __future__ import annotations

from .flexible_access_ingestion import FlexibleAccessIngestionService
from .matching_deletion_app import PayrollAppWithMatchingDeletion


class PayrollAppWithFlexibleAccess(PayrollAppWithMatchingDeletion):
    """Active l'import Access flexible sur l'application complète."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ingestion = FlexibleAccessIngestionService(self.db, self.config_data)
