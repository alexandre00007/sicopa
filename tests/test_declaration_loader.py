import tempfile
import unittest
from pathlib import Path

import pandas as pd

from controle_paie.config import AppConfig
from controle_paie.database import Database
from controle_paie.loaders import (IngestionService, describe_declaration_structure,
                                   select_access_driver)


class DeclarationLoaderTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.database=Database(self.root/"test.duckdb");self.database.migrate()
        self.institution=self.database.add_institution("TEST","Institution Test")
        self.service=IngestionService(self.database,AppConfig(database_path=self.root/"test.duckdb"))

    def tearDown(self):
        self.temp.cleanup()

    def _workbook(self,name="declaratif.xlsx"):
        path=self.root/name
        pd.DataFrame({"Matricule":["A1","A2"],"Noms":["Alpha","Beta"],
                      "Service":["Finance","RH"],"MontantDeclare":[100,200],
                      "StatutAgent":["Actif","Actif"]}).to_excel(path,index=False,sheet_name="Agents")
        return path

    def test_structure_recognizes_declarative_specific_fields(self):
        structure=describe_declaration_structure(
            ["Matricule","Noms","Service","MontantDeclare","StatutAgent","Observation"])
        self.assertFalse(structure["issues"])
        self.assertEqual(structure["mapping"]["Service"],"service")
        self.assertEqual(structure["mapping"]["MontantDeclare"],"remuneration_declaree")
        self.assertEqual(structure["mapping"]["StatutAgent"],"statut_agent")
        self.assertEqual(structure["unmapped"],["Observation"])
        statuses={row[0]:row[3] for row in structure["rows"]}
        self.assertEqual(statuses["matricule_source"],"✓ Obligatoire présent")
        self.assertEqual(statuses["nom"],"✓ Obligatoire présent")
        missing_name=describe_declaration_structure(["Matricule","Grade"])
        self.assertEqual(missing_name["missing_matching"],["Nom / noms de l’agent"])
        self.assertIn("Nom / noms de l’agent",missing_name["issues"][0])
        missing_matricule=describe_declaration_structure(["Noms","Province"])
        self.assertEqual(missing_matricule["missing_matching"],["Matricule"])
        invalid=describe_declaration_structure(["Grade","Province"])
        self.assertEqual(invalid["missing_matching"],["Matricule","Nom / noms de l’agent"])

    def test_loader_blocks_missing_or_empty_matching_fields(self):
        missing_name=self.root/"sans_nom.xlsx"
        pd.DataFrame({"Matricule":["A1"]}).to_excel(missing_name,index=False,sheet_name="Agents")
        with self.assertRaisesRegex(ValueError,"Nom / noms de l’agent"):
            self.service.load_excel(str(missing_name),"Agents",1,self.institution,"PNC","T1",2024)

        empty_matricule=self.root/"matricule_vide.xlsx"
        pd.DataFrame({"Matricule":["",None],"Noms":["Alpha","Beta"]}).to_excel(
            empty_matricule,index=False,sheet_name="Agents")
        with self.assertRaisesRegex(ValueError,"sans aucune valeur exploitable : Matricule"):
            self.service.load_excel(str(empty_matricule),"Agents",1,self.institution,"PNC","T1",2024)

    def test_loader_journals_schema_and_unused_import_can_be_deleted(self):
        path=self._workbook();events=[]
        inspected=self.service.inspect_declaration_structure(str(path),"Agents",1,"PNC")
        self.assertFalse(inspected["issues"])
        execution=self.service.load_excel(str(path),"Agents",1,self.institution,"PNC","T1",2024,
            progress=lambda value,text:events.append((value,text)))
        self.assertEqual([value for value,_ in events],[-1,25,-1,55,85,100])
        with self.database.connect() as connection:
            row=connection.execute("""SELECT matricule_normalise,nom,service,remuneration_declaree,
                statut_agent FROM declaratif_standardise WHERE execution_id=? ORDER BY matricule_normalise""",
                [execution]).fetchall()
            schema=dict(connection.execute("SELECT colonne_source,colonne_standard FROM schemas_sources WHERE execution_id=?",
                                           [execution]).fetchall())
        self.assertEqual(row[0],("A1","Alpha","Finance",100,"Actif"))
        self.assertEqual(schema["Service"],"service")
        imports=self.database.list_declaration_imports(self.institution,"PNC","T1",2024)
        self.assertEqual(imports[0][0],execution);self.assertEqual(imports[0][8],2)
        result=self.database.delete_declaration_import(execution)
        self.assertEqual(result["lines"],2)
        self.assertEqual(self.database.list_declaration_imports(self.institution,"PNC","T1",2024),[])
        with self.database.connect() as connection:
            status=connection.execute("SELECT statut FROM journal_executions WHERE execution_id=?",
                                      [execution]).fetchone()[0]
        self.assertEqual(status,"SUPPRIME")

    def test_used_declarative_import_cannot_be_deleted(self):
        path=self._workbook("used.xlsx")
        execution=self.service.load_excel(str(path),"Agents",1,self.institution,"PNC","T1",2024)
        with self.database.connect() as connection:
            declaration_id=connection.execute("SELECT ligne_declaratif_id FROM declaratif_standardise WHERE execution_id=? LIMIT 1",
                                              [execution]).fetchone()[0]
            connection.execute("""INSERT INTO resultats_rapprochement
                (rapprochement_id,execution_id,ligne_declaratif_id) VALUES ('r1','matching-1',?)""",
                [declaration_id])
        with self.assertRaisesRegex(ValueError,"Suppression bloquée"):
            self.database.delete_declaration_import(execution)
        replacement=self._workbook("replacement.xlsx")
        with self.assertRaisesRegex(ValueError,"Remplacement bloqué"):
            self.service.load_excel(str(replacement),"Agents",1,self.institution,"PNC","T1",2024,
                                    mode="replace_period")
        with self.database.connect() as connection:
            remaining=connection.execute("SELECT COUNT(*) FROM declaratif_standardise WHERE execution_id=?",
                                         [execution]).fetchone()[0]
        self.assertEqual(remaining,2)

    def test_access_driver_is_selected_or_im002_is_prevented(self):
        installed=["SQL Server","Microsoft Access Driver (*.mdb, *.accdb)"]
        self.assertEqual(select_access_driver(installed,"Pilote configuré absent",".accdb"),installed[1])
        with self.assertRaisesRegex(RuntimeError,"IM002 évitée"):
            select_access_driver(["SQL Server"],"Microsoft Access Driver (*.mdb, *.accdb)",".accdb")


if __name__=="__main__":
    unittest.main()
