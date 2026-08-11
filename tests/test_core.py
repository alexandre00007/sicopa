import tempfile
import unittest
from pathlib import Path

import pandas as pd

from controle_paie.database import Database
from controle_paie.config import AppConfig, RegimeConfig
from controle_paie.matching import MatchingService
from controle_paie.standardization import normalize_identifier, standardize_declaration, standardize_payroll
from controle_paie.ui import validate_scope_values


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "test.duckdb")
        self.db.migrate()
        self.institution = self.db.add_institution("TEST", "Institution Test")

    def tearDown(self):
        self.temp.cleanup()

    def metadata(self):
        return dict(execution_id="e1", institution_id=self.institution, regime="PNC",
                    trimestre="T1", annee=2024, table_source="Tab_PNC_T1_2024",
                    fichier_source="declaratif.xlsx", feuille_source="Agents")

    def test_normalization_and_aliases(self):
        self.assertEqual(normalize_identifier(" AB-12 / ç "), "AB12C")
        frame = pd.DataFrame({"NumMatricule": ["A-1"], "Noms": ["Jean Test"],
                              "TraitementBase": [100], "Primes": [20]})
        result = standardize_payroll(frame, self.metadata())
        self.assertEqual(result.loc[0, "matricule_normalise"], "A1")
        self.assertEqual(result.loc[0, "remuneration_brute_calculee"], 120)

    def test_scope_validation_lists_missing_fields(self):
        with self.assertRaisesRegex(ValueError, "institution, trimestre"):
            validate_scope_values("", "PNC", "", "2024")
        self.assertEqual(validate_scope_values("inst-1", "PNC", "T1", "2024"),
                         ("inst-1", "PNC", "T1", 2024))

    def test_dynamic_regime_configuration(self):
        self.db.upsert_regime("SANTE", "Régime de la santé", r"^Tab_Sante_T[1-4]_\d{4}$", "raw_sante")
        rows = self.db.list_regimes()
        self.assertEqual(rows[0][0], "SANTE")
        config = AppConfig(regimes={row[0]: RegimeConfig(row[0], row[2], row[3]) for row in rows})
        self.assertEqual(config.detect_regime("Tab_Sante_T2_2025"), "SANTE")
        self.db.set_regime_active("SANTE", False)
        self.assertEqual(self.db.list_regimes(), [])

    def test_one_classification_per_payroll_row(self):
        pay = standardize_payroll(pd.DataFrame({
            "Matricule": ["A", "B", "B", "C"], "NomPostnom": ["Alpha", "Beta", "Beta", "Gamma"],
            "Base": [100, 200, 200, 300]}), self.metadata())
        declaration = standardize_declaration(
            pd.DataFrame({"matricule": ["A", "B"], "noms": ["Alpha", "Beta"]}), self.metadata())
        with self.db.connect() as connection:
            connection.register("pay", pay)
            connection.execute("INSERT INTO paie_standardisee BY NAME SELECT * FROM pay")
            connection.register("declaration", declaration)
            connection.execute("INSERT INTO declaratif_standardise BY NAME SELECT * FROM declaration")
        execution = MatchingService(self.db).run(self.institution, "PNC", "T1", 2024)
        with self.db.connect() as connection:
            rows = dict(connection.execute(
                "SELECT statut_rapprochement, COUNT(*) FROM resultats_rapprochement WHERE execution_id=? GROUP BY 1",
                [execution]).fetchall())
            total = connection.execute(
                "SELECT COUNT(*) FROM resultats_rapprochement WHERE execution_id=? AND ligne_paie_id IS NOT NULL",
                [execution]).fetchone()[0]
        self.assertEqual(total, 4)
        self.assertEqual(rows["DOUBLON_MATRICULE"], 1)
        self.assertEqual(rows["PAYE_NON_DECLARE"], 1)

    def test_nu_variants_are_never_matricule_duplicates(self):
        pay = standardize_payroll(pd.DataFrame({
            "Matricule": ["NU", "N.U", "nu", "nU"],
            "NomPostnom": ["Alpha", "Beta", "Gamma", "Delta"],
            "Base": [100, 100, 100, 100]}), self.metadata())
        with self.db.connect() as connection:
            connection.register("pay_nu", pay)
            connection.execute("INSERT INTO paie_standardisee BY NAME SELECT * FROM pay_nu")
        execution = MatchingService(self.db).run(self.institution, "PNC", "T1", 2024)
        with self.db.connect() as connection:
            statuses = dict(connection.execute(
                "SELECT statut_rapprochement,COUNT(*) FROM resultats_rapprochement WHERE execution_id=? AND ligne_paie_id IS NOT NULL GROUP BY 1",
                [execution]).fetchall())
        self.assertNotIn("DOUBLON_MATRICULE", statuses)
        self.assertEqual(statuses["MATRICULE_MANQUANT"], 4)

    def test_listing_filters_are_applied_before_matching(self):
        pay = standardize_payroll(pd.DataFrame({
            "Matricule": ["A", "B"], "NomPostnom": ["Alpha", "Beta"],
            "Section": ["CABINET", "DIRECTION"], "Base": [100, 200]}), self.metadata())
        with self.db.connect() as connection:
            connection.register("pay_filter", pay)
            connection.execute("INSERT INTO paie_standardisee BY NAME SELECT * FROM pay_filter")
        self.db.add_treatment_filter(self.institution,"PNC","section","égal à","CABINET")
        execution=MatchingService(self.db).run(self.institution,"PNC","T1",2024)
        with self.db.connect() as connection:
            rows=connection.execute("SELECT COUNT(*) FROM resultats_rapprochement WHERE execution_id=? AND ligne_paie_id IS NOT NULL",[execution]).fetchone()[0]
        self.assertEqual(rows,1)


if __name__ == "__main__":
    unittest.main()
