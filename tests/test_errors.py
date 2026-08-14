import errno
import unittest

from controle_paie.errors import explain_error


class ErrorExplanationTests(unittest.TestCase):
    def test_corrupt_office_file_is_explained(self):
        report=explain_error(RuntimeError('Failed to open zip for reading'),operation="Rapport final")
        self.assertEqual(report.category,"Fichier Excel ou Word endommagé")
        self.assertIn("Enregistrer sous",report.actions[0])
        self.assertTrue(report.reference.startswith("SIC-"))
        self.assertEqual(report.operation,"Rapport final")

    def test_access_driver_error_is_explained(self):
        report=explain_error(RuntimeError("Can't open Microsoft Access database"))
        self.assertEqual(report.category,"Lecture Microsoft Access impossible")
        self.assertTrue(any("64 bits" in action for action in report.actions))

    def test_im002_is_explained_as_an_odbc_architecture_problem(self):
        report=explain_error(RuntimeError(
            "[IM002] [Microsoft][Gestionnaire de pilotes ODBC] Source de données introuvable "
            "et nom de pilote non spécifié (SQLDriverConnect)"))
        self.assertEqual(report.category,"Pilote ODBC Microsoft Access indisponible")
        self.assertTrue(any("architecture" in action for action in report.actions))

    def test_memory_and_disk_errors_are_distinct(self):
        memory=explain_error(MemoryError("out of memory"))
        disk=explain_error(OSError(errno.ENOSPC,"No space left on device"))
        self.assertEqual(memory.category,"Mémoire insuffisante")
        self.assertEqual(disk.category,"Espace disque insuffisant")

    def test_illegal_excel_character_has_a_specific_diagnosis(self):
        report=explain_error(RuntimeError(
            "KASONGO KASONGO L\\x1eYLY cannot be used in worksheets."))
        self.assertEqual(report.category,"Caractère invisible incompatible avec Excel")
        self.assertIn("caractère de contrôle invisible",report.summary)

    def test_traceback_is_kept_for_support(self):
        report=explain_error(ValueError("Périmètre incomplet"),"Traceback de test","Import")
        self.assertEqual(report.category,"Données ou sélection invalides")
        self.assertIn("Traceback de test",report.technical)
        self.assertIn("Périmètre incomplet",report.user_text)


if __name__=="__main__":
    unittest.main()
