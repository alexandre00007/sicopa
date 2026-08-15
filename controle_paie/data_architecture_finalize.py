from __future__ import annotations

FINAL_DATA_SCHEMA_VERSION = 3


FINAL_MIGRATION_STATEMENTS = [
    "ALTER TABLE resultats_comparaison_raw_periode ADD COLUMN IF NOT EXISTS lignes_source_a BIGINT DEFAULT 0",
    "ALTER TABLE resultats_comparaison_raw_periode ADD COLUMN IF NOT EXISTS lignes_source_b BIGINT DEFAULT 0",
    "ALTER TABLE resultats_comparaison_raw_periode ADD COLUMN IF NOT EXISTS executions_a BIGINT DEFAULT 0",
    "ALTER TABLE resultats_comparaison_raw_periode ADD COLUMN IF NOT EXISTS executions_b BIGINT DEFAULT 0",
    "ALTER TABLE resultats_comparaison_raw_periode ADD COLUMN IF NOT EXISTS numeros_lignes_a VARCHAR",
    "ALTER TABLE resultats_comparaison_raw_periode ADD COLUMN IF NOT EXISTS numeros_lignes_b VARCHAR",
    "ALTER TABLE resultats_comparaison_raw_periode ADD COLUMN IF NOT EXISTS montants_distincts_a BIGINT DEFAULT 0",
    "ALTER TABLE resultats_comparaison_raw_periode ADD COLUMN IF NOT EXISTS montants_distincts_b BIGINT DEFAULT 0",
    "ALTER TABLE resultats_comparaison_raw_periode ADD COLUMN IF NOT EXISTS situation_occurrences VARCHAR",
    "ALTER TABLE resultats_comparaison_raw_periode ADD COLUMN IF NOT EXISTS ecart_lignes BIGINT DEFAULT 0",
    """CREATE TABLE IF NOT EXISTS occurrences_comparaison_raw (
        comparaison_id VARCHAR NOT NULL,
        cote VARCHAR NOT NULL,
        table_source VARCHAR,
        execution_id VARCHAR,
        ligne_paie_id VARCHAR,
        ligne_source BIGINT,
        matricule_normalise VARCHAR,
        nom_normalise VARCHAR,
        nom VARCHAR,
        prenom VARCHAR,
        institution_id VARCHAR,
        regime VARCHAR,
        section VARCHAR,
        categorie VARCHAR,
        grade VARCHAR,
        unite_affectation VARCHAR,
        province VARCHAR,
        brut DECIMAL(38,2),
        net DECIMAL(38,2)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_occ_cmp_raw_identite ON occurrences_comparaison_raw(comparaison_id,cote,matricule_normalise,nom_normalise)",
    "CREATE INDEX IF NOT EXISTS idx_sources_cmp_raw_id ON sources_comparaison_raw_periode(comparaison_id,cote,execution_id)",
    "CREATE INDEX IF NOT EXISTS idx_sources_fusion_raw_id ON sources_fusion_raw(fusion_id,execution_id)",
    "CREATE INDEX IF NOT EXISTS idx_fusions_raw_table ON fusions_raw(table_fusion,trimestre,annee)",
]


REQUIRED_TABLES = {
    "migrations_sicorpa",
    "catalogue_raw",
    "qualite_imports",
    "journal_traitements",
    "comparaisons_regimes",
    "resultats_comparaison_regimes",
    "comparaisons_raw_periode",
    "sources_comparaison_raw_periode",
    "resultats_comparaison_raw_periode",
    "occurrences_comparaison_raw",
    "fusions_raw",
    "sources_fusion_raw",
    "resultats_fusion_multi",
    "versions_analyses",
}

REQUIRED_RAW_RESULT_COLUMNS = {
    "lignes_source_a", "lignes_source_b", "executions_a", "executions_b",
    "numeros_lignes_a", "numeros_lignes_b", "montants_distincts_a",
    "montants_distincts_b", "situation_occurrences", "ecart_lignes",
}


def finalize_data_architecture(db) -> None:
    """Finalise le Lot 2 sans supprimer les anciens ensure_schema idempotents."""
    with db.connect() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS migrations_sicorpa (
            version INTEGER PRIMARY KEY, nom VARCHAR NOT NULL,
            applique_le TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        applied = con.execute("SELECT 1 FROM migrations_sicorpa WHERE version=?", [FINAL_DATA_SCHEMA_VERSION]).fetchone()
        if applied:
            return
        con.execute("BEGIN")
        try:
            for statement in FINAL_MIGRATION_STATEMENTS:
                con.execute(statement)
            con.execute("INSERT INTO migrations_sicorpa(version,nom) VALUES (?,?)",
                        [FINAL_DATA_SCHEMA_VERSION, "data_architecture_final_v3"])
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise


def schema_health(db) -> dict:
    """Controle que le schema requis par les traitements actifs est disponible."""
    with db.connect() as con:
        existing_tables = {row[0] for row in con.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
        ).fetchall()}
        missing_tables = sorted(REQUIRED_TABLES - existing_tables)
        columns = {row[0] for row in con.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema='main' AND table_name='resultats_comparaison_raw_periode'"
        ).fetchall()}
        missing_columns = sorted(REQUIRED_RAW_RESULT_COLUMNS - columns)
        versions = [int(row[0]) for row in con.execute(
            "SELECT version FROM migrations_sicorpa ORDER BY version"
        ).fetchall()] if "migrations_sicorpa" in existing_tables else []
    ok = not missing_tables and not missing_columns and FINAL_DATA_SCHEMA_VERSION in versions
    return {
        "ok": ok,
        "version": max(versions) if versions else 0,
        "missing_tables": missing_tables,
        "missing_columns": missing_columns,
        "message": "Schéma de données opérationnel" if ok else "Schéma incomplet",
    }


def assert_schema_health(db) -> dict:
    health = schema_health(db)
    if not health["ok"]:
        details = []
        if health["missing_tables"]:
            details.append("tables manquantes: " + ", ".join(health["missing_tables"]))
        if health["missing_columns"]:
            details.append("colonnes manquantes: " + ", ".join(health["missing_columns"]))
        raise RuntimeError("Architecture de données SICORPA incomplète — " + " ; ".join(details))
    return health
