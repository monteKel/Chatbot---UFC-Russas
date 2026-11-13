import asyncio
import json
import re
from datetime import datetime
from types import SimpleNamespace

import pytest
from telegram import Chat, InlineKeyboardMarkup, Message, MessageEntity, Update, User
from telegram.error import BadRequest

import bot
import db
import horas
import llm
from fakes import (
    CONTEXT,
    FakeAttachment,
    FakeQuery,
    Recorder,
    completion,
    make_callback_update,
    make_update,
    provider,
    tool_call,
)

CC = "Ciência da Computação"
EC = "Engenharia Civil"


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def chunks(monkeypatch):
    """Replaces the embedding/Chroma lookup and records which course filter was used."""
    seen = []

    async def fake_retrieve(question, course_prefix, n_results=10):
        seen.append(course_prefix)
        return [("Trecho oficial sobre horas.", "Regulamento de Teste (2020)")]

    monkeypatch.setattr(bot, "retrieve_context", fake_retrieve)
    return seen


def extraction_call(*activities):
    return completion(tool_calls=[tool_call("register_activities", json.dumps({"activities": list(activities)}))])


ENGLISH_COURSE = {"group": 7, "item": "b", "activity_name": "Curso de inglês", "certificate_hours": 40,
                  "credited_hours": 20, "explanation": "1h a cada 2h"}


# ---------- formatting helpers ----------

def test_split_message_respects_limit_and_keeps_content():
    text = "\n".join(f"linha {i} " + "x" * 50 for i in range(300))
    parts = bot.split_message(text, limit=1000)
    assert all(len(p) <= 1000 for p in parts)
    assert "".join(parts).replace("\n", "") == text.replace("\n", "")
    no_newlines = "y" * 2500
    assert [len(p) for p in bot.split_message(no_newlines, limit=1000)] == [1000, 1000, 500]
    assert bot.split_message("") == []


def test_to_telegram_html():
    assert bot.to_telegram_html("**Grupo I** & x < y") == "<b>Grupo I</b> &amp; x &lt; y"
    assert bot.to_telegram_html("### Título\nuse `/horas`") == "<b>Título</b>\nuse <code>/horas</code>"
    assert bot.to_telegram_html("sem **fechar") == "sem fechar"


TITLES = ["Regulamento de TCC de Engenharia de Software (2024.1)", "Projeto Pedagógico de Engenharia de Software (2017)"]


@pytest.mark.parametrize("text,titles,expected", [
    ("Tudo bem! Como posso ajudar?\n\nFonte:     ", TITLES, "Tudo bem! Como posso ajudar?"),
    ("Tudo bem!\n\n**Fonte:**", TITLES, "Tudo bem!"),
    ("Use /horas.\n\nFonte: (nenhum trecho específico usado)", TITLES, "Use /horas."),
    ("Texto.\n\nFonte: Manual Inventado de Coisas (2030)", TITLES, "Texto."),
    ("Texto.\n\nFonte: Regulamento de TCC de Engenharia de Software (2024.1)", TITLES,
     "Texto.\n\nFonte: Regulamento de TCC de Engenharia de Software (2024.1)"),
    ("Texto.\n\n**Fonte:** regulamento de tcc de engenharia de software", TITLES,
     "Texto.\n\n**Fonte:** regulamento de tcc de engenharia de software"),
    ("Texto.\n\nFonte: Regulamento de TCC de Engenharia de Software (2024.1)", [], "Texto."),
    ("Texto sem fonte.", TITLES, "Texto sem fonte."),
    ("A fonte: do problema é outra coisa no meio.\nFim.", TITLES, "A fonte: do problema é outra coisa no meio.\nFim."),
])
def test_clean_source_line(text, titles, expected):
    assert bot.clean_source_line(text, titles) == expected


def test_inline_citation_brackets_are_removed():
    text = ("São **288 horas**.【Fonte: Projeto Pedagógico de Engenharia de Software (2017)】\n\n"
            "Fonte: Projeto Pedagógico de Engenharia de Software (2017)【Fonte: Projeto Pedagógico de Engenharia de Software (2017)】")
    assert bot.clean_source_line(text, TITLES) == (
        "São **288 horas**.\n\nFonte: Projeto Pedagógico de Engenharia de Software (2017)")


