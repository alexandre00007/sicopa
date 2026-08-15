from __future__ import annotations

from .raw_period_occurrence_app import PayrollAppWithRawOccurrenceDetails
from .reliable_package_services import (
    ReliableListingGroupAnalysisService,
    ReliableMultiRegimeAnalysisService,
    ReliableReportService,
)


class PayrollAppWithReliableExports(PayrollAppWithRawOccurrenceDetails):
    """Point d'entrée final avec publication atomique des gros packages d'export."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.multi_analysis = ReliableMultiRegimeAnalysisService(self.db)
        self.listing_analysis = ReliableListingGroupAnalysisService(self.db)
        self.reports = ReliableReportService(self.db)
