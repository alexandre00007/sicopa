import pytest

from controle_paie.sql_console import SqlConsoleService
from controle_paie.sql_templates import SqlTemplateLibrary


def test_all_sql_templates_are_non_empty_and_read_only():
    assert len(SqlTemplateLibrary.names()) >= 40
    for name in SqlTemplateLibrary.names():
        sql = SqlTemplateLibrary.render(name, "raw_paie_a", "raw_paie_b")
        assert sql.strip(), name
        validated = SqlConsoleService.validate_read_only_query(sql)
        assert validated, name


def test_join_templates_use_selected_a_and_b_tables():
    sql = SqlTemplateLibrary.render("JOIN — LEFT JOIN", "raw_cnss", "raw_carc")
    assert '"raw_cnss" a' in sql
    assert '"raw_carc" b' in sql
    assert "LEFT JOIN" in sql


def test_fictif_template_is_available_and_read_only():
    name = "Contrôle paie — Fictifs / identités suspectes"
    assert name in SqlTemplateLibrary.names()
    sql = SqlTemplateLibrary.render(name, "raw_test")
    assert "FICTIF" in sql.upper()
    assert 'FROM "raw_test"' in sql
    SqlConsoleService.validate_read_only_query(sql)


def test_template_requires_main_table():
    with pytest.raises(ValueError, match="table RAW principale"):
        SqlTemplateLibrary.render("Sélection — Toutes les colonnes", "")


def test_unknown_template_is_rejected():
    with pytest.raises(ValueError, match="inconnu"):
        SqlTemplateLibrary.render("MODELE_INCONNU", "raw_test")
