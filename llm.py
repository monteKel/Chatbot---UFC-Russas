import asyncio
import json
import logging
import os
import re
import time
import unicodedata
from typing import Awaitable, Callable

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    RateLimitError,
)

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = float(os.environ.get("LLM_REQUEST_TIMEOUT", 20))
SHORT_RETRY_MAX_WAIT = 5

VALID_COURSES = {
    "Ciência da Computação",
    "Engenharia de Software",
    "Engenharia de Produção",
    "Engenharia Civil",
    "Engenharia Mecânica",
}

SET_COURSE_TOOL = {
    "type": "function",
    "function": {
        "name": "set_course",
        "description": (
            "Registra ou corrige o curso de graduação do aluno. Só chame esta função quando "
            "o aluno afirmar claramente e sem ambiguidade qual curso faz (ex: 'eu sou de "
            "engenharia de software', 'meu curso é ciência da computação'), ou quando ele "
            "pedir explicitamente para corrigir/trocar o curso já registrado. NÃO chame com "
            "base em pistas indiretas, suposições ou menções a disciplinas/atividades que "
            "poderiam pertencer a mais de um curso — nesses casos, pergunte ao aluno qual é "
            "o curso antes de registrar."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "course": {
                    "type": "string",
                    "enum": sorted(VALID_COURSES),
                    "description": "Nome completo do curso de graduação do aluno, na lista de cursos do Campus de Russas.",
                }
            },
            "required": ["course"],
            "additionalProperties": False,
        },
    },
}

DETECT_COURSE_PROMPT = (
    "Sua única tarefa é decidir se a mensagem do aluno afirma claramente qual é o curso de graduação DELE "
    "no Campus da UFC em Russas, ou pede para corrigir o curso registrado. Se sim, chame set_course. "
    "Não chame se ele apenas perguntar sobre um curso, falar do curso de outra pessoa, ou der pistas indiretas. "
    "Se não for chamar a função, responda apenas: nenhum."
)


def normalize(text: str) -> str:
    stripped = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return stripped.casefold().strip()


_COURSE_BY_KEY = {normalize(c): c for c in VALID_COURSES}
_COURSE_HINT = re.compile(r"curso|comput|software|produc|civil|mecanic|engenharia|\bcc\b")


# Full course names only: bare words like "software", "produção" or "mecânica" also appear in
# activity and subject names ("registro de software", "produção técnica", "mecânica dos solos").
_COURSE_NAME_PATTERNS = {
    "Ciência da Computação": re.compile(r"\bciencias? da computacao\b"),
    "Engenharia de Software": re.compile(r"\beng(enharia|\.)? (de )?software\b"),
    "Engenharia de Produção": re.compile(r"\beng(enharia|\.)? (de )?producao\b"),
    "Engenharia Civil": re.compile(r"\beng(enharia|\.)? civil\b"),
    "Engenharia Mecânica": re.compile(r"\beng(enharia|\.)? mecanica\b"),
}


def mentions_course(text: str) -> bool:
    return bool(_COURSE_HINT.search(normalize(text)))


def course_named_in(text: str) -> str | None:
    normalized = normalize(text)
    found = {course for course, pattern in _COURSE_NAME_PATTERNS.items() if pattern.search(normalized)}
    return found.pop() if len(found) == 1 else None


def _client(base_url: str, api_key: str) -> AsyncOpenAI:
    return AsyncOpenAI(base_url=base_url, api_key=api_key, max_retries=0, timeout=REQUEST_TIMEOUT)


def _build_providers() -> list[dict]:
    providers = []
    if os.environ.get("GROQ_API_KEY"):
        providers.append({
            "name": "groq",
            "client": _client("https://api.groq.com/openai/v1", os.environ["GROQ_API_KEY"]),
            "model": os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b"),
            "max_tokens": 1800,
            "params": {"reasoning_effort": "low", "extra_body": {"include_reasoning": False}},
        })
    if os.environ.get("OPENROUTER_API_KEY"):
        models = [m.strip() for m in os.environ.get(
            "OPENROUTER_MODELS", "nvidia/nemotron-3-ultra-550b-a55b:free"
        ).split(",") if m.strip()]
        extra_body = {"reasoning": {"effort": "low", "exclude": True}}
        if len(models) > 1:
            extra_body["models"] = models
        providers.append({
            "name": "openrouter",
            "client": _client("https://openrouter.ai/api/v1", os.environ["OPENROUTER_API_KEY"]),
            "model": models[0],
            "max_tokens": 3000,
            "params": {"extra_body": extra_body},
        })
    if os.environ.get("GEMINI_API_KEY") and os.environ.get("GEMINI_FALLBACK", "1") == "1":
        providers.append({
            "name": "gemini",
            "client": _client("https://generativelanguage.googleapis.com/v1beta/openai/", os.environ["GEMINI_API_KEY"]),
            "model": os.environ.get("GEMINI_MODEL", "gemini-flash-lite-latest"),
            "max_tokens": 1500,
            "params": {},
        })
    return providers


_providers: list[dict] | None = None
_cooldown_until: dict[str, float] = {}


def get_providers() -> list[dict]:
    global _providers
    if _providers is None:
        _providers = _build_providers()
    return _providers


def _pause(name: str, seconds: float) -> None:
    _cooldown_until[name] = time.monotonic() + seconds
    logger.warning("Provedor %s pausado por %.0fs", name, seconds)


