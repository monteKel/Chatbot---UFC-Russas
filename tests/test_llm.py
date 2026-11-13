import asyncio

import openai
import pytest

import llm
from fakes import completion, provider, rate_limit, status_error, timeout_error, tool_call


def run(coro):
    return asyncio.run(coro)


MESSAGES = [{"role": "user", "content": "oi"}]


# ---------- course text helpers ----------

@pytest.mark.parametrize("text,expected", [
    ("Sou de Ciência da Computação", True),
    ("faço engenharia civil", True),
    ("meu curso é ES", True),  # "curso" triggers detection; the model decides
    ("quantas horas complementares preciso?", False),
    ("qual o prazo do TCC?", False),
])
def test_mentions_course(text, expected):
    assert llm.mentions_course(text) is expected


@pytest.mark.parametrize("text,expected", [
    ("quantas horas complementares exige engenharia civil?", "Engenharia Civil"),
    ("e em Engenharia de Software?", "Engenharia de Software"),
    ("como é o TCC de ciência da computação", "Ciência da Computação"),
    ("eng. de produção tem estágio obrigatório?", "Engenharia de Produção"),
    ("comparar engenharia civil e engenharia mecânica", None),
    # Words that appear inside other terms must not switch the search to another course.
    ("registro de software conta em qual grupo?", None),
    ("quantas horas de produção técnica posso ter?", None),
    ("a disciplina mecânica dos solos tem monitoria?", None),
    ("maratona de programação conta hora?", None),
])
def test_course_named_in(text, expected):
    assert llm.course_named_in(text) == expected


# ---------- failover ----------

def test_answer_uses_first_provider():
    llm._providers = [provider("groq", [completion("resposta groq")]), provider("openrouter")]
    assert run(llm.answer(MESSAGES)) == ("resposta groq", "groq")
    assert llm._providers[1]["client"].calls == []


def test_long_rate_limit_pauses_provider_and_falls_back(no_sleep):
    llm._providers = [provider("groq", [rate_limit("40")]), provider("openrouter", [completion("reserva")])]
    assert run(llm.answer(MESSAGES)) == ("reserva", "openrouter")
    assert llm._cooldown_until["groq"] > 0
    # While paused, groq is skipped entirely.
    llm._providers[1]["client"].script = [completion("de novo reserva")]
    assert run(llm.answer(MESSAGES)) == ("de novo reserva", "openrouter")
    assert len(llm._providers[0]["client"].calls) == 1


def test_short_rate_limit_waits_and_retries_same_provider(no_sleep):
    llm._providers = [provider("groq", [rate_limit("2"), completion("depois de esperar")]), provider("openrouter")]
    assert run(llm.answer(MESSAGES)) == ("depois de esperar", "groq")
    assert no_sleep == [2.0]


def test_repeated_short_waits_respect_budget(no_sleep):
    llm._providers = [provider("groq", [rate_limit("3"), rate_limit("3"), completion("x")]),
                      provider("openrouter", [completion("reserva")])]
    # Default budget is 5s: 3s fits, the second 3s does not, so it falls back.
    assert run(llm.answer(MESSAGES)) == ("reserva", "openrouter")
    assert no_sleep == [3.0]


@pytest.mark.parametrize("error,paused", [
    (status_error(openai.InternalServerError, 503), 30),
    (status_error(openai.AuthenticationError, 401), 3600),
    (status_error(openai.NotFoundError, 404), 3600),
    (timeout_error(), 30),
])
def test_errors_pause_provider(error, paused, no_sleep):
    llm._providers = [provider("groq", [error]), provider("openrouter", [completion("ok")])]
    assert run(llm.answer(MESSAGES)) == ("ok", "openrouter")
    remaining = llm._cooldown_until["groq"] - llm.time.monotonic()
    assert paused - 5 < remaining <= paused


def test_bad_request_and_too_large_fall_back_without_pause():
    for status, cls in ((400, openai.BadRequestError), (413, openai.APIStatusError)):
        llm._cooldown_until.clear()
        llm._providers = [provider("groq", [status_error(cls, status)]), provider("openrouter", [completion("ok")])]
        assert run(llm.answer(MESSAGES)) == ("ok", "openrouter")
        assert "groq" not in llm._cooldown_until


