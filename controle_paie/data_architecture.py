from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass


GOVERNANCE_SCHEMA_VERSION = 1


MIGRATIONS = {
    1: [
        """CREATE TABLE IF NOT EXISTS migrations_sicorpa (
            version INTEGER PRIMARY KEY, nom VARCHAR NOT NULL,
            applique_le TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS catalogue_raw (
            table_name VARCHAR PRIMARY KEY,
            type_raw VARCHAR NOT NULL DEFAULT 'IMPORT',
            trimestre VARCHAR, annee INTEGER,
            regimes VARCHAR, institutions VARCHAR,
            lignes BIGINT DEFAULT 0, colonnes INTEGER DEFAULT 0,
            score_qualite DOUBLE, niveau_qualite VARCHAR,
            derniere_execution_id VARCHAR,
            derniere_mise_a_jour TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS qualite_imports (
            execution_id VARCHAR PRIMARY KEY,
            type_source VARCHAR, table_destination VARCHAR,
            lignes BIGINT DEFAULT 0,
            matricules_exploitables BIGINT DEFAULT 0,
            noms_exploitables BIGINT DEFAULT 0,
            matricules_dupliques BIGINT DEFAULT 0,
            noms_dupliques BIGINT DEFAULT 0,
            taux_matricules DOUBLE DEFAULT 0,
            taux_noms DOUBLE DEFAULT 0,
            score DOUBLE DEFAULT 0,
            niveau VARCHAR,
            details_json VARCHAR,
            calcule_le TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS journal_traitements (
            traitement_id VARCHAR PRIMARY KEY,
            operation VARCHAR NOT NULL,
            statut VARCHAR NOT NULL,
            date_debut TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            date_fin TIMESTAMP,
            duree_secondes DOUBLE,
            lignes BIGINT,
            objet_id VARCHAR,
            fichier_sortie VARCHAR,
            version_algorithme VARCHAR,
            message VARCHAR,
            details_json VARCHAR)""",
        "CREATE INDEX IF NOT EXISTS idx_catalogue_raw_periode ON catalogue_raw(trimestre,annee)",
        "CREATE INDEX IF NOT EXISTS idx_qualite_imports_niveau ON qualite_imports(niveau)",
        "CREATE INDEX IF NOT EXISTS idx_journal_traitements_date ON journal_traitements(date_debut)",
    ]
}


