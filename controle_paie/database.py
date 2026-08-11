from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Union

import duckdb


class Database:
    def __init__(self, path: Union[Path, str]):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[duckdb.DuckDBPyConnection]:
        connection = duckdb.connect(str(self.path))
        connection.execute("SET memory_limit='2GB'")
        connection.execute("SET threads=4")
        try:
            yield connection
        finally:
            connection.close()

    def migrate(self) -> None:
        statements = [
            """CREATE TABLE IF NOT EXISTS sicorpa_meta (cle VARCHAR PRIMARY KEY, valeur VARCHAR NOT NULL, modifie_le TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
            """CREATE TABLE IF NOT EXISTS institutions (
                institution_id VARCHAR PRIMARY KEY, code VARCHAR UNIQUE NOT NULL,
                nom_officiel VARCHAR NOT NULL, nom_normalise VARCHAR NOT NULL,
                actif BOOLEAN DEFAULT TRUE, cree_le TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
            """CREATE TABLE IF NOT EXISTS institution_aliases (
                alias_normalise VARCHAR PRIMARY KEY, institution_id VARCHAR NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS institution_regimes (
                institution_id VARCHAR NOT NULL, regime VARCHAR NOT NULL,
                section_access VARCHAR, categorie_access VARCHAR, unite_access VARCHAR,
                date_debut DATE, date_fin DATE)""",
            """CREATE TABLE IF NOT EXISTS config_regimes (
                code VARCHAR PRIMARY KEY, libelle VARCHAR NOT NULL,
                table_pattern VARCHAR NOT NULL, raw_table VARCHAR NOT NULL,
                actif BOOLEAN DEFAULT TRUE, cree_le TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                modifie_le TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
            """CREATE TABLE IF NOT EXISTS config_mapping_colonnes (
                regime VARCHAR NOT NULL, type_source VARCHAR NOT NULL,
                colonne_source VARCHAR NOT NULL, colonne_standard VARCHAR NOT NULL,
                obligatoire BOOLEAN DEFAULT FALSE,
                PRIMARY KEY (regime, type_source, colonne_source))""",
            """CREATE TABLE IF NOT EXISTS config_filtres_traitement (
                filtre_id VARCHAR PRIMARY KEY, institution_id VARCHAR NOT NULL,
                regime VARCHAR NOT NULL, colonne VARCHAR NOT NULL,
                operateur VARCHAR NOT NULL, valeur VARCHAR,
                actif BOOLEAN DEFAULT TRUE, cree_le TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
            """CREATE TABLE IF NOT EXISTS journal_executions (
                execution_id VARCHAR, type_operation VARCHAR, fichier_source VARCHAR,
                table_source VARCHAR, table_destination VARCHAR, institution_id VARCHAR,
                regime VARCHAR, trimestre VARCHAR, annee INTEGER, mode_chargement VARCHAR,
                lignes_lues BIGINT DEFAULT 0, lignes_chargees BIGINT DEFAULT 0,
                lignes_rejetees BIGINT DEFAULT 0, statut VARCHAR, message VARCHAR,
                date_debut TIMESTAMP DEFAULT CURRENT_TIMESTAMP, date_fin TIMESTAMP)""",
            """CREATE TABLE IF NOT EXISTS schemas_sources (
                execution_id VARCHAR, type_source VARCHAR, objet_source VARCHAR,
                colonne_source VARCHAR, type_source_colonne VARCHAR,
                colonne_standard VARCHAR, obligatoire BOOLEAN DEFAULT FALSE)""",
            """CREATE TABLE IF NOT EXISTS paie_standardisee (
                ligne_paie_id VARCHAR, execution_id VARCHAR, institution_id VARCHAR,
                regime VARCHAR, trimestre VARCHAR, annee INTEGER, table_source VARCHAR,
                matricule_source VARCHAR, matricule_normalise VARCHAR, nom VARCHAR,
                prenom VARCHAR, nom_normalise VARCHAR, section VARCHAR, categorie VARCHAR,
                grade VARCHAR, unite_affectation VARCHAR, province VARCHAR,
                remuneration_base DECIMAL(38,2), transport DECIMAL(38,2),
                prime DECIMAL(38,2), logement DECIMAL(38,2),
                pension_rente DECIMAL(38,2), autres_remunerations DECIMAL(38,2),
                retenues DECIMAL(38,2), montant_net DECIMAL(38,2),
                remuneration_brute_calculee DECIMAL(38,2), ligne_source BIGINT)""",
            """CREATE TABLE IF NOT EXISTS declaratif_standardise (
                ligne_declaratif_id VARCHAR, execution_id VARCHAR, institution_id VARCHAR,
                regime VARCHAR, trimestre VARCHAR, annee INTEGER, fichier_source VARCHAR,
                feuille_source VARCHAR, matricule_source VARCHAR, matricule_normalise VARCHAR,
                nom VARCHAR, prenom VARCHAR, nom_normalise VARCHAR, grade VARCHAR,
                service VARCHAR, unite_affectation VARCHAR, province VARCHAR,
                remuneration_declaree DECIMAL(38,2), statut_agent VARCHAR, ligne_source BIGINT)""",
            """CREATE TABLE IF NOT EXISTS resultats_rapprochement (
                rapprochement_id VARCHAR, execution_id VARCHAR, institution_id VARCHAR,
                regime VARCHAR, trimestre VARCHAR, annee INTEGER, ligne_paie_id VARCHAR,
                ligne_declaratif_id VARCHAR, methode_correspondance VARCHAR,
                score_correspondance DOUBLE, statut_rapprochement VARCHAR,
                masse_financiere_controlee DECIMAL(38,2), impact_potentiel DECIMAL(38,2),
                impact_confirme DECIMAL(38,2) DEFAULT 0, statut_validation VARCHAR DEFAULT 'A_VALIDER',
                commentaire_validation VARCHAR, date_validation TIMESTAMP, validateur VARCHAR)""",
            """CREATE TABLE IF NOT EXISTS rejets_importation (
                execution_id VARCHAR, source VARCHAR, ligne_source BIGINT,
                code_rejet VARCHAR, message VARCHAR, donnees_json VARCHAR)""",
        ]
        with self.connect() as con:
            for statement in statements:
                con.execute(statement)
            from .runtime import CURRENT_SCHEMA_VERSION
            con.execute("""INSERT INTO sicorpa_meta (cle,valeur) VALUES ('schema_version',?)
                ON CONFLICT(cle) DO UPDATE SET valeur=excluded.valeur,modifie_le=now()""",[str(CURRENT_SCHEMA_VERSION)])

    def add_institution(self, code: str, name: str) -> str:
        import re, unicodedata, uuid
        normalized = ''.join(c for c in unicodedata.normalize('NFKD', name) if not unicodedata.combining(c))
        normalized = re.sub(r"[^A-Z0-9]", "", normalized.upper())
        with self.connect() as con:
            row = con.execute("SELECT institution_id FROM institutions WHERE code = ?", [code]).fetchone()
            if row:
                return row[0]
            identifier = str(uuid.uuid4())
            con.execute("INSERT INTO institutions VALUES (?, ?, ?, ?, TRUE, CURRENT_TIMESTAMP)", [identifier, code, name, normalized])
            return identifier

    def list_institutions(self) -> list[tuple]:
        with self.connect() as con:
            return con.execute("SELECT institution_id, code, nom_officiel FROM institutions WHERE actif ORDER BY nom_officiel").fetchall()

    def upsert_regime(self, code: str, label: str, table_pattern: str, raw_table: str,
                      active: bool = True) -> None:
        import re
        code = code.strip().upper(); raw_table = raw_table.strip().lower()
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", code):
            raise ValueError("Le code régime doit contenir uniquement lettres, chiffres et underscores.")
        if not label.strip(): raise ValueError("Le libellé du régime est obligatoire.")
        if not re.fullmatch(r"[a-z_][a-z0-9_]*", raw_table):
            raise ValueError("La table RAW doit être un identifiant DuckDB valide.")
        try: re.compile(table_pattern)
        except re.error as exc: raise ValueError(f"Motif de table invalide : {exc}") from exc
        with self.connect() as con:
            con.execute("""INSERT INTO config_regimes (code,libelle,table_pattern,raw_table,actif)
                VALUES (?,?,?,?,?) ON CONFLICT(code) DO UPDATE SET libelle=excluded.libelle,
                table_pattern=excluded.table_pattern,raw_table=excluded.raw_table,
                actif=excluded.actif,modifie_le=now()""",
                [code,label.strip(),table_pattern.strip(),raw_table,active])

    def list_regimes(self, active_only: bool = True) -> list[tuple]:
        query="SELECT code,libelle,table_pattern,raw_table,actif FROM config_regimes"
        if active_only: query += " WHERE actif"
        with self.connect() as con: return con.execute(query+" ORDER BY libelle").fetchall()

    def set_regime_active(self, code: str, active: bool) -> None:
        with self.connect() as con:
            con.execute("UPDATE config_regimes SET actif=?,modifie_le=now() WHERE code=?",[active,code])

    def upsert_column_mapping(self, regime: str, source_type: str, source_column: str,
                              target_column: str, required: bool = False) -> None:
        source_type = source_type.upper()
        if source_type not in {"ACCESS", "EXCEL"}: raise ValueError("Le type de source doit être ACCESS ou EXCEL.")
        if not all([regime.strip(), source_column.strip(), target_column.strip()]): raise ValueError("Régime, colonne source et colonne standard sont obligatoires.")
        with self.connect() as con:
            con.execute("""INSERT INTO config_mapping_colonnes (regime,type_source,colonne_source,colonne_standard,obligatoire)
                VALUES (?,?,?,?,?) ON CONFLICT(regime,type_source,colonne_source) DO UPDATE SET
                colonne_standard=excluded.colonne_standard,obligatoire=excluded.obligatoire""",
                [regime,source_type,source_column.strip(),target_column.strip(),required])

    def list_column_mappings(self, regime: str = "", source_type: str = "") -> list[tuple]:
        conditions=[];params=[]
        if regime:conditions.append("regime=?");params.append(regime)
        if source_type:conditions.append("type_source=?");params.append(source_type.upper())
        query="SELECT regime,type_source,colonne_source,colonne_standard,obligatoire FROM config_mapping_colonnes"
        if conditions:query += " WHERE " + " AND ".join(conditions)
        with self.connect() as con:return con.execute(query+" ORDER BY regime,type_source,colonne_source",params).fetchall()

    def get_column_mapping(self, regime: str, source_type: str) -> dict:
        return {row[2]:row[3] for row in self.list_column_mappings(regime,source_type)}

    def required_source_columns(self, regime: str, source_type: str) -> list[str]:
        return [row[2] for row in self.list_column_mappings(regime,source_type) if row[4]]

    def delete_column_mapping(self, regime: str, source_type: str, source_column: str) -> None:
        with self.connect() as con:con.execute("DELETE FROM config_mapping_colonnes WHERE regime=? AND type_source=? AND colonne_source=?",[regime,source_type.upper(),source_column])

    PAYROLL_FILTER_COLUMNS = {
        "table_source", "matricule_source", "nom", "prenom", "section", "categorie",
        "grade", "unite_affectation", "province", "remuneration_base", "transport",
        "prime", "logement", "pension_rente", "autres_remunerations", "retenues",
        "montant_net", "remuneration_brute_calculee",
    }
    FILTER_OPERATORS = {"égal à", "différent de", "contient", "commence par", ">", ">=", "<", "<="}

    def add_treatment_filter(self, institution_id: str, regime: str, column: str, operator: str, value: str) -> str:
        import uuid
        if column not in self.PAYROLL_FILTER_COLUMNS: raise ValueError("Colonne de listing non autorisée.")
        if operator not in self.FILTER_OPERATORS: raise ValueError("Opérateur de filtre non autorisé.")
        if not str(value).strip(): raise ValueError("Le contenu recherché est obligatoire.")
        identifier=str(uuid.uuid4())
        with self.connect() as con:
            con.execute("INSERT INTO config_filtres_traitement VALUES (?,?,?,?,?,?,?,CURRENT_TIMESTAMP)",[identifier,institution_id,regime,column,operator,str(value).strip(),True])
        return identifier

    def list_treatment_filters(self, institution_id: str, regime: str) -> list[tuple]:
        with self.connect() as con:
            return con.execute("SELECT filtre_id,colonne,operateur,valeur FROM config_filtres_traitement WHERE institution_id=? AND regime=? AND actif ORDER BY cree_le",[institution_id,regime]).fetchall()

    def delete_treatment_filter(self, filter_id: str) -> None:
        with self.connect() as con: con.execute("DELETE FROM config_filtres_traitement WHERE filtre_id=?",[filter_id])

    def clear_treatment_filters(self, institution_id: str, regime: str) -> None:
        with self.connect() as con: con.execute("DELETE FROM config_filtres_traitement WHERE institution_id=? AND regime=?",[institution_id,regime])

    def payroll_filter_clause(self, institution_id: str, regime: str, alias: str = "") -> tuple[str,list]:
        prefix=f"{alias}." if alias else "";parts=[];params=[]
        sql_ops={"égal à":"=", "différent de":"<>", ">":">", ">=":">=", "<":"<", "<=":"<="}
        numeric={"remuneration_base","transport","prime","logement","pension_rente","autres_remunerations","retenues","montant_net","remuneration_brute_calculee"}
        for _,column,operator,value in self.list_treatment_filters(institution_id,regime):
            if column not in self.PAYROLL_FILTER_COLUMNS or operator not in self.FILTER_OPERATORS: continue
            expression=f'{prefix}"{column}"'
            if operator in sql_ops:
                parts.append(f"{expression} {sql_ops[operator]} ?")
                if column in numeric:
                    try: params.append(float(str(value).replace(" ","").replace(",",".")))
                    except ValueError: raise ValueError(f"La valeur du filtre {column} doit être numérique.")
                else: params.append(value)
            elif operator == "contient": parts.append(f"LOWER(CAST({expression} AS VARCHAR)) LIKE ?");params.append(f"%{str(value).lower()}%")
            else: parts.append(f"LOWER(CAST({expression} AS VARCHAR)) LIKE ?");params.append(f"{str(value).lower()}%")
        return ((" AND "+" AND ".join(parts)) if parts else "",params)
