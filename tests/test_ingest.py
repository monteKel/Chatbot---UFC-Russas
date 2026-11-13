import re

import pytest
from pypdf import PdfReader

import rag_ingest
from conftest import ROOT

DOCS = ROOT / "Documentos"


@pytest.mark.parametrize("raw,expected", [
    ("Objetivos do est´ agio", "Objetivos do estágio"),
    ("1. Introdu¸ c˜ ao", "1. Introdução"),
    ("N ´ ıvel 2 de Maturidade", "Nível 2 de Maturidade"),
    ("Frequˆ encia: ( ) N˜ ao falta", "Frequência: ( ) Não falta"),
    ("Relat´ orio de Est´ agio", "Relatório de Estágio"),
    ("carga hor´ aria m ´ ınima", "carga horária mínima"),
    ("Sum´ ario 1. Introdu¸ c˜ ao . . . . . . . . . . . . . 1 2. Est´ agio . . . . . . 4", "Sumário 1. Introdução 1 2. Estágio 4"),
    ("Art. 5º. Itens a), b) e c)... fim.", "Art. 5º. Itens a), b) e c)... fim."),
])
def test_clean_text(raw, expected):
    assert rag_ingest.clean_text(raw) == expected


def _raw(path):
    return "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)


def test_clean_text_fixes_the_es_internship_manual():
    text = rag_ingest.clean_text(_raw(DOCS / "Eng. Software" / "es_estagio_manual-normatizacao_grade-2025_v2025.pdf"))
    assert not re.search(r"[´˜ˆ¨¸] ?[A-Za-zı]", text)
    assert not re.search(r"(?:\. ){8,}", text)
    assert "estágio" in text and "Introdução" in text


@pytest.mark.parametrize("path", [
    "Ciencia da Computacao/cc_atividades-complementares_regulamento_2019.pdf",
    "Eng. Civil/ec_atividades-complementares_manual_2023.1.pdf",
])
def test_clean_text_leaves_clean_documents_unchanged(path):
    raw = _raw(DOCS / path)
    assert rag_ingest.clean_text(raw) == re.sub(r"\s+", " ", raw).strip()