def _retry_after(error: APIStatusError, default: float) -> float:
    raw = error.response.headers.get("retry-after", "") if error.response is not None else ""
    try:
        return min(float(raw), 600)
    except ValueError:
        return default


async def _create(provider: dict, messages: list[dict], tools: list[dict] | None = None, max_wait: float = SHORT_RETRY_MAX_WAIT):
    kwargs = dict(model=provider["model"], messages=messages, max_tokens=provider["max_tokens"], **provider["params"])
    if tools:
        kwargs.update(tools=tools, tool_choice="auto")
    budget = max_wait
    while True:
        try:
            return await provider["client"].chat.completions.create(**kwargs)
        except RateLimitError as e:
            # Per-minute token windows (e.g. Groq's 8K TPM) often free up in a few seconds.
            wait = _retry_after(e, 999)
            if wait > budget:
                raise
            budget -= wait
            await asyncio.sleep(wait)
        except APIStatusError as e:
            # Groq counts prompt + max_tokens against the 8K TPM limit and answers 413 with the exact
            # overflow, so retry with a smaller answer budget when that leaves enough room.
            smaller = _max_tokens_that_fit(e, kwargs["max_tokens"])
            if smaller is None:
                raise
            logger.info("%s: pedido grande demais, tentando de novo com max_tokens=%d", provider["name"], smaller)
            kwargs["max_tokens"] = smaller


_TOO_LARGE = re.compile(r"Limit (\d+), Requested (\d+)")
MIN_ANSWER_TOKENS = 500


def _max_tokens_that_fit(error: APIStatusError, max_tokens: int) -> int | None:
    match = _TOO_LARGE.search(str(error)) if error.status_code == 413 else None
    if not match:
        return None
    limit, requested = int(match.group(1)), int(match.group(2))
    smaller = max_tokens - (requested - limit) - 50
    return smaller if MIN_ANSWER_TOKENS <= smaller < max_tokens else None


async def _with_failover(
    operation: Callable[[dict], Awaitable], exclude: tuple[str, ...] = (), max_wait: float = 0
) -> tuple[object, str | None]:
    for provider in get_providers():
        name = provider["name"]
        if name in exclude:
            continue
        remaining = _cooldown_until.get(name, 0) - time.monotonic()
        if remaining > 0:
            if remaining > max_wait:
                continue
            await asyncio.sleep(remaining)
        try:
            return await operation(provider), name
        except RateLimitError as e:
            logger.warning("%s: limite atingido (%s)", name, e)
            _pause(name, _retry_after(e, 60))
        except (APITimeoutError, APIConnectionError) as e:
            logger.warning("%s: timeout/conexão (%s)", name, e)
            _pause(name, 30)
        except APIStatusError as e:
            logger.warning("%s: erro %s (%s)", name, e.status_code, e)
            if e.status_code >= 500:
                _pause(name, 30)
            elif e.status_code in (401, 402, 403, 404):
                _pause(name, 3600)
        except Exception:
            logger.exception("%s: falha inesperada", name)
    return None, None


async def call_tool(
    messages: list[dict], tool: dict, exclude: tuple[str, ...] = (), max_wait: float = SHORT_RETRY_MAX_WAIT
) -> tuple[list[dict] | None, str | None]:
    tool_name = tool["function"]["name"]

    async def operation(provider: dict) -> list[dict]:
        response = await _create(provider, messages, tools=[tool], max_wait=max_wait)
        calls = []
        for call in response.choices[0].message.tool_calls or []:
            if call.function.name != tool_name:
                continue
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                continue
            if isinstance(args, dict):
                calls.append(args)
        return calls

    return await _with_failover(operation, exclude, max_wait)


async def detect_course(user_text: str, current_course: str | None) -> str | None:
    system = DETECT_COURSE_PROMPT
    if current_course:
        system += f"\nCurso atualmente registrado: {current_course}."
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user_text}]
    calls, provider = await call_tool(messages, SET_COURSE_TOOL)
    if provider is None:
        logger.warning("Detecção de curso indisponível em todos os provedores")
        return None
    for args in calls:
        course = _COURSE_BY_KEY.get(normalize(str(args.get("course", ""))))
        if course:
            return course
    return None


async def answer(messages: list[dict]) -> tuple[str | None, str | None]:
    async def operation(provider: dict) -> str:
        response = await _create(provider, messages)
        choice = response.choices[0]
        if choice.finish_reason == "length":
            logger.warning("%s: resposta cortada por max_tokens", provider["name"])
        if not choice.message.content:
            raise RuntimeError("resposta vazia")
        return choice.message.content

    # A short Groq pause (e.g. while a certificate batch uses the token window) is worth waiting
    # for instead of falling back to the much slower free providers.
    return await _with_failover(operation, max_wait=SHORT_RETRY_MAX_WAIT)


async def transcribe(audio: bytes, filename: str) -> str | None:
    groq = next((p for p in get_providers() if p["name"] == "groq"), None)
    if groq is None:
        return None
    try:
        result = await groq["client"].audio.transcriptions.create(
            model=os.environ.get("GROQ_WHISPER_MODEL", "whisper-large-v3-turbo"),
            file=(filename, audio),
            language="pt",
        )
    except Exception:
        logger.exception("groq: falha na transcrição de áudio")
        return None
    return (result.text or "").strip() or None
