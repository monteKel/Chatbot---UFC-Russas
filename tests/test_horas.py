import asyncio
import json

import pytest

import db
import horas
import llm
from conftest import ROOT
from fakes import completion, provider, tool_call

CC = "Ciência da Computação"
EC = "Engenharia Civil"


def run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize("text,expected", [
    ("fiz um curso de inglês de 40h", True),
    ("Participei do congresso nacional por 3 dias", True),
    ("concluí a monitoria de cálculo", True),
    ("fui monitor de programação", True),
    ("tenho um certificado de palestra", True),
    ("quantas horas complementares eu preciso?", False),
    ("como funciona o TCC?", False),
])
def test_declares_activity(text, expected):
    assert horas.declares_activity(text) is expected


@pytest.mark.parametrize("value,expected", [
    (20, 20.0), (20.5, 20.5), (0, 0.0), ("20", 20.0), ("20,5", 20.5), (" 12 h ", 12.0),
    (-3, None), (True, None), (None, None), ("muitas", None), ([], None),
])
def test_number(value, expected):
    assert horas._number(value) == expected


@pytest.mark.parametrize("group,expected", [
    (4, 4), ("4", 4), ("IV", 4), ("iv", 4), (4.0, 4), ("Grupo VII", 7), (8, None), ("X", None), (None, None),
])
def test_parse_group_formats(group, expected):
    activity = horas._parse({"group": group, "activity_name": "Curso", "credited_hours": 8, "explanation": "x"},
                            horas.COURSE_RULES[CC]["groups"])
    assert (activity.group if activity else None) == expected


def test_parse_requires_name_and_normalizes_item():
    groups = horas.COURSE_RULES[CC]["groups"]
    assert horas._parse({"group": 4, "activity_name": "  ", "credited_hours": 8}, groups) is None
    activity = horas._parse({"group": 4, "item": " C) ", "activity_name": "Curso", "credited_hours": "8",
                             "certificate_hours": "8"}, groups)
    assert (activity.item, activity.credited_hours, activity.certificate_hours) == ("c", 8.0, 8.0)


def test_redact_removes_ids_but_keeps_hours():
    text = "CPF 123.456.789-00, CPF 12345678900, matrícula 541234567, carga horária 40 horas em 12/05/2025"
    redacted = horas._redact(text)
    assert "123.456.789-00" not in redacted and "12345678900" not in redacted and "541234567" not in redacted
    assert "40 horas" in redacted and "12/05/2025" in redacted


@pytest.mark.parametrize("value,expected", [(40.0, "40"), (0.5, "0,5"), (102.00000001, "102"), (12.25, "12,25")])
def test_fmt(value, expected):
    assert horas.fmt(value) == expected


def _add(chat_id, group, hours, course=CC):
    db.add_complementary_hours(chat_id, group, None, f"Atividade G{group}", hours, hours, "texto", None, "x",
                               course=course)


def test_summary_applies_group_caps_and_total():
    db.set_course(1, EC)
    _add(1, 1, 48, EC)   # cap 12
    _add(1, 7, 24, EC)
    text = horas.summary(1, EC)
    assert "Grupo I - Iniciação à pesquisa, ensino ou extensão: 12/12h (registradas 48h" in text
    assert "Total: 36/60h (faltam 24h)" in text


def test_summary_concluded_and_none_without_hours():
    assert horas.summary(2, EC) is None
    for group in range(1, 8):
        _add(2, group, 50, EC)
    assert "Total: 60/60h (concluído)" in horas.summary(2, EC)
    assert horas.summary(2, "Engenharia Mecânica") is None
    assert horas.summary(2, None) is None


def test_suggestions_lists_room_per_group_and_stops_when_done():
    _add(3, 7, 24, EC)
    text = horas.suggestions(3, EC)
    assert "Grupo VII - Revisão do Ensino Médio (cabem mais 24h)" in text
    assert "Grupo I" in text
    for group in range(1, 8):
        _add(3, group, 50, EC)
    assert horas.suggestions(3, EC) is None


def test_hours_from_other_course_do_not_count():
    _add(4, 7, 40, CC)   # registered while the student was marked as CC
    _add(4, 4, 8, EC)
    assert db.hours_by_group(4, EC) == {4: 8}
    assert "Total: 8/60h" in horas.summary(4, EC)


