from __future__ import annotations

import uuid
from pathlib import Path

import pandas as pd

from .flexible_access_ingestion import FlexibleAccessIngestionService
from .loaders import _validate_excel_file, describe_declaration_structure
from .standardization import standardize_declaration, standardize_payroll


class FlexibleIngestionService(FlexibleAccessIngestionService):
    """Service d'import global tolérant aux variations de colonnes.

    Principe :
    - les colonnes absentes ne bloquent plus l'import ;
    - les colonnes supplémentaires sont conservées dans les RAW quand un RAW existe ;
    - les colonnes standardisées absentes prennent leur valeur neutre ('' ou 0) ;
    - les anomalies de structure sont conservées comme avertissements dans le journal.
    """

    @staticmethod
    def _warning_text(items: list[str]) -> str:
        items = [str(item).strip() for item in items if str(item).strip()]
        return " ; ".join(items)

    def load_payroll_excel(self, path: str, sheet: str, header_row: int,
                           institution_id: str, regime: str, quarter: str, year: int,
                           mode: str = "append", mapping=None, progress=None) -> str:
        _validate_excel_file(path)
        execution_id = str(uuid.uuid4())
        progress and progress(-1, f"Ouverture du listing Excel : {Path(path).name}")
        raw = pd.read_excel(path, sheet_name=sheet, header=max(int(header_row) - 1, 0))
        raw_count = len(raw)
        if not raw_count:
            raise ValueError("La feuille de paie ne contient aucune ligne de données.")

        progress and progress(25, f"Feuille {sheet} lue : {raw_count:,} lignes".replace(",", " "))
        metadata = dict(
            execution_id=execution_id,
            institution_id=institution_id,
            regime=regime,
            trimestre=quarter,
            annee=year,
            table_source=f"{Path(path).name} — {sheet}",
        )
        mapping = mapping if mapping is not None else self.db.get_column_mapping(regime, "PAIE_EXCEL")
        required = self.db.required_source_columns(regime, "PAIE_EXCEL")
        missing_required = [column for column in required if column not in raw.columns]
        warnings = []
        if missing_required:
            warnings.append("Colonnes configurées absentes : " + ", ".join(missing_required))
            progress and progress(35, "Import flexible : colonnes absentes remplacées par des valeurs neutres")

        standard = standardize_payroll(raw, metadata, mapping)
        usable_mat = int((~standard["matricule_normalise"].isin(["", "NU"])).sum())
        usable_name = int((standard["nom_normalise"] != "").sum())
        if not usable_mat:
            warnings.append("Aucun matricule exploitable")
        if not usable_name:
            warnings.append("Aucun nom exploitable")

        progress and progress(60, f"{len(standard):,} lignes standardisées — préparation de DuckDB".replace(",", " "))
        with self.db.connect() as con:
            con.execute("BEGIN")
            try:
                if mode == "replace_period":
                    con.execute(
                        "DELETE FROM paie_standardisee WHERE regime=? AND trimestre=? AND annee=? AND institution_id=?",
                        [regime, quarter, year, institution_id],
                    )
                con.register("standard_frame", standard)
                con.execute("INSERT INTO paie_standardisee BY NAME SELECT * FROM standard_frame")
                message = self._warning_text(warnings)
                con.execute(
                    """INSERT INTO journal_executions
                       (execution_id,type_operation,fichier_source,table_source,table_destination,
                        institution_id,regime,trimestre,annee,mode_chargement,lignes_lues,
                        lignes_chargees,statut,message,date_fin)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)""",
                    [execution_id, "IMPORT_PAIE_EXCEL", str(path), sheet, "paie_standardisee",
                     institution_id, regime, quarter, year, mode, raw_count, len(standard),
                     "TERMINE_AVEC_AVERTISSEMENTS" if warnings else "TERMINE", message or None],
                )
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise

        if warnings:
            progress and progress(95, "Import terminé avec avertissements : " + self._warning_text(warnings))
        progress and progress(100, f"Listing Excel chargé : {len(standard):,} lignes".replace(",", " "))
        return execution_id

    def load_excel(self, path: str, sheet: str, header_row: int,
                   institution_id: str, regime: str, quarter: str, year: int,
                   mode: str = "append", mapping=None, progress=None) -> str:
        _validate_excel_file(path)
        execution_id = str(uuid.uuid4())
        progress and progress(-1, f"Ouverture du déclaratif : {Path(path).name}")
        raw = pd.read_excel(path, sheet_name=sheet, header=max(int(header_row) - 1, 0))
        raw_count = len(raw)
        if not raw_count:
            raise ValueError("La feuille déclarative ne contient aucune ligne de données.")

        progress and progress(25, f"Feuille {sheet} lue : {raw_count:,} lignes".replace(",", " "))
        metadata = dict(
            execution_id=execution_id,
            institution_id=institution_id,
            regime=regime,
            trimestre=quarter,
            annee=year,
            fichier_source=str(path),
            feuille_source=sheet,
        )
        mapping = mapping if mapping is not None else self.db.get_column_mapping(regime, "EXCEL")
        required = self.db.required_source_columns(regime, "EXCEL")
        structure = describe_declaration_structure(raw.columns, mapping, required)
        warnings = list(structure.get("issues") or [])
        resolved_mapping = structure["mapping"]

        if warnings:
            progress and progress(35, "Import flexible : structure incomplète acceptée avec avertissements")

        schema_rows = [
            (execution_id, "EXCEL", sheet, str(column), str(dtype),
             resolved_mapping.get(str(column)), str(column) in required)
            for column, dtype in raw.dtypes.items()
        ]
        standard = standardize_declaration(raw, metadata, resolved_mapping)
        usable_mat = int((~standard["matricule_normalise"].isin(["", "NU"])).sum())
        usable_name = int((standard["nom_normalise"] != "").sum())
        if not usable_mat:
            warnings.append("Aucun matricule exploitable : le rapprochement par matricule sera indisponible")
        if not usable_name:
            warnings.append("Aucun nom exploitable : le rapprochement par nom sera indisponible")

        progress and progress(55, f"{len(standard):,} lignes standardisées — préparation de DuckDB".replace(",", " "))
        with self.db.connect() as con:
            con.execute("BEGIN")
            try:
                if mode == "replace_period":
                    matching_refs = con.execute(
                        """SELECT COUNT(DISTINCT r.execution_id)
                           FROM resultats_rapprochement r JOIN declaratif_standardise d
                             ON d.ligne_declaratif_id=r.ligne_declaratif_id
                           WHERE d.regime=? AND d.trimestre=? AND d.annee=? AND d.institution_id=?""",
                        [regime, quarter, year, institution_id],
                    ).fetchone()[0]
                    campaign_refs = con.execute(
                        """SELECT COUNT(*) FROM campagnes_analyse_multi
                           WHERE regime_declaratif=? AND trimestre=? AND annee=?
                             AND institution_declarative_id=?""",
                        [regime, quarter, year, institution_id],
                    ).fetchone()[0]
                    if matching_refs or campaign_refs:
                        raise ValueError(
                            "Remplacement bloqué : le déclaratif actuel est déjà utilisé par "
                            f"{matching_refs} rapprochement(s) et {campaign_refs} campagne(s) multi-régimes. "
                            "Ajoutez une nouvelle version afin de conserver la traçabilité."
                        )
                    con.execute(
                        "DELETE FROM declaratif_standardise WHERE regime=? AND trimestre=? AND annee=? AND institution_id=?",
                        [regime, quarter, year, institution_id],
                    )

                if schema_rows:
                    con.executemany("INSERT INTO schemas_sources VALUES (?,?,?,?,?,?,?)", schema_rows)
                con.register("standard_frame", standard)
                con.execute("INSERT INTO declaratif_standardise BY NAME SELECT * FROM standard_frame")
                message = self._warning_text(warnings)
                con.execute(
                    """INSERT INTO journal_executions
                       (execution_id,type_operation,fichier_source,table_source,table_destination,
                        institution_id,regime,trimestre,annee,mode_chargement,lignes_lues,
                        lignes_chargees,statut,message,date_fin)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)""",
                    [execution_id, "IMPORT_EXCEL", str(path), sheet, "declaratif_standardise",
                     institution_id, regime, quarter, year, mode, raw_count, len(standard),
                     "TERMINE_AVEC_AVERTISSEMENTS" if warnings else "TERMINE", message or None],
                )
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise

        if warnings:
            progress and progress(95, "Import terminé avec avertissements : " + self._warning_text(warnings))
        progress and progress(100, f"Déclaratif chargé : {len(standard):,} lignes".replace(",", " "))
        return execution_id