def test_prompt_budget_drops_old_history_then_weak_chunks():
    for i in range(3):
        db.save_message(1, "user", f"pergunta {i} " + "q" * 1100)
        db.save_message(1, "model", f"resposta {i} " + "r" * 1100)
    chunks = [(f"trecho {i} " + "c" * 1500, f"Doc {i}") for i in range(10)]
    messages = bot.build_messages(1, "pergunta nova", chunks, CC)
    total = sum(len(m["content"]) for m in messages)
    assert total <= bot.MAX_PROMPT_CHARS + 500
    context = messages[-1]["content"]
    assert "trecho 0 " in context                                  # most relevant chunk kept
    assert context.count("[Fonte:") >= bot.MIN_CONTEXT_CHUNKS
    assert len(messages) - 2 >= bot.MIN_HISTORY_MESSAGES            # recent history kept


def test_reply_without_used_documents_has_no_empty_source(chunks):
    llm._providers = [provider("groq", [completion("Tudo bem! Como posso ajudar?\n\nFonte:   ")])]
    recorder = Recorder()
    run(bot.process_text(make_update(recorder), CONTEXT, "oi tudo bem"))
    assert recorder.visible == ["Tudo bem! Como posso ajudar?"]


@pytest.mark.parametrize("handler", [bot.start, bot.help_command, bot.faq, bot.coordcc, bot.coordes, bot.coordep,
                                     bot.coordec, bot.coordem])
def test_markdown_texts_are_valid(handler):
    recorder = Recorder()
    run(handler(make_update(recorder), CONTEXT))
    text = recorder.sent[0]
    assert len(text) < 4096
    assert text.count("*") % 2 == 0, "asterisco sem par quebra o Markdown do Telegram"
    assert "_" not in text and "[" not in text and "`" not in text


# ---------- prompt building ----------

def test_build_messages_includes_course_hours_and_sources():
    db.set_course(1, EC)
    db.add_complementary_hours(1, 7, None, "Revisão", 24, 24, "texto", None, "x", course=EC)
    messages = bot.build_messages(1, "quantas horas me faltam?", [("trecho", "Manual X")], EC)
    system = messages[0]["content"]
    assert "Curso registrado do aluno: Engenharia Civil" in system
    assert "Total: 24/60h" in system
    assert "Onde ainda dá para ganhar horas" in system
    assert "[Fonte: Manual X]\ntrecho" in messages[-1]["content"]


def test_build_messages_without_hours_question_skips_suggestions():
    db.add_complementary_hours(1, 7, None, "Revisão", 24, 24, "texto", None, "x", course=EC)
    system = bot.build_messages(1, "como funciona o TCC?", [], EC)[0]["content"]
    assert "Onde ainda dá para ganhar horas" not in system


def test_build_messages_context_placeholders():
    assert "Não foi possível consultar" in bot.build_messages(1, "oi", None, None)[-1]["content"]
    assert "Nenhum trecho relevante" in bot.build_messages(1, "oi", [], None)[-1]["content"]


def test_build_messages_maps_roles_and_bounds_history_size():
    for i in range(6):
        db.save_message(1, "user", f"pergunta {i}")
        db.save_message(1, "model", f"resposta {i} " + "z" * 5000)
    messages = bot.build_messages(1, "nova pergunta", [], CC)
    history = messages[1:-1]
    assert {m["role"] for m in history} <= {"user", "assistant"}
    assert history[-1]["content"].startswith("resposta 5")          # most recent kept
    assert sum(len(m["content"]) for m in history) <= bot.MAX_HISTORY_CHARS
    assert all(len(m["content"]) <= bot.MAX_HISTORY_MESSAGE_CHARS + 10 for m in history)


# ---------- text messages ----------

def test_normal_answer_replaces_typing_message(chunks):
    llm._providers = [provider("groq", [completion("A resposta é **192h**.")])]
    recorder = Recorder()
    run(bot.process_text(make_update(recorder), CONTEXT, "quantas horas preciso?"))
    kinds = [e[0] for e in recorder.events]
    assert kinds == ["send", "delete", "send"]
    assert recorder.events[0][1] == "Digitando..." and recorder.events[1][1] == "Digitando..."
    assert recorder.events[2][1] == "A resposta é <b>192h</b>." and recorder.events[2][4] == "HTML"
    assert db.get_history(recorder.chat_id) == [("user", "quantas horas preciso?"), ("model", "A resposta é **192h**.")]


def test_feedback_is_saved_without_calling_llm():
    recorder = Recorder()
    bot.awaiting_feedback.add(recorder.chat_id)
    run(bot.process_text(make_update(recorder), CONTEXT, "adorei"))
    assert recorder.sent == ["Obrigado pelo feedback!"]
    assert db._conn.execute("SELECT content FROM feedback").fetchall() == [("adorei",)]


