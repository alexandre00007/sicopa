from __future__ import annotations

import json
import uuid
from datetime import datetime

from .identity_policy import IDENTITY_ALGORITHM_VERSION


class AnalysisVersionRegistry:
    """Registre générique des versions/recalculs d'analyses SICORPA."""

    def __init__(self, db):
        self.db = db
        self.ensure_schema()

    def ensure_schema(self) -> None:
        with self.db.connect() as con:
            con.execute("""CREATE TABLE IF NOT EXISTS versions_analyses (
                version_id VARCHAR PRIMARY KEY,
                type_analyse VARCHAR NOT NULL,
                analyse_id VARCHAR NOT NULL,
                analyse_parent_id VARCHAR,
                numero_version INTEGER NOT NULL,
                version_algorithme VARCHAR NOT NULL,
                action VARCHAR NOT NULL,
                parametres_json VARCHAR,
                resume_json VARCHAR,
                cree_le TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""")
            con.execute("CREATE INDEX IF NOT EXISTS idx_versions_analyses_id ON versions_analyses(type_analyse,analyse_id,numero_version)")

    def next_version(self, type_analyse: str, analyse_id: str) -> int:
        with self.db.connect() as con:
            row = con.execute(
                "SELECT COALESCE(MAX(numero_version),0)+1 FROM versions_analyses WHERE type_analyse=? AND analyse_id=?",
                [type_analyse, analyse_id],
            ).fetchone()
        return int(row[0] or 1)

    def record(self, type_analyse: str, analyse_id: str, *, action: str,
               parent_id: str | None = None, parameters: dict | None = None,
               summary: dict | None = None, algorithm_version: str = IDENTITY_ALGORITHM_VERSION,
               version_number: int | None = None) -> str:
        version_id = str(uuid.uuid4())
        number = int(version_number or self.next_version(type_analyse, analyse_id))
        with self.db.connect() as con:
            con.execute("""INSERT INTO versions_analyses
                (version_id,type_analyse,analyse_id,analyse_parent_id,numero_version,version_algorithme,
                 action,parametres_json,resume_json,cree_le)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                [version_id,type_analyse,analyse_id,parent_id,number,algorithm_version,action,
                 json.dumps(parameters or {}, ensure_ascii=False, default=str),
                 json.dumps(summary or {}, ensure_ascii=False, default=str),datetime.now()])
        return version_id

    def history(self, type_analyse: str, analyse_id: str) -> list[tuple]:
        with self.db.connect() as con:
            return con.execute("""SELECT version_id,numero_version,version_algorithme,action,
                    analyse_parent_id,parametres_json,resume_json,cree_le
                FROM versions_analyses WHERE type_analyse=? AND analyse_id=?
                ORDER BY numero_version,cree_le""", [type_analyse,analyse_id]).fetchall()