def test_pending_belongs_to_chat_and_expires(monkeypatch):
    activity = horas.Activity(4, "c", "Curso", 8, 8, "x", "")
    token = horas.add_pending(10, [activity], "pdf", "F1", CC)
    assert horas.pop_pending(token, 11) is None          # other student
    assert horas.pop_pending(token, 10).activities == [activity]
    assert horas.pop_pending(token, 10) is None          # already used
    token = horas.add_pending(10, [activity], "pdf", "F1", CC)
    monkeypatch.setattr(horas.time, "monotonic", lambda: 10 ** 9)
    assert horas.pop_pending(token, 10) is None


def test_save_stores_course_source_and_file():
    activity = horas.Activity(4, "c", "Minicurso Docker", 8, 8, "1h por hora", "")
    horas.save(horas.Pending(20, [activity], "pdf", "FILE9", CC))
    row = db._conn.execute(
        "SELECT activity_group, activity_item, activity_name, certificate_hours, hours, source, file_id, course "
        "FROM complementary_hours WHERE chat_id = 20").fetchone()
    assert row == (4, "c", "Minicurso Docker", 8.0, 8.0, "pdf", "FILE9", CC)


def test_describe_hides_item_letter_and_explains_missing_info():
    full = horas.describe(horas.Activity(7, "b", "Curso de inglês", 40, 20, "1h a cada 2h", ""), CC)
    assert "Grupo VII (Outras atividades)" in full and "40h → contam 20h" in full and "item" not in full
    missing = horas.describe(horas.Activity(1, "c", "Monitoria", None, None, "", "número de semanas"), CC)
    assert "Faltou: número de semanas" in missing


def test_extract_parses_calls_and_excludes_gemini():
    arguments = json.dumps({"activities": [
        {"group": "IV", "item": "c", "activity_name": "Minicurso Docker", "certificate_hours": 8,
         "credited_hours": 8, "explanation": "1h por hora"},
        {"group": 9, "activity_name": "inválida", "credited_hours": 1, "explanation": "x"},
    ]})
    llm._providers = [provider("gemini", [completion("não devia ser chamado")]),
                      provider("groq", [completion(tool_calls=[tool_call("register_activities", arguments)])])]
    activities = run(horas.extract("Certificado CPF 123.456.789-00 Docker 8 horas", CC))
    assert [(a.group, a.credited_hours) for a in activities] == [(4, 8.0)]
    assert llm._providers[0]["client"].calls == []
    sent = llm._providers[1]["client"].calls[0]["messages"][1]["content"]
    assert "123.456.789-00" not in sent


def test_extract_returns_empty_when_no_activity_and_none_on_failure():
    llm._providers = [provider("groq", [completion("nenhuma atividade")])]
    assert run(horas.extract("fiz a prova de cálculo", CC)) == []
    llm._providers = []
    assert run(horas.extract("fiz um curso de 8h", CC)) is None


def test_extractions_run_one_at_a_time():
    active, peak = 0, 0

    async def slow_call_tool(*args, **kwargs):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return [], "groq"

    async def main():
        original = llm.call_tool
        llm.call_tool = slow_call_tool
        try:
            await asyncio.gather(*(horas.extract("fiz um curso", CC) for _ in range(5)))
        finally:
            llm.call_tool = original

    run(main())
    assert peak == 1


def test_read_pdf_text_and_scanned_fallback(monkeypatch):
    pdf = (ROOT / "Documentos" / "Eng. Civil" / "ec_tcc_diretrizes-avaliacao-banca.pdf").read_bytes()
    text = horas.read_pdf(pdf)
    assert horas.is_readable(text)

    class FakePage:
        images = [type("I", (), {"data": b"img"})()]

        def extract_text(self):
            return ""

    monkeypatch.setattr(horas, "PdfReader", lambda _: type("R", (), {"pages": [FakePage()]})())
    monkeypatch.setattr(horas, "_ocr_image", lambda data: "texto lido por OCR com mais de quarenta caracteres aqui")
    assert "OCR" in horas.read_pdf(b"%PDF")


def test_is_readable():
    assert not horas.is_readable("   \n  abc ")
    assert horas.is_readable("Certificamos que Fulano participou do minicurso de Docker")