def test_provider_failure_sends_error_and_saves_nothing(chunks):
    llm._providers = []
    recorder = Recorder()
    run(bot.process_text(make_update(recorder), CONTEXT, "oi"))
    assert recorder.visible == [bot.ERROR_REPLY]
    assert db.get_history(recorder.chat_id) == []


def test_unexpected_error_still_answers_and_removes_typing(monkeypatch):
    async def broken_retrieve(*args, **kwargs):
        raise RuntimeError("chroma quebrou")

    monkeypatch.setattr(bot, "retrieve_context", broken_retrieve)
    llm._providers = [provider("groq", [completion("não deveria chegar aqui")])]
    recorder = Recorder()
    run(bot.process_text(make_update(recorder), CONTEXT, "oi"))
    assert recorder.visible == [bot.ERROR_REPLY]


def test_retrieve_context_survives_network_errors(monkeypatch):
    async def broken_embed(**kwargs):
        raise ConnectionError("sem internet")

    monkeypatch.setattr(bot.gemini_client.aio.models, "embed_content", broken_embed)
    assert run(bot.retrieve_context("oi", "cc")) is None


def test_long_answer_is_split(chunks):
    long_answer = "\n".join("parágrafo " + "w" * 90 for _ in range(100))
    llm._providers = [provider("groq", [completion(long_answer)])]
    recorder = Recorder()
    run(bot.process_text(make_update(recorder), CONTEXT, "explica tudo"))
    assert len(recorder.visible) >= 3


def test_html_rejected_falls_back_to_plain_text(chunks):
    llm._providers = [provider("groq", [completion("**negrito** e `código`")])]
    recorder = Recorder()
    recorder.html_rejected = True
    run(bot.process_text(make_update(recorder), CONTEXT, "oi"))
    assert recorder.visible == ["negrito e código"]


def test_search_course_follows_named_course_only_for_real_course_names(chunks):
    db.set_course(recorder_id := 1000, CC)
    llm._providers = [provider("groq", [completion("nenhum"), completion("r1"), completion("nenhum"), completion("r2"),
                                        completion("r3")])]
    run(bot.process_text(make_update(Recorder(recorder_id)), CONTEXT, "quantas horas exige engenharia civil?"))
    run(bot.process_text(make_update(Recorder(recorder_id)), CONTEXT, "registro de software conta em qual grupo?"))
    run(bot.process_text(make_update(Recorder(recorder_id)), CONTEXT, "quanto vale produção técnica?"))
    assert chunks == ["ec", "cc", "cc"]
    assert db.get_course(recorder_id) == CC


def test_course_statement_is_registered_before_search(chunks):
    llm._providers = [provider("groq", [completion(tool_calls=[tool_call("set_course", '{"course": "Engenharia Civil"}')]),
                                        completion("resposta")])]
    run(bot.process_text(make_update(Recorder(5)), CONTEXT, "sou de engenharia civil, como é o TCC?"))
    assert db.get_course(5) == EC
    assert chunks == ["ec"]


def test_activity_message_shows_confirmation(chunks):
    db.set_course(1000, CC)
    llm._providers = [provider("groq", [completion("nenhum"), extraction_call(ENGLISH_COURSE)])]
    recorder = Recorder()
    run(bot.process_text(make_update(recorder), CONTEXT, "fiz um curso de inglês de 40 horas"))
    assert [e[0] for e in recorder.events] == ["send", "delete", "send"]
    confirmation = recorder.events[2]
    assert "Curso de inglês" in confirmation[1] and "contam 20h" in confirmation[1]
    buttons = confirmation[2].inline_keyboard[0]
    assert [b.text for b in buttons] == ["Salvar", "Cancelar"]
    assert db.get_history(1000)[0] == ("user", "fiz um curso de inglês de 40 horas")
    assert chunks == []   # no RAG search needed


def test_activity_without_hours_asks_for_missing_info(chunks):
    db.set_course(1000, CC)
    missing = {"group": 1, "item": "c", "activity_name": "Monitoria", "certificate_hours": None,
               "credited_hours": None, "explanation": "até 3h por semana", "missing_info": "número de semanas"}
    llm._providers = [provider("groq", [extraction_call(missing)])]
    recorder = Recorder()
    run(bot.process_text(make_update(recorder), CONTEXT, "fui monitor com bolsa"))
    last = recorder.events[-1]
    assert "Faltou: número de semanas" in last[1] and last[2] is None


