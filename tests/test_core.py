import tempfile
import unittest
from pathlib import Path

import pandas as pd

from controle_paie.database import Database
from controle_paie.config import AppConfig, RegimeConfig
from controle_paie.matching import MatchingService
from controle_paie.letters import generate_interpretation_letter
from controle_paie.standardization import normalize_identifier, standardize_declaration, standardize_payroll
from controle_paie.ui import fitted_window_geometry, validate_scope_values


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

    def test_child_window_geometry_is_always_visible(self):
        width,height,x,y=fitted_window_geometry(1024,600,1400,900,512,300)
        self.assertLessEqual(x+width,1000)
        self.assertLessEqual(y+height,528)
        self.assertGreaterEqual(x,24)
        self.assertGreaterEqual(y,48)
        self.assertEqual((width,height),(976,480))

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

    def test_interpretation_letter_is_created(self):
        from docx import Document
        target=Path(self.temp.name)/"lettre_interpretation.docx"
        summaries=[
            {"label":"Données du listing de paie filtré","count":10,"concerned":9,"impact":1000,"group":"annexes_listing"},
            {"label":"Données déclaratives","count":8,"concerned":8,"impact":0,"group":"annexes_declaratif"},
            {"label":"Doublons par matricule hors NU","count":2,"concerned":1,"impact":200,"group":"annexes_listing"},
        ]
        generate_interpretation_letter(target,"Institution Test","PNC","T1",2024,summaries,[])
        self.assertTrue(target.exists())
        text="\n".join(paragraph.text for paragraph in Document(target).paragraphs)
        self.assertIn("Institution Test",text)
        self.assertIn("Interprétation générale",text)

    def test_versioned_impact_formula_and_extra_component(self):
        self.db.add_financial_component("PRIME_TECHNIQUE","Prime technique")
        formula_id=self.db.save_impact_formula("Net technique",self.institution,"PNC","PAYE_NON_DECLARE","T1",2024,"TOUTES_LIGNES",[
            {"code":"REMUNERATION_BASE","coefficient":1},{"code":"PRIME_TECHNIQUE","coefficient":1},{"code":"RETENUES","coefficient":-1}])
        pay=standardize_payroll(pd.DataFrame({"Matricule":["X"],"NomPostnom":["Agent X"],"Base":[100],"Retenue":[10],"PrimeTech":[25]}),self.metadata(),{"PrimeTech":"composante_PRIME_TECHNIQUE"})
        with self.db.connect() as connection:
            connection.register("pay_formula",pay);connection.execute("INSERT INTO paie_standardisee BY NAME SELECT * FROM pay_formula")
        execution=MatchingService(self.db).run(self.institution,"PNC","T1",2024)
        with self.db.connect() as connection:
            row=connection.execute("SELECT impact_potentiel,formule_impact_id FROM resultats_rapprochement WHERE execution_id=? AND ligne_paie_id IS NOT NULL",[execution]).fetchone()
        self.assertEqual(float(row[0]),115.0);self.assertEqual(row[1],formula_id)

    def test_formula_occurrences_supplementaires(self):
        self.db.save_impact_formula("Doublons supplémentaires",self.institution,"PNC","DOUBLON_MATRICULE","T1",2024,"OCCURRENCES_SUPPLEMENTAIRES",[{"code":"REMUNERATION_BASE","coefficient":1}])
        expression,formula=self.db.impact_sql(self.institution,"PNC","T1",2024,"DOUBLON_MATRICULE","p","rn")
        self.assertIn("CASE WHEN rn>1",expression);self.assertEqual(formula["aggregation"],"OCCURRENCES_SUPPLEMENTAIRES")

    def test_default_formula_is_visible_and_used_as_fallback(self):
        formula=self.db.default_impact_formula()
        self.assertEqual(formula["id"],"FORMULE_DEFAUT")
        self.assertEqual(formula["aggregation"],"TOUTES_LIGNES")
        self.assertEqual([term["code"] for term in formula["terms"]],["REMUNERATION_BASE","TRANSPORT","PRIME","LOGEMENT","PENSION_RENTE","AUTRES_REMUNERATIONS"])
        resolved=self.db.resolve_impact_formula(self.institution,"PNC","T1",2024,"PAYE_NON_DECLARE")
        self.assertEqual(resolved["id"],"FORMULE_DEFAUT")

    def test_formula_details_and_non_destructive_modification(self):
        first=self.db.save_impact_formula("Impact initial",self.institution,"PNC","PAYE_NON_DECLARE","T1",2024,"TOUTES_LIGNES",[{"code":"REMUNERATION_BASE","coefficient":1}])
        detail=self.db.get_impact_formula(first)
        self.assertEqual(detail["version"],1);self.assertEqual(detail["terms"][0]["code"],"REMUNERATION_BASE")
        second=self.db.save_impact_formula("Impact modifié",self.institution,"PNC","PAYE_NON_DECLARE","T1",2024,"TOUTES_LIGNES",[{"code":"REMUNERATION_BASE","coefficient":1},{"code":"RETENUES","coefficient":-1}])
        self.assertEqual(self.db.get_impact_formula(second)["version"],2)
        self.assertEqual(self.db.get_impact_formula(first)["name"],"Impact initial")
        self.assertEqual(self.db.resolve_impact_formula(self.institution,"PNC","T1",2024,"PAYE_NON_DECLARE")["id"],second)


if __name__ == "__main__":
    unittest.main()
