from __future__ import annotations

from .data_architecture import (
    DataQualityService,
    ObservedIngestionProxy,
    RawCatalogService,
    TreatmentJournalService,
    migrate_governance,
)
from .export_reliability_app import PayrollAppWithReliableExports
from .sql_console import SqlConsoleService


class CatalogSqlConsoleService(SqlConsoleService):
    """Console SQL utilisant le catalogue RAW au lieu de recompter toutes les tables."""
    def __init__(self, db, catalog):
        super().__init__(db)
        self.catalog = catalog

    def list_raw_tables(self):
        return self.catalog.list()


class PayrollAppWithDataArchitecture(PayrollAppWithReliableExports):
    """Point d'entree Lot 2 : migrations, catalogue, qualite et journal transversal."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        migrate_governance(self.db)
        self.data_quality_service = DataQualityService(self.db)
        self.raw_catalog_service = RawCatalogService(self.db)
        self.treatment_journal_service = TreatmentJournalService(self.db)
        self.ingestion = ObservedIngestionProxy(
            self.ingestion, self.db, self.data_quality_service, self.raw_catalog_service
        )
        self.sql_console_service = CatalogSqlConsoleService(self.db, self.raw_catalog_service)
        try:
            self.raw_catalog_service.refresh()
            if hasattr(self, "_refresh_sql_tables"):
                self._refresh_sql_tables()
        except Exception:
            pass

    def _background(self, task, success, refresh_data=False, operation=""):
        journal = getattr(self, "treatment_journal_service", None)
        if journal is None:
            return super()._background(task, success, refresh_data=refresh_data, operation=operation)
        token = journal.start(operation or "Traitement SICORPA")

        def observed_task():
            try:
                result = task()
                journal.finish(token, result)
                # Les operations qui peuvent modifier les RAW invalident le catalogue.
                label = (operation or "").lower()
                if any(word in label for word in ("import", "fusion", "suppression", "chargement")):
                    try:
                        self.raw_catalog_service.refresh()
                    except Exception:
                        pass
                return result
            except Exception as exc:
                journal.fail(token, exc)
                raise

        started = super()._background(
            observed_task, success, refresh_data=refresh_data, operation=operation
        )
        if not started:
            # Aucun worker n'a ete lance : ne pas laisser une entree EN_COURS.
            try:
                journal.fail(token, RuntimeError("Traitement non lance : application deja occupee"))
            except Exception:
                pass
        return started
