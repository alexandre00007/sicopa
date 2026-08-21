from __future__ import annotations

import uuid
from pathlib import Path

from .fast_access_reader import read_access_table_fast
from .loaders import IngestionService
from .standardization import standardize_payroll


class FlexibleAccessIngestionService(IngestionService):
    """Import Access tolérant aux variations de schéma des tables raw_*.

    Les colonnes nouvelles sont ajoutées automatiquement à la destination.
    Les colonnes historiques absentes du nouvel import sont remplies avec NULL.
    Les colonnes configurées obligatoires deviennent des avertissements de qualité.
    """

    @staticmethod
    def _quote_identifier(name: str) -> str:
        return '"' + str(name).replace('"', '""') + '"'

    def _sync_raw_schema(self, con, destination: str) -> dict:
        dest_q = self._quote_identifier(destination)
        exists = con.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='main' AND table_name=?",
            [destination],
        ).fetchone()[0]

        if not exists:
            con.execute(
                f"CREATE TABLE {dest_q} AS "
                "SELECT *, CAST(NULL AS VARCHAR) AS execution_id, "
                "CAST(NULL AS VARCHAR) AS trimestre, CAST(NULL AS INTEGER) AS annee "
                "FROM raw_frame WHERE FALSE"
            )
            return {"added": [], "missing": []}

        destination_columns = {
            row[0]: row[1] for row in con.execute(f"DESCRIBE {dest_q}").fetchall()
        }
        source_columns = {
            row[0]: row[1] for row in con.execute("DESCRIBE raw_frame").fetchall()
        }

        added = []
        for column, data_type in source_columns.items():
            if column in destination_columns:
                continue
            con.execute(
                f"ALTER TABLE {dest_q} ADD COLUMN {self._quote_identifier(column)} {data_type}"
            )
            destination_columns[column] = data_type
            added.append(column)

        for technical, data_type in (("execution_id", "VARCHAR"), ("trimestre", "VARCHAR"), ("annee", "INTEGER")):
            if technical not in destination_columns:
                con.execute(
                    f"ALTER TABLE {dest_q} ADD COLUMN {self._quote_identifier(technical)} {data_type}"
                )
                destination_columns[technical] = data_type
                added.append(technical)

        missing = [
            column for column in destination_columns
            if column not in source_columns and column not in {"execution_id", "trimestre", "annee"}
        ]
        return {"added": added, "missing": missing}

    def load_access(self, path: str, table: str, institution_id: str, regime: str,
                    quarter: str, year: int, mode: str = "append", mapping=None,
                    progress=None) -> str:
        execution_id = str(uuid.uuid4())
        progress and progress(-1, f"Ouverture du fichier Access : {Path(path).name}")
        raw = read_access_table_fast(path, table, self.config.access_driver)
        raw_count = len(raw)
        progress and progress(25, f"Table {table} lue : {raw_count:,} lignes".replace(",", " "))

        metadata = dict(
            execution_id=execution_id,
            institution_id=institution_id,
            regime=regime,
            trimestre=quarter,
            annee=year,
            table_source=table,
        )
        mapping = mapping if mapping is not None else self.db.get_column_mapping(regime, "ACCESS")
        missing_required = [
            column for column in self.db.required_source_columns(regime, "ACCESS")
            if column not in raw.columns
        ]
        warnings = []
        if missing_required:
            warnings.append("Colonnes configurées absentes : " + ", ".join(missing_required))
            progress and progress(
                35,
                "Import flexible : colonnes absentes acceptées et complétées avec des valeurs neutres",
            )

        progress and progress(-1, "Standardisation et validation des colonnes Access")
        standard = standardize_payroll(raw, metadata, mapping)
        usable_mat = int((~standard["matricule_normalise"].isin(["", "NU"])).sum())
        usable_name = int((standard["nom_normalise"] != "").sum())
        if not usable_mat:
            warnings.append("Aucun matricule exploitable")
        if not usable_name:
            warnings.append("Aucun nom exploitable")

        destination = self.config.regimes[regime].raw_table
        progress and progress(50, f"Préparation flexible de {destination}")

        with self.db.connect() as con:
            con.execute("BEGIN")
            try:
                if mode == "replace_period":
                    con.execute(
                        "DELETE FROM paie_standardisee WHERE regime=? AND trimestre=? AND annee=? AND institution_id=?",
                        [regime, quarter, year, institution_id],
                    )

                con.register("raw_frame", raw)
                schema = self._sync_raw_schema(con, destination)

                if schema["added"]:
                    progress and progress(60, "Colonnes ajoutées au RAW : " + ", ".join(schema["added"]))
                elif schema["missing"]:
                    progress and progress(
                        60,
                        f"{len(schema['missing'])} colonne(s) historique(s) absente(s) : valeurs NULL",
                    )

                dest_q = self._quote_identifier(destination)
                con.execute(
                    f"INSERT INTO {dest_q} BY NAME "
                    "SELECT *, ?::VARCHAR AS execution_id, ?::VARCHAR AS trimestre, ?::INTEGER AS annee "
                    "FROM raw_frame",
                    [execution_id, quarter, year],
                )
                con.unregister("raw_frame")
                del raw

                progress and progress(75, f"Données brutes écrites dans {destination}")
                con.register("standard_frame", standard)
                con.execute("INSERT INTO paie_standardisee BY NAME SELECT * FROM standard_frame")
                con.unregister("standard_frame")
                progress and progress(90, "Données standardisées écrites — finalisation du journal")
                message = " ; ".join(warnings) if warnings else None
                con.execute(
                    """INSERT INTO journal_executions
                       (execution_id,type_operation,fichier_source,table_source,table_destination,
                        institution_id,regime,trimestre,annee,mode_chargement,lignes_lues,
                        lignes_chargees,statut,message,date_fin)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)""",
                    [execution_id, "IMPORT_ACCESS", str(path), table, destination,
                     institution_id, regime, quarter, year, mode, raw_count, len(standard),
                     "TERMINE_AVEC_AVERTISSEMENTS" if warnings else "TERMINE", message],
                )
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                try:
                    con.execute(
                        f"DELETE FROM {self._quote_identifier(destination)} WHERE execution_id=?",
                        [execution_id],
                    )
                except Exception:
                    pass
                con.execute("DELETE FROM paie_standardisee WHERE execution_id=?", [execution_id])
                con.execute("DELETE FROM journal_executions WHERE execution_id=?", [execution_id])
                raise

        if warnings:
            progress and progress(95, "Import terminé avec avertissements : " + " ; ".join(warnings))
        progress and progress(100, f"Table Access chargée : {len(standard):,} lignes".replace(",", " "))
        return execution_id