def test_long_confirmation_is_split_and_keeps_buttons_on_last_part(chunks):
    db.set_course(1000, CC)
    many = [dict(ENGLISH_COURSE, activity_name=f"Curso {i} " + "n" * 80, explanation="e" * 200) for i in range(25)]
    llm._providers = [provider("groq", [completion("nenhum"), extraction_call(*many)])]
    recorder = Recorder()
    run(bot.process_text(make_update(recorder), CONTEXT, "fiz estes cursos"))
    sends = [e for e in recorder.events if e[0] == "send" and e[1] != "Digitando..."]
    assert len(sends) >= 2
    assert sends[-1][2] is not None and all(s[2] is None for s in sends[:-1])


# ---------- certificates ----------

@pytest.fixture
def pdf_text(monkeypatch):
    holder = {"text": "Certificamos que Fulano participou do minicurso Docker com carga horária de 8 horas."}
    monkeypatch.setattr(horas, "read_pdf", lambda data: holder["text"])
    monkeypatch.setattr(horas, "read_image", lambda data: holder["text"])
    return holder


def cert_update(recorder, **kwargs):
    attachment = FakeAttachment(b"%PDF-1.4", file_name="docker.pdf", mime_type="application/pdf", **kwargs)
    return make_update(recorder, document=attachment), attachment


def test_certificate_requires_known_course(pdf_text):
    recorder = Recorder()
    update, _ = cert_update(recorder)
    run(bot.handle_certificate(update, CONTEXT))
    assert "me diga qual é o seu curso" in recorder.sent[0]
    db.set_course(recorder.chat_id, "Engenharia Mecânica")
    run(bot.handle_certificate(update, CONTEXT))
    assert "Ainda não tenho o regulamento" in recorder.sent[1]


def test_certificate_too_big(pdf_text):
    db.set_course(1000, CC)
    recorder = Recorder()
    update, _ = cert_update(recorder, file_size=50 * 1024 * 1024)
    run(bot.handle_certificate(update, CONTEXT))
    assert recorder.sent == ["Esse arquivo é grande demais (máximo 10 MB). Tente mandar uma versão menor."]


@pytest.mark.parametrize("scenario,expected", [
    ("download", "Não consegui abrir esse arquivo"),
    ("unreadable", "Não consegui ler o texto desse arquivo"),
    ("providers_down", "não consegui analisar \"docker.pdf\" agora"),
    ("no_activity", "Não identifiquei em \"docker.pdf\""),
])
def test_certificate_failures_replace_status_message(scenario, expected, pdf_text):
    db.set_course(1000, CC)
    recorder = Recorder()
    update, _ = cert_update(recorder, fail_download=(scenario == "download"))
    if scenario == "unreadable":
        pdf_text["text"] = "  ilegível "
    llm._providers = {"providers_down": [], "no_activity": [provider("groq", [completion("nada")])]}.get(
        scenario, [provider("groq")])
    run(bot.handle_certificate(update, CONTEXT))
    assert len(recorder.visible) == 1 and expected in recorder.visible[0]
    assert recorder.events[0][1].startswith("Analisando")


def test_certificate_success_creates_pending_with_file_and_caption(pdf_text, monkeypatch):
    db.set_course(1000, CC)
    seen_text = []
    original = horas.extract

    async def spy_extract(text, course):
        seen_text.append(text)
        return await original(text, course)

    monkeypatch.setattr(horas, "extract", spy_extract)
    docker = {"group": 4, "item": "c", "activity_name": "Minicurso Docker", "certificate_hours": 8,
              "credited_hours": 8, "explanation": "1h por hora"}
    llm._providers = [provider("groq", [extraction_call(docker)])]
    recorder = Recorder()
    attachment = FakeAttachment(b"%PDF", file_name="docker.pdf", mime_type="application/pdf", file_id="FILE-DOCKER")
    run(bot.handle_certificate(make_update(recorder, document=attachment, caption="foi online"), CONTEXT))
    assert "Mensagem do aluno: foi online" in seen_text[0]
    assert recorder.visible[-1].startswith("Encontrei isto")
    (pending,) = horas._pending.values()
    assert pending.file_id == "FILE-DOCKER" and pending.source == "pdf" and pending.course == CC


