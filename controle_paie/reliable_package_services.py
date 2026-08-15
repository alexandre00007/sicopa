from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from .listing_analysis import ListingGroupAnalysisService
from .multiregime import MultiRegimeAnalysisService
from .reports import ReportService


def _temporary_root(root: str | Path) -> tuple[Path, Path]:
    final_root = Path(root)
    final_root.mkdir(parents=True, exist_ok=True)
    temp_root = Path(tempfile.mkdtemp(prefix=".sicorpa_export_", dir=final_root))
    return final_root, temp_root


def _publish_directory(temp_package: Path, final_root: Path, temp_root: Path) -> Path:
    final = final_root / temp_package.name
    if final.exists():
        raise FileExistsError(f"Le dossier d'export existe déjà : {final}")
    try:
        os.replace(temp_package, final)
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)
    return final


class ReliableListingGroupAnalysisService(ListingGroupAnalysisService):
    """Génère le package complet avant de le rendre visible dans le dossier final."""

    def export(self, group_id: str, root: str, progress=None) -> Path:
        final_root, temp_root = _temporary_root(root)
        try:
            temporary_package = Path(super().export(group_id, str(temp_root), progress=progress))
            final = _publish_directory(temporary_package, final_root, temp_root)
        except Exception:
            shutil.rmtree(temp_root, ignore_errors=True)
            raise
        with self.db.connect() as con:
            con.execute("UPDATE groupes_analyse_listing SET dossier_export=? WHERE groupe_id=?",
                        [str(final), group_id])
        return final


class ReliableMultiRegimeAnalysisService(MultiRegimeAnalysisService):
    """Publie une analyse multi-régimes uniquement lorsque tous ses fichiers sont générés."""

    def export(self, campaign_id: str, root: str, progress=None) -> Path:
        final_root, temp_root = _temporary_root(root)
        try:
            temporary_package = Path(super().export(campaign_id, str(temp_root), progress=progress))
            final = _publish_directory(temporary_package, final_root, temp_root)
        except Exception:
            shutil.rmtree(temp_root, ignore_errors=True)
            raise
        with self.db.connect() as con:
            con.execute("UPDATE campagnes_analyse_multi SET dossier_export=? WHERE campagne_id=?",
                        [str(final), campaign_id])
        return final


class ReliableReportService(ReportService):
    """Évite de publier un package de rapports incomplet."""

    def generate_package(self, root: str, institution_id: str, regime: str, quarter: str, year: int,
                         progress=None, impact_formula_id: str = "") -> Path:
        final_root, temp_root = _temporary_root(root)
        try:
            temporary_package = Path(super().generate_package(
                str(temp_root), institution_id, regime, quarter, year,
                progress=progress, impact_formula_id=impact_formula_id,
            ))
            return _publish_directory(temporary_package, final_root, temp_root)
        except Exception:
            shutil.rmtree(temp_root, ignore_errors=True)
            raise
