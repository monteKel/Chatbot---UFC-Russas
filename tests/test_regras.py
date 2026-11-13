import re

import pytest

import fontes
from regras_horas import COURSE_RULES, ROMAN

EXPECTED_TOTALS = {
    "Ciência da Computação": 192,
    "Engenharia de Software": 288,
    "Engenharia Civil": 60,
    "Engenharia de Produção": 60,
}
CONTACTS = {
    "Ciência da Computação": "/coordcc",
    "Engenharia de Software": "/coordes",
    "Engenharia Civil": "/coordec",
    "Engenharia de Produção": "/coordep",
}


@pytest.mark.parametrize("course", COURSE_RULES)
def test_course_structure(course):
    rules = COURSE_RULES[course]
    assert rules["total"] == EXPECTED_TOTALS[course]
    assert set(rules["groups"]) == set(range(1, 8))
    assert set(rules["hints"]) == set(range(1, 8))
    assert all(rules["hints"].values())
    assert CONTACTS[course] in rules["submission"]
    assert len(rules["submission"]) < 4000


@pytest.mark.parametrize("course", COURSE_RULES)
def test_group_caps_match_regulation_text(course):
    rules = COURSE_RULES[course]
    for group, (_, cap) in rules["groups"].items():
        header = re.search(rf"^{ROMAN[group]}\. .*?\(até (\d+) horas", rules["rules"], re.M)
        assert header, f"{course}: cabeçalho do grupo {ROMAN[group]} não encontrado"
        assert int(header.group(1)) == cap, f"{course} grupo {ROMAN[group]}: teto {cap} != texto {header.group(1)}"


@pytest.mark.parametrize("course", COURSE_RULES)
def test_group_caps_can_reach_total(course):
    rules = COURSE_RULES[course]
    assert sum(cap for _, cap in rules["groups"].values()) >= rules["total"]


def test_every_ingested_document_exists_and_has_a_source_title():
    import rag_ingest
    from conftest import ROOT

    for course, files in rag_ingest.COURSE_FILES.items():
        for filename in files:
            assert filename in fontes.DOC_TITLES, f"sem título de fonte: {filename}"
            assert (ROOT / "Documentos" / rag_ingest.COURSE_FOLDERS[course] / filename).exists(), filename


def test_doc_title_fallbacks():
    assert fontes.doc_title(None) == "documento oficial"
    assert fontes.doc_title("desconhecido.pdf") == "desconhecido.pdf"