def test_student_cannot_queue_unbounded_certificates(pdf_text, monkeypatch):
    db.set_course(1000, CC)
    release = asyncio.Event()

    async def blocked_extract(text, course):
        await release.wait()
        return []

    monkeypatch.setattr(horas, "extract", blocked_extract)

    async def main():
        recorder = Recorder()
        tasks = [asyncio.create_task(bot.handle_certificate(cert_update(recorder)[0], CONTEXT)) for _ in range(7)]
        await asyncio.sleep(0.05)
        refused = [t for t in recorder.sent if t.startswith("Já estou analisando")]
        release.set()
        await asyncio.gather(*tasks)
        return refused

    assert len(run(main())) == 2
    assert bot._certificates_in_flight == {}


def test_photo_certificate_uses_ocr_label(pdf_text):
    db.set_course(1000, CC)
    llm._providers = [provider("groq", [completion("nada")])]
    recorder = Recorder()
    photo = FakeAttachment(b"jpeg", file_size=1000)
    run(bot.handle_certificate(make_update(recorder, photo=[FakeAttachment(b"small"), photo]), CONTEXT))
    assert recorder.events[0][1] == "Analisando sua foto..."
    assert "Não identifiquei em sua foto" in recorder.visible[0]


# ---------- buttons ----------

def _pending_query(recorder, action, activities=None, answer_error=None):
    activities = activities or [horas.Activity(4, "c", "Minicurso Docker", 8, 8, "1h por hora", "")]
    token = horas.add_pending(recorder.chat_id, activities, "pdf", "F1", CC)
    markup = InlineKeyboardMarkup([[]])
    return FakeQuery(recorder, f"hrs:{action}:{token}", "Encontrei isto: ...", markup, answer_error), token


def test_save_click_stores_hours_and_shows_summary():
    db.set_course(1000, CC)
    recorder = Recorder()
    query, _ = _pending_query(recorder, "ok")
    run(bot.handle_hours_callback(make_callback_update(query), CONTEXT))
    assert db.hours_by_group(1000, CC) == {4: 8}
    assert query.message.text.endswith("Salvo!")
    assert "Total: 8/192h" in recorder.sent[-1]
    assert db.get_history(1000)[-1] == ("model", "Salvei no seu registro de horas: Minicurso Docker.")


def test_cancel_click_saves_nothing():
    recorder = Recorder()
    query, _ = _pending_query(recorder, "no")
    run(bot.handle_hours_callback(make_callback_update(query), CONTEXT))
    assert db.list_complementary_hours(1000) == []
    assert query.message.text.endswith("Cancelado, nada foi salvo.")


def test_late_click_still_saves():
    db.set_course(1000, CC)
    recorder = Recorder()
    query, _ = _pending_query(recorder, "ok", answer_error=BadRequest("Query is too old"))
    run(bot.handle_hours_callback(make_callback_update(query), CONTEXT))
    assert db.hours_by_group(1000, CC) == {4: 8}


def test_double_click_does_not_crash_or_save_twice():
    db.set_course(1000, CC)
    recorder = Recorder()
    query, token = _pending_query(recorder, "ok")
    update = make_callback_update(query)
    run(bot.handle_hours_callback(update, CONTEXT))
    run(bot.handle_hours_callback(update, CONTEXT))
    assert db.hours_by_group(1000, CC) == {4: 8}


def test_expired_click_explains():
    recorder = Recorder()
    query = FakeQuery(recorder, "hrs:ok:deadbeef", "Encontrei isto", InlineKeyboardMarkup([[]]))
    run(bot.handle_hours_callback(make_callback_update(query), CONTEXT))
    assert "expirou" in recorder.sent[-1]


def test_delete_click_and_repeated_delete():
    db.set_course(1000, CC)
    db.add_complementary_hours(1000, 4, "c", "Curso A", 8, 8, "pdf", None, "x", course=CC)
    db.add_complementary_hours(2000, 4, "c", "De outro aluno", 8, 8, "pdf", None, "x", course=CC)
    entry_id = db.list_complementary_hours(1000)[0][0]
    other_id = db.list_complementary_hours(2000)[0][0]
    recorder = Recorder()
    text, markup = bot.hours_listing(1000)
    query = FakeQuery(recorder, f"hrs:del:{entry_id}", text, markup)
    run(bot.handle_hours_callback(make_callback_update(query), CONTEXT))
    assert db.list_complementary_hours(1000) == []
    run(bot.handle_hours_callback(make_callback_update(query), CONTEXT))   # same click again: no crash
    forged = FakeQuery(recorder, f"hrs:del:{other_id}", "x", None)
    run(bot.handle_hours_callback(make_callback_update(forged), CONTEXT))
    assert len(db.list_complementary_hours(2000)) == 1