def test_too_large_request_retries_with_smaller_answer_budget():
    too_large = status_error(openai.APIStatusError, 413, message=(
        "Error code: 413 - Request too large for model on tokens per minute (TPM): Limit 8000, Requested 8429"))
    llm._providers = [provider("groq", [too_large, completion("coube")], max_tokens=1800), provider("openrouter")]
    assert run(llm.answer(MESSAGES)) == ("coube", "groq")
    calls = llm._providers[0]["client"].calls
    assert [c["max_tokens"] for c in calls] == [1800, 1800 - 429 - 50]


def test_too_large_prompt_that_cannot_fit_falls_back():
    too_large = status_error(openai.APIStatusError, 413, message="Limit 8000, Requested 9900")
    llm._providers = [provider("groq", [too_large], max_tokens=1800), provider("openrouter", [completion("reserva")])]
    assert run(llm.answer(MESSAGES)) == ("reserva", "openrouter")


def test_empty_or_malformed_response_falls_back():
    llm._providers = [provider("groq", [completion(None)]), provider("openrouter", [completion("ok")])]
    assert run(llm.answer(MESSAGES)) == ("ok", "openrouter")
    from types import SimpleNamespace
    llm._providers = [provider("groq", [SimpleNamespace(choices=[])]), provider("openrouter", [completion("ok")])]
    assert run(llm.answer(MESSAGES)) == ("ok", "openrouter")


def test_all_providers_failing_returns_none(no_sleep):
    llm._providers = [provider("groq", [rate_limit("60")]), provider("openrouter", [timeout_error()])]
    assert run(llm.answer(MESSAGES)) == (None, None)


def test_patient_call_waits_for_cooldown(no_sleep):
    llm._providers = [provider("groq", [completion(tool_calls=[])]), provider("openrouter")]
    llm._pause("groq", 10)
    calls, name = run(llm.call_tool(MESSAGES, llm.SET_COURSE_TOOL, max_wait=60))
    assert name == "groq" and calls == []
    assert no_sleep and 9 < no_sleep[0] <= 10


def test_excluded_provider_is_never_called():
    llm._providers = [provider("gemini", [completion("não devia")]), provider("groq", [completion(tool_calls=[])])]
    _, name = run(llm.call_tool(MESSAGES, llm.SET_COURSE_TOOL, exclude=("gemini",)))
    assert name == "groq"
    assert llm._providers[0]["client"].calls == []


# ---------- tool calls ----------

def test_call_tool_skips_malformed_arguments():
    calls_script = [
        tool_call("set_course", "{nao é json"),
        tool_call("outra_funcao", '{"course": "Engenharia Civil"}'),
        tool_call("set_course", '["lista"]'),
        tool_call("set_course", '{"course": "Engenharia Civil"}'),
    ]
    llm._providers = [provider("groq", [completion(tool_calls=calls_script)])]
    calls, _ = run(llm.call_tool(MESSAGES, llm.SET_COURSE_TOOL))
    assert calls == [{"course": "Engenharia Civil"}]


@pytest.mark.parametrize("arguments,expected", [
    ('{"course": "Ciencia da Computacao"}', "Ciência da Computação"),
    ('{"course": "engenharia de software"}', "Engenharia de Software"),
    ('{"course": "Medicina"}', None),
    ('{}', None),
])
def test_detect_course_normalizes(arguments, expected):
    llm._providers = [provider("groq", [completion(tool_calls=[tool_call("set_course", arguments)])])]
    assert run(llm.detect_course("sou de ...", None)) == expected


def test_detect_course_without_call_or_providers():
    llm._providers = [provider("groq", [completion("nenhum")])]
    assert run(llm.detect_course("oi", None)) is None
    llm._providers = []
    assert run(llm.detect_course("sou de civil", None)) is None


def test_detect_course_includes_current_course_in_prompt():
    llm._providers = [provider("groq", [completion("nenhum")])]
    run(llm.detect_course("quero trocar meu curso", "Engenharia Civil"))
    system = llm._providers[0]["client"].calls[0]["messages"][0]["content"]
    assert "Engenharia Civil" in system


# ---------- transcription ----------

def test_transcribe():
    from types import SimpleNamespace
    llm._providers = [provider("groq", transcripts=[SimpleNamespace(text="  olá bot  ")])]
    assert run(llm.transcribe(b"audio", "a.ogg")) == "olá bot"
    llm._providers = [provider("groq", transcripts=[SimpleNamespace(text="   ")])]
    assert run(llm.transcribe(b"audio", "a.ogg")) is None
    llm._providers = [provider("groq", transcripts=[timeout_error()])]
    assert run(llm.transcribe(b"audio", "a.ogg")) is None
    llm._providers = [provider("openrouter")]
    assert run(llm.transcribe(b"audio", "a.ogg")) is None