def migrate_governance(db) -> None:
    """Migrations versionnees des briques transversales ajoutees apres le schema historique."""
    with db.connect() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS migrations_sicorpa (
            version INTEGER PRIMARY KEY, nom VARCHAR NOT NULL,
            applique_le TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        applied = {int(row[0]) for row in con.execute("SELECT version FROM migrations_sicorpa").fetchall()}
        for version in sorted(MIGRATIONS):
            if version in applied:
                continue
            con.execute("BEGIN")
            try:
                for statement in MIGRATIONS[version]:
                    con.execute(statement)
                con.execute("INSERT INTO migrations_sicorpa(version,nom) VALUES (?,?)",
                            [version, f"governance_v{version}"])
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise


def _quality_level(score: float, usable_identity: float) -> str:
    if usable_identity <= 0:
        return "INEXPLOITABLE_POUR_MATCHING"
    if score >= 90:
        return "EXCELLENTE"
    if score >= 70:
        return "ACCEPTABLE"
    if score >= 40:
        return "LIMITEE"
    return "FAIBLE"


class DataQualityService:
    def __init__(self, db):
        self.db = db

    def calculate(self, execution_id: str) -> dict:
        with self.db.connect() as con:
            journal = con.execute("""SELECT type_operation,table_destination FROM journal_executions
                WHERE execution_id=? ORDER BY date_fin DESC NULLS LAST LIMIT 1""", [execution_id]).fetchone()
            if not journal:
                raise ValueError("Execution d'import introuvable pour le calcul qualite.")
            operation, destination = journal
            table = "declaratif_standardise" if operation == "IMPORT_EXCEL" else "paie_standardisee"
            row = con.execute(f"""SELECT COUNT(*),
                SUM(CASE WHEN matricule_normalise NOT IN ('','NU') THEN 1 ELSE 0 END),
                SUM(CASE WHEN nom_normalise<>'' THEN 1 ELSE 0 END),
                SUM(CASE WHEN matricule_normalise NOT IN ('','NU') THEN 1 ELSE 0 END)
                  - COUNT(DISTINCT CASE WHEN matricule_normalise NOT IN ('','NU') THEN matricule_normalise END),
                SUM(CASE WHEN nom_normalise<>'' THEN 1 ELSE 0 END)
                  - COUNT(DISTINCT CASE WHEN nom_normalise<>'' THEN nom_normalise END)
                FROM {table} WHERE execution_id=?""", [execution_id]).fetchone()
            total = int(row[0] or 0)
            usable_mat = int(row[1] or 0)
            usable_name = int(row[2] or 0)
            dup_mat = max(0, int(row[3] or 0))
            dup_name = max(0, int(row[4] or 0))
            rate_mat = 100.0 * usable_mat / max(1, total)
            rate_name = 100.0 * usable_name / max(1, total)
            identity_rate = max(rate_mat, rate_name)
            score = round(0.55 * rate_mat + 0.35 * rate_name + 0.10 * identity_rate, 2)
            level = _quality_level(score, identity_rate)
            details = {"operation": operation, "duplicates_matricule": dup_mat,
                       "duplicates_nom": dup_name}
            con.execute("""INSERT OR REPLACE INTO qualite_imports
                (execution_id,type_source,table_destination,lignes,matricules_exploitables,noms_exploitables,
                 matricules_dupliques,noms_dupliques,taux_matricules,taux_noms,score,niveau,details_json,calcule_le)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)""",
                [execution_id, operation, destination, total, usable_mat, usable_name, dup_mat, dup_name,
                 rate_mat, rate_name, score, level, json.dumps(details, ensure_ascii=False)])
        return {"execution_id": execution_id, "lignes": total, "score": score, "niveau": level,
                "taux_matricules": rate_mat, "taux_noms": rate_name}

    def backfill(self, limit: int = 100) -> int:
        """Calcule la qualite des imports recents qui ne possedent pas encore de score."""
        with self.db.connect() as con:
            rows = con.execute("""SELECT DISTINCT j.execution_id FROM journal_executions j
                LEFT JOIN qualite_imports q ON q.execution_id=j.execution_id
                WHERE q.execution_id IS NULL
                  AND j.type_operation IN ('IMPORT_ACCESS','IMPORT_PAIE_EXCEL','IMPORT_EXCEL')
                  AND j.statut LIKE 'TERMINE%'
                ORDER BY j.execution_id DESC LIMIT ?""", [max(1, min(int(limit), 1000))]).fetchall()
        done = 0
        for (execution_id,) in rows:
            try:
                self.calculate(execution_id)
                done += 1
            except Exception:
                pass
        return done

    def list_recent(self, limit: int = 200) -> list[tuple]:
        with self.db.connect() as con:
            return con.execute("""SELECT q.execution_id,q.type_source,q.table_destination,q.lignes,
                    q.taux_matricules,q.taux_noms,q.matricules_dupliques,q.noms_dupliques,
                    q.score,q.niveau,q.calcule_le
                FROM qualite_imports q ORDER BY q.calcule_le DESC LIMIT ?""",
                [max(1, min(int(limit), 2000))]).fetchall()


class RawCatalogService:
    def __init__(self, db):
        self.db = db

    def refresh(self) -> list[tuple]:
        """Recalcule une fois les metadonnees apres mutation; les ecrans lisent ensuite le cache."""
        with self.db.connect() as con:
            names = [row[0] for row in con.execute("""SELECT table_name FROM information_schema.tables
                WHERE table_schema='main' AND table_name LIKE 'raw_%' ORDER BY table_name""").fetchall()]
            fusion_table = bool(con.execute("""SELECT COUNT(*) FROM information_schema.tables
                WHERE table_schema='main' AND table_name='fusions_raw'""").fetchone()[0])
            for name in names:
                safe = name.replace('"', '""')
                lines = int(con.execute(f'SELECT COUNT(*) FROM "{safe}"').fetchone()[0])
                columns = int(con.execute("SELECT COUNT(*) FROM information_schema.columns WHERE table_schema='main' AND table_name=?", [name]).fetchone()[0])
                meta = con.execute("""SELECT MAX(trimestre),MAX(annee),
                        STRING_AGG(DISTINCT regime, ', '),STRING_AGG(DISTINCT institution_id, ', '),
                        MAX(execution_id)
                    FROM journal_executions WHERE table_destination=? AND statut LIKE 'TERMINE%'""", [name]).fetchone()
                raw_type = "FUSION" if name.startswith("raw_multi_regimes_") else "IMPORT"
                if fusion_table and raw_type == "FUSION":
                    fm = con.execute("""SELECT trimestre,annee FROM fusions_raw WHERE table_destination=?
                        ORDER BY cree_le DESC LIMIT 1""", [name]).fetchone()
                    if fm:
                        meta = (fm[0], fm[1], meta[2], meta[3], meta[4])
                quality = con.execute("""SELECT AVG(q.score),ARG_MAX(q.niveau,q.score) FROM qualite_imports q
                    JOIN journal_executions j ON j.execution_id=q.execution_id WHERE j.table_destination=?""", [name]).fetchone()
                con.execute("""INSERT OR REPLACE INTO catalogue_raw
                    (table_name,type_raw,trimestre,annee,regimes,institutions,lignes,colonnes,
                     score_qualite,niveau_qualite,derniere_execution_id,derniere_mise_a_jour)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)""",
                    [name, raw_type, meta[0], meta[1], meta[2], meta[3], lines, columns,
                     quality[0], quality[1], meta[4]])
            if names:
                placeholders = ",".join("?" for _ in names)
                con.execute(f"DELETE FROM catalogue_raw WHERE table_name NOT IN ({placeholders})", names)
            else:
                con.execute("DELETE FROM catalogue_raw")
            return con.execute("""SELECT table_name,lignes,type_raw,trimestre,annee,score_qualite,niveau_qualite
                FROM catalogue_raw ORDER BY table_name""").fetchall()

    def list(self) -> list[tuple]:
        with self.db.connect() as con:
            rows = con.execute("SELECT table_name,lignes FROM catalogue_raw ORDER BY table_name").fetchall()
        return rows or [(row[0], row[1]) for row in self.refresh()]

    def list_detailed(self) -> list[tuple]:
        with self.db.connect() as con:
            return con.execute("""SELECT table_name,type_raw,trimestre,annee,regimes,institutions,
                    lignes,colonnes,ROUND(score_qualite,2),niveau_qualite,derniere_mise_a_jour
                FROM catalogue_raw ORDER BY table_name""").fetchall()


@dataclass
class TreatmentToken:
    treatment_id: str
    started: float


class TreatmentJournalService:
    def __init__(self, db):
        self.db = db

    def start(self, operation: str, details: dict | None = None) -> TreatmentToken:
        token = TreatmentToken(str(uuid.uuid4()), time.perf_counter())
        with self.db.connect() as con:
            con.execute("""INSERT INTO journal_traitements
                (traitement_id,operation,statut,details_json) VALUES (?,?,'EN_COURS',?)""",
                [token.treatment_id, operation or "Traitement SICORPA",
                 json.dumps(details or {}, ensure_ascii=False)])
        return token

    def finish(self, token: TreatmentToken, result=None) -> None:
        duration = time.perf_counter() - token.started
        object_id = None
        lines = None
        output = None
        if isinstance(result, dict):
            object_id = next((result.get(k) for k in ("comparison_id","fusion_id","campaign_id","group_id","execution_id") if result.get(k)), None)
            lines = next((result.get(k) for k in ("rows","base_rows","lignes") if result.get(k) is not None), None)
            output = result.get("path") or result.get("folder")
        elif isinstance(result, (str, bytes)):
            object_id = str(result)
        with self.db.connect() as con:
            con.execute("""UPDATE journal_traitements SET statut='TERMINE',date_fin=CURRENT_TIMESTAMP,
                duree_secondes=?,lignes=?,objet_id=?,fichier_sortie=? WHERE traitement_id=?""",
                [duration, lines, object_id, str(output) if output else None, token.treatment_id])

    def fail(self, token: TreatmentToken, exc: Exception) -> None:
        with self.db.connect() as con:
            con.execute("""UPDATE journal_traitements SET statut='ERREUR',date_fin=CURRENT_TIMESTAMP,
                duree_secondes=?,message=? WHERE traitement_id=?""",
                [time.perf_counter()-token.started, str(exc), token.treatment_id])

    def list_recent(self, limit: int = 200) -> list[tuple]:
        with self.db.connect() as con:
            return con.execute("""SELECT operation,statut,date_debut,date_fin,ROUND(duree_secondes,3),
                    lignes,objet_id,message FROM journal_traitements
                ORDER BY date_debut DESC LIMIT ?""", [max(1, min(int(limit), 2000))]).fetchall()


class ObservedIngestionProxy:
    """Ajoute qualite et catalogue sans modifier les loaders historiques."""
    def __init__(self, delegate, db, quality: DataQualityService, catalog: RawCatalogService):
        self._delegate = delegate
        self._db = db
        self._quality = quality
        self._catalog = catalog

    def __getattr__(self, name):
        return getattr(self._delegate, name)

    def _run(self, method: str, *args, **kwargs):
        execution_id = getattr(self._delegate, method)(*args, **kwargs)
        try:
            self._quality.calculate(execution_id)
            self._catalog.refresh()
        except Exception:
            # L'import reste valide meme si la metrologie secondaire echoue.
            pass
        return execution_id

    def load_access(self, *args, **kwargs):
        return self._run("load_access", *args, **kwargs)

    def load_excel(self, *args, **kwargs):
        return self._run("load_excel", *args, **kwargs)

    def load_payroll_excel(self, *args, **kwargs):
        return self._run("load_payroll_excel", *args, **kwargs)