def test_hours_listing_with_many_entries_fits_telegram_limits():
    db.set_course(1000, CC)
    for i in range(150):
        db.add_complementary_hours(1000, (i % 7) + 1, None, f"Atividade número {i} com nome comprido", 2, 2,
                                   "pdf", None, "x", course=CC)
    text, markup = bot.hours_listing(1000)
    assert len(text) <= 4000
    assert sum(len(row) for row in markup.inline_keyboard) <= 100
    assert "Total:" in text


def test_hours_listing_empty_shows_suggestions():
    db.set_course(1000, EC)
    text, markup = bot.hours_listing(1000)
    assert "ainda não registrou" in text and "Onde ainda dá para ganhar horas" in text and markup is None


@pytest.mark.parametrize("course,expected", [
    (CC, "/coordcc"), (EC, "/coordec"), ("Engenharia de Software", "/coordes"),
    ("Engenharia de Produção", "/coordep"), ("Engenharia Mecânica", "Ainda não tenho"), (None, "Me diga qual"),
])
def test_submission_command(course, expected):
    if course:
        db.set_course(1000, course)
    recorder = Recorder()
    run(bot.submission_command(make_update(recorder), CONTEXT))
    assert expected in recorder.sent[0]


# ---------- voice ----------

def test_voice_too_long_or_not_understood(monkeypatch):
    recorder = Recorder()
    run(bot.handle_voice(make_update(recorder, voice=FakeAttachment(b"ogg", duration=600)), CONTEXT))
    assert "longo demais" in recorder.sent[0]
    llm._providers = [provider("groq", transcripts=[SimpleNamespace(text="")])]
    run(bot.handle_voice(make_update(recorder, voice=FakeAttachment(b"ogg", duration=5)), CONTEXT))
    assert "Não consegui entender" in recorder.sent[1]


def test_voice_transcription_goes_to_text_flow(monkeypatch):
    received = []

    async def fake_process(update, context, text):
        received.append(text)

    monkeypatch.setattr(bot, "process_text", fake_process)
    llm._providers = [provider("groq", transcripts=[SimpleNamespace(text="quantas horas preciso")])]
    recorder = Recorder()
    run(bot.handle_voice(make_update(recorder, voice=FakeAttachment(b"ogg", duration=5)), CONTEXT))
    assert received == ["quantas horas preciso"]
    assert recorder.sent == []   # no "Você disse" echo


# ---------- update routing ----------

@pytest.fixture
def app():
    application = bot.build_application()
    application.bot._bot_user = User(id=99, first_name="Bot", is_bot=True, username="ufc_test_bot")
    return application


def tg_update(application, text, chat_type="private", edited=False):
    entities = [MessageEntity(MessageEntity.BOT_COMMAND, 0, len(text.split()[0]))] if text.startswith("/") else None
    message = Message(message_id=1, date=datetime.now(), chat=Chat(id=1, type=chat_type), text=text,
                      entities=entities, from_user=User(id=1, first_name="Aluno", is_bot=False))
    message.set_bot(application.bot)
    return Update(update_id=1, edited_message=message) if edited else Update(update_id=1, message=message)


def matching_callbacks(application, update):
    return [h.callback.__name__ for group in application.handlers.values() for h in group if h.check_update(update)]


def test_routing_new_private_messages(app):
    assert matching_callbacks(app, tg_update(app, "oi"))[0] == "handle_message"
    assert matching_callbacks(app, tg_update(app, "/horas"))[0] == "hours_command"


def test_edited_messages_are_ignored(app):
    assert matching_callbacks(app, tg_update(app, "oi editado", edited=True)) == []
    assert matching_callbacks(app, tg_update(app, "/horas", edited=True)) == []


def test_group_chats_are_ignored(app):
    assert matching_callbacks(app, tg_update(app, "oi", chat_type="group")) == []
    assert matching_callbacks(app, tg_update(app, "/horas", chat_type="supergroup")) == []


def test_unknown_command_gets_a_reply(app):
    assert matching_callbacks(app, tg_update(app, "/naoexiste"))[0] == "unknown_command"
    recorder = Recorder()
    run(bot.unknown_command(make_update(recorder), CONTEXT))
    assert "/help" in recorder.sent[0]


def test_every_listed_command_is_registered(app):
    from telegram.ext import CommandHandler

    registered = {c for group in app.handlers.values() for h in group if isinstance(h, CommandHandler)
                  for c in h.commands}
    listed = set(re.findall(r"^/(\w+)", bot.COMMANDS_TEXT, re.M))
    assert listed == registered
