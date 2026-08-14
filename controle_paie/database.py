from __future__ import annotations

import json
import os
import platform
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Union

import duckdb


class Database:
    def __init__(self, path: Union[Path, str]):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.temp_directory=self.path.parent/".duckdb_tmp"
        self.temp_directory.mkdir(parents=True,exist_ok=True)
        self.threads=self._configured_threads()
        self.memory_limit_mb=self._configured_memory_limit_mb()

    @staticmethod
    def _available_memory_bytes() -> int:
        """Return currently available memory without adding a runtime dependency."""
        try:
            if platform.system()=="Windows":
                import ctypes
                class MemoryStatus(ctypes.Structure):
                    _fields_=[("dwLength",ctypes.c_ulong),("dwMemoryLoad",ctypes.c_ulong),
                        ("ullTotalPhys",ctypes.c_ulonglong),("ullAvailPhys",ctypes.c_ulonglong),
                        ("ullTotalPageFile",ctypes.c_ulonglong),("ullAvailPageFile",ctypes.c_ulonglong),
                        ("ullTotalVirtual",ctypes.c_ulonglong),("ullAvailVirtual",ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual",ctypes.c_ulonglong)]
                status=MemoryStatus();status.dwLength=ctypes.sizeof(status)
                if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                    return int(status.ullAvailPhys)
            meminfo=Path("/proc/meminfo")
            if meminfo.exists():
                for line in meminfo.read_text(encoding="utf-8").splitlines():
                    if line.startswith("MemAvailable:"):
                        return int(line.split()[1])*1024
            return int(os.sysconf("SC_AVPHYS_PAGES"))*int(os.sysconf("SC_PAGE_SIZE"))
        except Exception:
            return 3*1024**3

    @staticmethod
    def _configured_threads() -> int:
        detected=max(1,int(os.cpu_count() or 4))
        try:return max(1,min(32,int(os.environ.get("SICORPA_DUCKDB_THREADS",detected))))
        except ValueError:return min(32,detected)

    def _configured_memory_limit_mb(self) -> int:
        try:
            override=int(os.environ.get("SICORPA_DUCKDB_MEMORY_MB","0"))
            if override>0:return max(512,override)
        except ValueError:
            pass
        # Keep enough memory for Tkinter, Python/OpenPyXL and the operating system.
        available_mb=max(768,self._available_memory_bytes()//(1024**2))
        return int(max(512,min(8192,available_mb*0.60)))

    def tuning_info(self) -> dict:
        return {"threads":self.threads,"memory_limit_mb":self.memory_limit_mb,
                "temp_directory":str(self.temp_directory)}

    @contextmanager
    def connect(self) -> Iterator[duckdb.DuckDBPyConnection]:
        connection = duckdb.connect(str(self.path))
        escaped_temp=str(self.temp_directory).replace("'","''")
        connection.execute(f"SET memory_limit='{self.memory_limit_mb}MB'")
        connection.execute(f"SET threads={self.threads}")
        connection.execute(f"SET temp_directory='{escaped_temp}'")
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
            """CREATE TABLE IF NOT EXISTS config_composantes_financieres (
                code VARCHAR PRIMARY KEY, libelle VARCHAR NOT NULL,
                colonne_standard VARCHAR, systeme BOOLEAN DEFAULT FALSE,
                actif BOOLEAN DEFAULT TRUE, cree_le TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
            """CREATE TABLE IF NOT EXISTS config_formules_impact (
                formule_id VARCHAR PRIMARY KEY, nom VARCHAR NOT NULL,
                institution_id VARCHAR, regime VARCHAR, rubrique VARCHAR NOT NULL,
                trimestre_debut VARCHAR NOT NULL, annee_debut INTEGER NOT NULL,
                aggregation VARCHAR NOT NULL, termes_json VARCHAR NOT NULL,
                version INTEGER NOT NULL, actif BOOLEAN DEFAULT TRUE,
                cree_le TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
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
            """CREATE TABLE IF NOT EXISTS campagnes_analyse_multi (
                campagne_id VARCHAR PRIMARY KEY, institution_declarative_id VARCHAR NOT NULL,
                regime_declaratif VARCHAR NOT NULL, trimestre VARCHAR NOT NULL, annee INTEGER NOT NULL,
                statut VARCHAR NOT NULL, lignes_base BIGINT DEFAULT 0, lignes_declaratives BIGINT DEFAULT 0,
                cree_le TIMESTAMP DEFAULT CURRENT_TIMESTAMP, termine_le TIMESTAMP)""",
            """CREATE TABLE IF NOT EXISTS sources_analyse_multi (
                campagne_id VARCHAR, execution_id VARCHAR, institution_id VARCHAR, regime VARCHAR,
                table_source VARCHAR, lignes_disponibles BIGINT, lignes_retenues BIGINT,
                filtres_appliques VARCHAR, PRIMARY KEY(campagne_id,execution_id))""",
            """CREATE TABLE IF NOT EXISTS base_analyse_multi AS
                SELECT CAST(NULL AS VARCHAR) campagne_id,p.* FROM paie_standardisee p WHERE FALSE""",
            """CREATE TABLE IF NOT EXISTS resultats_analyse_multi (
                resultat_id VARCHAR, campagne_id VARCHAR, ligne_declaratif_id VARCHAR, ligne_paie_id VARCHAR,
                institution_declarative_id VARCHAR, regime_declaratif VARCHAR,
                institution_paiement_id VARCHAR, regime_paiement VARCHAR,
                execution_paiement_id VARCHAR, table_source VARCHAR,
                methode_correspondance VARCHAR, statut_analyse VARCHAR,
                nombre_occurrences BIGINT DEFAULT 0, nombre_regimes BIGINT DEFAULT 0,
                masse_financiere DECIMAL(38,2) DEFAULT 0, impact_potentiel DECIMAL(38,2) DEFAULT 0,
                formule_impact_id VARCHAR, matricule_normalise VARCHAR, nom_normalise VARCHAR)""",
            """CREATE TABLE IF NOT EXISTS groupes_analyse_listing (
                groupe_id VARCHAR PRIMARY KEY, nom VARCHAR NOT NULL, trimestre VARCHAR NOT NULL,
                annee INTEGER NOT NULL, statut VARCHAR NOT NULL, lignes_base BIGINT DEFAULT 0,
                cree_le TIMESTAMP DEFAULT CURRENT_TIMESTAMP, termine_le TIMESTAMP,
                archive BOOLEAN DEFAULT FALSE, dossier_export VARCHAR)""",
            """CREATE TABLE IF NOT EXISTS sources_analyse_listing (
                groupe_id VARCHAR, execution_id VARCHAR, institution_id VARCHAR, regime VARCHAR,
                table_source VARCHAR, lignes_disponibles BIGINT, lignes_retenues BIGINT,
                filtres_appliques VARCHAR, PRIMARY KEY(groupe_id,execution_id))""",
            """CREATE TABLE IF NOT EXISTS base_analyse_listing AS
                SELECT CAST(NULL AS VARCHAR) groupe_id,p.* FROM paie_standardisee p WHERE FALSE""",
            """CREATE TABLE IF NOT EXISTS resultats_analyse_listing (
                resultat_id VARCHAR, groupe_id VARCHAR, ligne_paie_id VARCHAR,
                institution_id VARCHAR, regime VARCHAR, execution_id VARCHAR, table_source VARCHAR,
                statut_analyse VARCHAR, occurrences_matricule BIGINT DEFAULT 0,
                occurrences_nom BIGINT DEFAULT 0, nombre_regimes BIGINT DEFAULT 0,
                nombre_institutions BIGINT DEFAULT 0, rang_occurrence BIGINT DEFAULT 1,
                masse_financiere DECIMAL(38,2) DEFAULT 0,
                impact_potentiel DECIMAL(38,2) DEFAULT 0, formule_impact_id VARCHAR,
                matricule_normalise VARCHAR, nom_normalise VARCHAR)""",
        ]
        with self.connect() as con:
            for statement in statements:
                con.execute(statement)
            con.execute("ALTER TABLE paie_standardisee ADD COLUMN IF NOT EXISTS composantes_supplementaires_json VARCHAR DEFAULT '{}'")
            con.execute("ALTER TABLE paie_standardisee ADD COLUMN IF NOT EXISTS formule_remuneration_id VARCHAR")
            con.execute("ALTER TABLE base_analyse_multi ADD COLUMN IF NOT EXISTS composantes_supplementaires_json VARCHAR DEFAULT '{}'")
            con.execute("ALTER TABLE base_analyse_multi ADD COLUMN IF NOT EXISTS formule_remuneration_id VARCHAR")
            con.execute("ALTER TABLE base_analyse_listing ADD COLUMN IF NOT EXISTS composantes_supplementaires_json VARCHAR DEFAULT '{}'")
            con.execute("ALTER TABLE base_analyse_listing ADD COLUMN IF NOT EXISTS formule_remuneration_id VARCHAR")
            con.execute("ALTER TABLE resultats_analyse_listing ADD COLUMN IF NOT EXISTS rang_occurrence BIGINT DEFAULT 1")
            con.execute("ALTER TABLE resultats_rapprochement ADD COLUMN IF NOT EXISTS formule_impact_id VARCHAR")
            con.execute("CREATE INDEX IF NOT EXISTS idx_paie_execution ON paie_standardisee(execution_id)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_paie_periode_matricule ON paie_standardisee(trimestre,annee,matricule_normalise)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_paie_scope ON paie_standardisee(institution_id,regime,trimestre,annee)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_paie_scope_nom ON paie_standardisee(institution_id,regime,trimestre,annee,nom_normalise)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_declaratif_execution ON declaratif_standardise(execution_id)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_declaratif_periode_matricule ON declaratif_standardise(trimestre,annee,matricule_normalise)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_declaratif_scope ON declaratif_standardise(institution_id,regime,trimestre,annee)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_declaratif_scope_nom ON declaratif_standardise(institution_id,regime,trimestre,annee,nom_normalise)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_resultats_scope ON resultats_rapprochement(institution_id,regime,trimestre,annee)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_base_multi_campagne_matricule ON base_analyse_multi(campagne_id,matricule_normalise)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_base_multi_campagne_execution ON base_analyse_multi(campagne_id,execution_id)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_resultats_multi_campagne ON resultats_analyse_multi(campagne_id)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_resultats_multi_declaratif ON resultats_analyse_multi(campagne_id,ligne_declaratif_id)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_base_listing_groupe_matricule ON base_analyse_listing(groupe_id,matricule_normalise)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_base_listing_groupe_execution ON base_analyse_listing(groupe_id,execution_id)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_resultats_listing_groupe ON resultats_analyse_listing(groupe_id)")
            con.execute("ALTER TABLE campagnes_analyse_multi ADD COLUMN IF NOT EXISTS declaratif_execution_id VARCHAR")
            con.execute("ALTER TABLE campagnes_analyse_multi ADD COLUMN IF NOT EXISTS archivee BOOLEAN DEFAULT FALSE")
            con.execute("ALTER TABLE campagnes_analyse_multi ADD COLUMN IF NOT EXISTS dossier_export VARCHAR")
            builtins=[
                ("REMUNERATION_BASE","Rémunération de base","remuneration_base"),("TRANSPORT","Transport","transport"),
                ("PRIME","Prime","prime"),("LOGEMENT","Logement","logement"),("PENSION_RENTE","Pension / rente","pension_rente"),
                ("AUTRES_REMUNERATIONS","Autres rémunérations","autres_remunerations"),("RETENUES","Retenues","retenues"),
                ("MONTANT_NET","Montant net","montant_net"),
                ("REMUNERATION_BRUTE_CALCULEE","Rémunération brute calculée","remuneration_brute_calculee")]
            for code,label,column in builtins:
                con.execute("""INSERT INTO config_composantes_financieres(code,libelle,colonne_standard,systeme,actif)
                    VALUES (?,?,?,TRUE,TRUE) ON CONFLICT(code) DO UPDATE SET libelle=excluded.libelle,colonne_standard=excluded.colonne_standard""",[code,label,column])
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

    def delete_institution(self, institution_id: str) -> None:
        if not institution_id:
            raise ValueError("L’identifiant de l’institution est obligatoire.")
        with self.connect() as con:
            con.execute("DELETE FROM institution_aliases WHERE institution_id=?", [institution_id])
            con.execute("DELETE FROM institution_regimes WHERE institution_id=?", [institution_id])
            con.execute("DELETE FROM config_filtres_traitement WHERE institution_id=?", [institution_id])
            con.execute("DELETE FROM config_formules_impact WHERE institution_id=?", [institution_id])
            con.execute("DELETE FROM institutions WHERE institution_id=?", [institution_id])

    def list_institutions(self) -> list[tuple]:
        with self.connect() as con:
            return con.execute("SELECT institution_id, code, nom_officiel FROM institutions WHERE actif ORDER BY nom_officiel").fetchall()

    def list_declaration_imports(self, institution_id: str = "", regime: str = "",
                                 quarter: str = "", year: int | None = None) -> list[tuple]:
        """List auditable declarative imports and whether derived analyses use them."""
        conditions = ["j.type_operation='IMPORT_EXCEL'", "j.table_destination='declaratif_standardise'",
                      "COALESCE(j.statut,'')<>'SUPPRIME'"]
        params = []
        for column, value in (("j.institution_id", institution_id), ("j.regime", regime),
                              ("j.trimestre", quarter), ("j.annee", year)):
            if value not in {"", None}:
                conditions.append(f"{column}=?");params.append(value)
        query = f"""SELECT j.execution_id,COALESCE(i.nom_officiel,j.institution_id),j.regime,
                j.trimestre,j.annee,j.fichier_source,j.table_source,j.mode_chargement,
                (SELECT COUNT(*) FROM declaratif_standardise d WHERE d.execution_id=j.execution_id) lignes,
                COALESCE(j.date_fin,j.date_debut) date_import,
                (SELECT COUNT(DISTINCT r.execution_id) FROM resultats_rapprochement r
                 JOIN declaratif_standardise d ON d.ligne_declaratif_id=r.ligne_declaratif_id
                 WHERE d.execution_id=j.execution_id) rapprochements,
                (SELECT COUNT(*) FROM campagnes_analyse_multi c
                 WHERE c.declaratif_execution_id=j.execution_id) campagnes
            FROM journal_executions j LEFT JOIN institutions i ON i.institution_id=j.institution_id
            WHERE {' AND '.join(conditions)} ORDER BY date_import DESC"""
        with self.connect() as con:
            return con.execute(query, params).fetchall()

    def delete_declaration_import(self, execution_id: str) -> dict:
        """Delete an unused declarative import while retaining an audit journal entry."""
        with self.connect() as con:
            record = con.execute("""SELECT fichier_source,table_source,institution_id,regime,trimestre,annee
                FROM journal_executions WHERE execution_id=? AND type_operation='IMPORT_EXCEL'
                AND table_destination='declaratif_standardise' AND COALESCE(statut,'')<>'SUPPRIME'""",
                [execution_id]).fetchone()
            if not record:
                raise ValueError("Import déclaratif introuvable ou déjà supprimé.")
            lines = con.execute("SELECT COUNT(*) FROM declaratif_standardise WHERE execution_id=?",
                                [execution_id]).fetchone()[0]
            matching_refs = con.execute("""SELECT COUNT(DISTINCT r.execution_id)
                FROM resultats_rapprochement r JOIN declaratif_standardise d
                  ON d.ligne_declaratif_id=r.ligne_declaratif_id
                WHERE d.execution_id=?""", [execution_id]).fetchone()[0]
            campaign_refs = con.execute("SELECT COUNT(*) FROM campagnes_analyse_multi WHERE declaratif_execution_id=?",
                                        [execution_id]).fetchone()[0]
            if matching_refs or campaign_refs:
                usages=[]
                if matching_refs:usages.append(f"{matching_refs} rapprochement(s)")
                if campaign_refs:usages.append(f"{campaign_refs} campagne(s) multi-régimes")
                raise ValueError("Suppression bloquée : cet import est utilisé par " + " et ".join(usages) +
                                 ". Conservez-le pour garantir la traçabilité des résultats.")
            con.execute("BEGIN")
            try:
                con.execute("DELETE FROM rejets_importation WHERE execution_id=?", [execution_id])
                con.execute("DELETE FROM schemas_sources WHERE execution_id=?", [execution_id])
                con.execute("DELETE FROM declaratif_standardise WHERE execution_id=?", [execution_id])
                con.execute("""UPDATE journal_executions SET statut='SUPPRIME',
                    message=?,date_fin=CURRENT_TIMESTAMP WHERE execution_id=?""",
                    [f"Import déclaratif supprimé par l’utilisateur ({lines} lignes)", execution_id])
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
        return {"execution_id": execution_id, "lines": int(lines), "file": record[0],
                "sheet": record[1], "institution_id": record[2], "regime": record[3],
                "quarter": record[4], "year": record[5]}

    def delete_data_scope(self, institution_id: str, regime: str, quarter: str, year: int | str) -> dict:
        """Delete all standardized data for a given institution/regime/period.

        This is used by the explorer to remove a whole quarterly data scope while keeping
        configuration tables intact.
        """
        institution_id = str(institution_id).strip(); regime = str(regime).strip(); quarter = str(quarter).strip();
        if not institution_id: raise ValueError("L’identifiant de l’institution est obligatoire.")
        if not regime: raise ValueError("Le régime est obligatoire.")
        if not quarter: raise ValueError("Le trimestre est obligatoire.")
        try: year = int(year)
        except (TypeError, ValueError) as exc: raise ValueError("L’année doit être un nombre valide.") from exc
        with self.connect() as con:
            con.execute("BEGIN")
            try:
                paie_rows = con.execute("SELECT COUNT(*) FROM paie_standardisee WHERE institution_id=? AND regime=? AND trimestre=? AND annee=?",
                                       [institution_id, regime, quarter, year]).fetchone()[0]
                declaratif_rows = con.execute("SELECT COUNT(*) FROM declaratif_standardise WHERE institution_id=? AND regime=? AND trimestre=? AND annee=?",
                                              [institution_id, regime, quarter, year]).fetchone()[0]
                matching_rows = con.execute("SELECT COUNT(*) FROM resultats_rapprochement WHERE institution_id=? AND regime=? AND trimestre=? AND annee=?",
                                            [institution_id, regime, quarter, year]).fetchone()[0]
                con.execute("DELETE FROM resultats_rapprochement WHERE institution_id=? AND regime=? AND trimestre=? AND annee=?",
                            [institution_id, regime, quarter, year])
                con.execute("DELETE FROM paie_standardisee WHERE institution_id=? AND regime=? AND trimestre=? AND annee=?",
                            [institution_id, regime, quarter, year])
                con.execute("DELETE FROM declaratif_standardise WHERE institution_id=? AND regime=? AND trimestre=? AND annee=?",
                            [institution_id, regime, quarter, year])
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
        return {"institution_id": institution_id, "regime": regime,
                "quarter": quarter, "year": year,
                "paie_rows": int(paie_rows), "declaratif_rows": int(declaratif_rows),
                "matching_rows": int(matching_rows)}

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

    def delete_regime(self, code: str) -> None:
        if not code or not str(code).strip():
            raise ValueError("Le code du régime est obligatoire.")
        normalized = str(code).strip().upper()
        with self.connect() as con:
            con.execute("DELETE FROM config_mapping_colonnes WHERE regime=?", [normalized])
            con.execute("DELETE FROM config_filtres_traitement WHERE regime=?", [normalized])
            con.execute("DELETE FROM config_formules_impact WHERE regime=?", [normalized])
            con.execute("DELETE FROM institution_regimes WHERE regime=?", [normalized])
            con.execute("DELETE FROM config_regimes WHERE code=?", [normalized])

    def upsert_column_mapping(self, regime: str, source_type: str, source_column: str,
                              target_column: str, required: bool = False) -> None:
        source_type = source_type.upper()
        if source_type not in {"ACCESS", "PAIE_EXCEL", "EXCEL"}: raise ValueError("Le type de source doit être ACCESS, PAIE_EXCEL ou EXCEL.")
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

    DEFAULT_IMPACT_TERMS = [{"code":code,"coefficient":1.0} for code in ["REMUNERATION_BASE","TRANSPORT","PRIME","LOGEMENT","PENSION_RENTE","AUTRES_REMUNERATIONS"]]
    FORMULA_RUBRICS = ["*","DOUBLON_MATRICULE","DOUBLON_NOM","MATRICULE_MANQUANT","PAYE_NON_DECLARE","PAYE_HORS_PERIMETRE","CONFORME_MATRICULE","CONFORME_NOM"]
    FORMULA_AGGREGATIONS = ["TOUTES_LIGNES","OCCURRENCES_SUPPLEMENTAIRES","UNIQUE_AGENT","AUCUN_IMPACT"]

    def add_financial_component(self, code: str, label: str) -> None:
        import re
        code=code.strip().upper()
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*",code):raise ValueError("Le code composante doit contenir lettres, chiffres et underscores.")
        if not label.strip():raise ValueError("Le libellé de la composante est obligatoire.")
        with self.connect() as con:con.execute("""INSERT INTO config_composantes_financieres(code,libelle,colonne_standard,systeme,actif)
            VALUES (?,?,NULL,FALSE,TRUE) ON CONFLICT(code) DO UPDATE SET libelle=excluded.libelle,actif=TRUE""",[code,label.strip()])

    def delete_financial_component(self, code: str) -> None:
        normalized = str(code).strip().upper()
        if not normalized:
            raise ValueError("Le code de la composante est obligatoire.")
        with self.connect() as con:
            con.execute("DELETE FROM config_composantes_financieres WHERE code=?", [normalized])

    def list_financial_components(self, active_only: bool=True) -> list[tuple]:
        query="SELECT code,libelle,colonne_standard,systeme,actif FROM config_composantes_financieres"+(" WHERE actif" if active_only else "")
        with self.connect() as con:return con.execute(query+" ORDER BY systeme DESC,libelle").fetchall()

    def available_financial_components(self,institution_id: str="",regime: str="",
                                       quarter: str="",year: int | None=None) -> list[tuple]:
        """Return components backed by a mapped field or observed payroll values.

        Rows contain the code, label, standardized field, mapping presence,
        populated row count and total payroll row count in the selected perimeter.
        """
        components=self.list_financial_components();conditions=[];params=[]
        if institution_id:conditions.append("institution_id=?");params.append(institution_id)
        if regime:conditions.append("regime=?");params.append(regime)
        if quarter:conditions.append("trimestre=?");params.append(quarter)
        if year is not None:conditions.append("annee=?");params.append(int(year))
        where=" WHERE "+" AND ".join(conditions) if conditions else ""
        mapping_conditions=[];mapping_params=[]
        if regime:mapping_conditions.append("regime=?");mapping_params.append(regime)
        mapping_where=" WHERE "+" AND ".join(mapping_conditions) if mapping_conditions else ""
        with self.connect() as con:
            total=int(con.execute(f"SELECT COUNT(*) FROM paie_standardisee{where}",params).fetchone()[0])
            mapped_targets={str(row[0]) for row in con.execute(
                "SELECT DISTINCT colonne_standard FROM config_mapping_colonnes"+mapping_where,
                mapping_params).fetchall()}
            result=[]
            for code,label,column,_system,_active in components:
                target=column or f"composante_{code}"
                mapped=target in mapped_targets
                if column:
                    populated=int(con.execute(
                        f'SELECT COUNT(*) FROM paie_standardisee{where}' +
                        (" AND " if where else " WHERE ") +
                        f'ABS(COALESCE("{column}",0))>0',params).fetchone()[0])
                else:
                    populated=int(con.execute(
                        f"SELECT COUNT(*) FROM paie_standardisee{where}" +
                        (" AND " if where else " WHERE ") +
                        "json_extract_string(composantes_supplementaires_json, ?) IS NOT NULL",
                        params+[f'$.{code}']).fetchone()[0])
                if mapped or populated:
                    result.append((code,label,target,mapped,populated,total))
        return result

    def save_impact_formula(self,name: str,institution_id: str,regime: str,rubric: str,quarter: str,year: int,aggregation: str,terms: list[dict]) -> str:
        import re,uuid
        if not name.strip() or not regime.strip():raise ValueError("Nom et régime sont obligatoires.")
        if rubric not in self.FORMULA_RUBRICS:raise ValueError("Rubrique d’impact inconnue.")
        if aggregation not in self.FORMULA_AGGREGATIONS:raise ValueError("Agrégation inconnue.")
        if quarter not in {"T1","T2","T3","T4"}:raise ValueError("Trimestre d’entrée en vigueur invalide.")
        allowed={row[0] for row in self.list_financial_components()}
        clean=[]
        for term in terms:
            code=str(term.get("code","")).upper();coefficient=float(term.get("coefficient",0))
            if code not in allowed:raise ValueError(f"Composante inconnue : {code}")
            if abs(coefficient)>1000:raise ValueError("Le coefficient doit être compris entre -1000 et 1000.")
            if coefficient:clean.append({"code":code,"coefficient":coefficient})
        if aggregation!="AUCUN_IMPACT" and not clean:raise ValueError("Ajoutez au moins une composante à la formule.")
        with self.connect() as con:
            version=con.execute("SELECT COALESCE(MAX(version),0)+1 FROM config_formules_impact WHERE COALESCE(institution_id,'')=? AND regime=? AND rubrique=?",[institution_id or "",regime,rubric]).fetchone()[0]
            identifier=str(uuid.uuid4());con.execute("""INSERT INTO config_formules_impact VALUES (?,?,?,?,?,?,?,?,?,?,TRUE,CURRENT_TIMESTAMP)""",[identifier,name.strip(),institution_id or None,regime,rubric,quarter,int(year),aggregation,json.dumps(clean),version])
            return identifier

    def list_impact_formulas(self,regime: str="",institution_id: str="") -> list[tuple]:
        conditions=[];params=[]
        if regime:conditions.append("regime=?");params.append(regime)
        if institution_id:conditions.append("COALESCE(institution_id,'') IN ('',?)");params.append(institution_id)
        query="SELECT formule_id,nom,COALESCE(institution_id,''),regime,rubrique,trimestre_debut,annee_debut,aggregation,termes_json,version,actif FROM config_formules_impact"
        if conditions:query+=" WHERE "+" AND ".join(conditions)
        with self.connect() as con:return con.execute(query+" ORDER BY annee_debut DESC,trimestre_debut DESC,version DESC",params).fetchall()

    def get_impact_formula(self,formula_id: str) -> dict:
        if formula_id=="FORMULE_DEFAUT":return self.default_impact_formula()
        with self.connect() as con:
            row=con.execute("SELECT formule_id,nom,COALESCE(institution_id,''),regime,rubrique,trimestre_debut,annee_debut,aggregation,termes_json,version,actif,cree_le FROM config_formules_impact WHERE formule_id=?",[formula_id]).fetchone()
        if not row:raise ValueError("Formule introuvable.")
        return {"id":row[0],"name":row[1],"institution_id":row[2],"regime":row[3],"rubric":row[4],"quarter":row[5],"year":row[6],"aggregation":row[7],"terms":json.loads(row[8]),"version":row[9],"active":row[10],"created_at":row[11],"system":False}

    def set_impact_formula_active(self,formula_id: str,active: bool) -> None:
        with self.connect() as con:con.execute("UPDATE config_formules_impact SET actif=? WHERE formule_id=?",[active,formula_id])

    def delete_impact_formula(self, formula_id: str) -> None:
        if not formula_id:
            raise ValueError("L’identifiant de la formule est obligatoire.")
        with self.connect() as con:
            con.execute("DELETE FROM config_formules_impact WHERE formule_id=?", [formula_id])

    def resolve_impact_formula(self,institution_id: str,regime: str,quarter: str,year: int,rubric: str) -> dict:
        qnum=int(str(quarter).replace("T",""));rows=self.list_impact_formulas(regime,institution_id)
        candidates=[]
        for row in rows:
            fid,name,iid,reg,rub,qstart,ystart,aggregation,terms_json,version,active=row
            if not active or rub not in {rubric,"*"}:continue
            if (int(ystart),int(str(qstart).replace("T","")))>(int(year),qnum):continue
            specificity=(4 if iid==institution_id else 2 if not iid else 0)+(1 if rub==rubric else 0)
            if specificity:candidates.append((specificity,int(ystart),int(str(qstart).replace("T","")),int(version),row))
        if candidates:
            row=max(candidates,key=lambda x:x[:4])[4]
            return {"id":row[0],"name":row[1],"institution_id":row[2],"regime":row[3],"rubric":row[4],"quarter":row[5],"year":row[6],"aggregation":row[7],"terms":json.loads(row[8]),"version":row[9]}
        return self.default_impact_formula()

    def selectable_impact_formulas(self,institution_id: str,regime: str,quarter: str,year: int) -> list[dict]:
        """List active global formulas that may safely override a whole matching run."""
        qnum=int(str(quarter).replace("T",""));items=[self.default_impact_formula()]
        for row in self.list_impact_formulas(regime,institution_id):
            fid,_name,iid,_reg,rubric,qstart,ystart,_aggregation,_terms,_version,active=row
            if not active or rubric!="*":continue
            if iid and iid!=institution_id:continue
            if (int(ystart),int(str(qstart).replace("T","")))>(int(year),qnum):continue
            items.append(self.get_impact_formula(fid))
        return items

    def selected_impact_formula(self,formula_id: str,institution_id: str,regime: str,
                                quarter: str,year: int) -> dict:
        """Validate a user-selected formula before forcing it on a matching run."""
        allowed={item["id"]:item for item in self.selectable_impact_formulas(
            institution_id,regime,quarter,year)}
        if formula_id not in allowed:
            raise ValueError("La formule choisie n’est pas active ou ne correspond pas au régime, à l’institution et à la période sélectionnés.")
        return allowed[formula_id]

    def default_impact_formula(self) -> dict:
        return {"id":"FORMULE_DEFAUT","name":"Formule SICORPA par défaut","institution_id":"","regime":"Tous les régimes","rubric":"*","quarter":"T1","year":2020,"aggregation":"TOUTES_LIGNES","terms":[dict(term) for term in self.DEFAULT_IMPACT_TERMS],"version":1,"system":True}

    def formula_terms_sql(self,terms: list[dict],aggregation: str,alias: str="p",duplicate_rank: str="1") -> str:
        if aggregation not in self.FORMULA_AGGREGATIONS:raise ValueError("Agrégation inconnue.")
        components={row[0]:row[2] for row in self.list_financial_components()};expressions=[];prefix=f"{alias}." if alias else ""
        for term in terms:
            code=str(term.get("code","")).upper()
            if code not in components:raise ValueError(f"Composante inconnue : {code}")
            coefficient=float(term.get("coefficient",0));column=components.get(code)
            value=f'COALESCE({prefix}"{column}",0)' if column else f"COALESCE(TRY_CAST(json_extract_string({prefix}composantes_supplementaires_json, '$.{code}') AS DECIMAL(38,2)),0)"
            if coefficient:expressions.append(f"({coefficient})*({value})")
        expression=" + ".join(expressions) if expressions else "0"
        if aggregation=="AUCUN_IMPACT":return "0"
        if aggregation=="OCCURRENCES_SUPPLEMENTAIRES":return f"CASE WHEN {duplicate_rank}>1 THEN ({expression}) ELSE 0 END"
        if aggregation=="UNIQUE_AGENT":return f"CASE WHEN {duplicate_rank}=1 THEN ({expression}) ELSE 0 END"
        return expression

    def impact_sql(self,institution_id: str,regime: str,quarter: str,year: int,rubric: str,
                   alias: str="p",duplicate_rank: str="1",formula_id: str="") -> tuple[str,dict]:
        formula=(self.selected_impact_formula(formula_id,institution_id,regime,quarter,year)
                 if formula_id else
                 self.resolve_impact_formula(institution_id,regime,quarter,year,rubric))
        return self.formula_terms_sql(formula["terms"],formula["aggregation"],alias,duplicate_rank),formula

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
