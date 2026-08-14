from __future__ import annotations

from .raw_period_comparison_policy import PolicyRawPeriodComparisonService
from .raw_period_comparison_scalable import ScalableRawPeriodComparisonService


class PolicyScalableRawPeriodComparisonService(ScalableRawPeriodComparisonService):
    """Exports scalables avec le moteur de matching central sans choix arbitraire."""

    analyze = PolicyRawPeriodComparisonService.analyze
