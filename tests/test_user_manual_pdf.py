from controle_paie.manual_content import MANUAL_SECTIONS
from controle_paie.manual_pdf import generate_user_manual_pdf


def test_user_manual_pdf_is_generated(tmp_path):
    target = tmp_path / "Manuel_utilisateur_SICORPA.pdf"
    result = generate_user_manual_pdf(target)

    assert result == target
    assert target.exists()
    assert target.stat().st_size > 3000
    assert target.read_bytes().startswith(b"%PDF")
    headings = [heading for heading, _paragraphs in MANUAL_SECTIONS]
    assert any("Fusion" in heading for heading in headings)
    assert any("annexes" in heading.lower() for heading in headings)
