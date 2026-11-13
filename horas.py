import asyncio
import io
import logging
import re
import secrets
import time
from dataclasses import dataclass, field

from pypdf import PdfReader

import db
import llm
from regras_horas import COURSE_RULES, ROMAN

logger = logging.getLogger(__name__)

MAX_PDF_PAGES = 5
# Certificates aren't time-critical, so wait out Groq's per-minute token window instead of
# falling back to the much slower free providers.
EXTRACTION_MAX_WAIT = 60
MIN_READABLE_CHARS = 40
MAX_TEXT_CHARS = 6000
PENDING_TTL = 3600
# Gemini's free tier trains on submitted content; certificates carry names and IDs.
PRIVATE_EXCLUDE = ("gemini",)

_ACTIVITY_HINT = re.compile(
    r"\b(fiz|participei|conclui|terminei|completei|cursei|ministrei|apresentei|publiquei|organizei"
    r"|fui (monitor|voluntari|bolsista|representante)|tenho (um |o )?certificado)"
)
_CPF = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")
_LONG_NUMBER = re.compile(r"\b\d{9,}\b")

EXTRACTION_PROMPT = """Você analisa comprovantes de atividades complementares de alunos do curso {course} da UFC, Campus de Russas.

Regras oficiais do curso:
{rules}

Instruções:
- Se o texto for um comprovante (certificado, declaração) ou o aluno disser que JÁ realizou uma atividade, chame register_activities com uma entrada por atividade.
- Escolha o grupo (1 a 7, correspondendo a I a VII) e a letra do item conforme as regras acima.
- Calcule credited_hours aplicando a regra de conversão e o limite do item (ex.: "1 hora por 2 horas de atividade" transforma 40h em 20h). NÃO aplique o teto do grupo; isso é feito depois.
- Use apenas números que estejam no texto. Se faltar um dado necessário para o cálculo (carga horária, número de semanas, dias de evento), use credited_hours null e diga em missing_info o que falta.
- Se a atividade não se encaixar em nenhum item das regras, ou se o texto não for um comprovante nem relato de atividade concluída, não chame a função."""

REGISTER_TOOL = {
    "type": "function",
    "function": {
        "name": "register_activities",
        "description": "Registra atividades complementares comprovadas pelo documento ou que o aluno diz já ter realizado.",
        "parameters": {
            "type": "object",
            "properties": {
                "activities": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "group": {"type": "integer", "enum": [1, 2, 3, 4, 5, 6, 7], "description": "Grupo da atividade: 1=I, 2=II, ..., 7=VII."},
                            "item": {"type": "string", "description": "Letra do item dentro do grupo, ex.: 'c'."},
                            "activity_name": {"type": "string", "description": "Nome curto da atividade, ex.: 'Curso de Python (Udemy)'."},
                            "certificate_hours": {"type": ["number", "null"], "description": "Carga horária que consta no texto, ou null se não informada."},
                            "credited_hours": {"type": ["number", "null"], "description": "Horas que contam após aplicar a regra do item, ou null se faltar informação."},
                            "explanation": {"type": "string", "description": "Como as horas foram calculadas, citando a regra do item."},
                            "missing_info": {"type": "string", "description": "O que falta para calcular as horas; vazio se nada falta."},
                        },
                        "required": ["group", "activity_name", "credited_hours", "explanation"],
                    },
                }
            },
            "required": ["activities"],
        },
    },
}


@dataclass
class Activity:
    group: int
    item: str | None
    name: str
    certificate_hours: float | None
    credited_hours: float | None
    explanation: str
    missing_info: str


@dataclass
class Pending:
    chat_id: int
    activities: list[Activity]
    source: str
    file_id: str | None
    course: str
    created: float = field(default_factory=time.monotonic)


_pending: dict[str, Pending] = {}
# One extraction at a time, so a batch of certificates doesn't burst through the token limit.
_extraction_lock = asyncio.Lock()


def extraction_busy() -> bool:
    return _extraction_lock.locked()


def supports(course: str | None) -> bool:
    return course in COURSE_RULES


def declares_activity(text: str) -> bool:
    return bool(_ACTIVITY_HINT.search(llm.normalize(text)))


def fmt(hours: float) -> str:
    return f"{hours:g}".replace(".", ",")


def _ocr_image(data: bytes) -> str:
    import pytesseract
    from PIL import Image, ImageOps

    image = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("L")
    return pytesseract.image_to_string(image, lang="por")


def read_image(data: bytes) -> str:
    return _ocr_image(data)


def read_pdf(data: bytes) -> str:
    pages = PdfReader(io.BytesIO(data)).pages[:MAX_PDF_PAGES]
    text = "\n".join(page.extract_text() or "" for page in pages)
    if len(text.strip()) >= MIN_READABLE_CHARS:
        return text
    # Scanned PDF: the pages are images, so OCR the embedded pictures instead.
    return "\n".join(_ocr_image(image.data) for page in pages for image in page.images)


def is_readable(text: str) -> bool:
    return len(re.sub(r"\s+", "", text)) >= MIN_READABLE_CHARS


def _redact(text: str) -> str:
    return _LONG_NUMBER.sub("[número]", _CPF.sub("[CPF]", text))


_NUMBER_IN_TEXT = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*h?\s*$", re.IGNORECASE)
_ROMAN_TO_INT = {numeral: number for number, numeral in ROMAN.items()}


def _number(value) -> float | None:
    # Models sometimes send numbers as strings ("20", "20,5", "12 h").
    if isinstance(value, str) and (match := _NUMBER_IN_TEXT.match(value)):
        value = float(match.group(1).replace(",", "."))
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if value >= 0 else None


def _group(value) -> int | None:
    if isinstance(value, str):
        token = value.strip().upper().removeprefix("GRUPO").strip()
        value = _ROMAN_TO_INT.get(token, token)
    number = _number(value)
    return int(number) if number is not None and number.is_integer() else None


def _parse(args: dict, groups: dict) -> Activity | None:
    group = _group(args.get("group"))
    name = str(args.get("activity_name") or "").strip()
    if group not in groups or not name:
        return None
    item = str(args.get("item") or "").strip().strip(")").lower() or None
    return Activity(
        group=group,
        item=item,
        name=name,
        certificate_hours=_number(args.get("certificate_hours")),
        credited_hours=_number(args.get("credited_hours")),
        explanation=str(args.get("explanation") or "").strip(),
        missing_info=str(args.get("missing_info") or "").strip(),
    )


async def extract(text: str, course: str) -> list[Activity] | None:
    """Returns the activities found, [] if none, or None if every provider failed."""
    rules = COURSE_RULES[course]
    messages = [
        {"role": "system", "content": EXTRACTION_PROMPT.format(course=course, rules=rules["rules"])},
        {"role": "user", "content": _redact(text)[:MAX_TEXT_CHARS]},
    ]
    async with _extraction_lock:
        calls, provider = await llm.call_tool(messages, REGISTER_TOOL, exclude=PRIVATE_EXCLUDE, max_wait=EXTRACTION_MAX_WAIT)
    if provider is None:
        return None
    activities = []
    for call in calls:
        for args in call.get("activities") or []:
            if isinstance(args, dict) and (activity := _parse(args, rules["groups"])):
                activities.append(activity)
    logger.info("Extração via %s: %d atividade(s)", provider, len(activities))
    return activities


def describe(activity: Activity, course: str) -> str:
    group_name = COURSE_RULES[course]["groups"][activity.group][0]
    lines = [f"• {activity.name}", f"  Grupo {ROMAN[activity.group]} ({group_name})"]
    certificate = f"{fmt(activity.certificate_hours)}h" if activity.certificate_hours is not None else "não informado"
    if activity.credited_hours is not None:
        lines.append(f"  No comprovante: {certificate} → contam {fmt(activity.credited_hours)}h")
    else:
        lines.append(f"  No comprovante: {certificate}. Faltou: {activity.missing_info or 'informação para calcular as horas'}")
    if activity.explanation:
        lines.append(f"  Regra: {activity.explanation}")
    return "\n".join(lines)


def add_pending(chat_id: int, activities: list[Activity], source: str, file_id: str | None, course: str) -> str:
    now = time.monotonic()
    for token in [t for t, p in _pending.items() if now - p.created > PENDING_TTL]:
        del _pending[token]
    token = secrets.token_hex(4)
    _pending[token] = Pending(chat_id, activities, source, file_id, course)
    return token


def pop_pending(token: str, chat_id: int) -> Pending | None:
    pending = _pending.get(token)
    if pending is None or pending.chat_id != chat_id or time.monotonic() - pending.created > PENDING_TTL:
        return None
    return _pending.pop(token)


def save(pending: Pending) -> None:
    for activity in pending.activities:
        db.add_complementary_hours(
            chat_id=pending.chat_id,
            group=activity.group,
            item=activity.item,
            name=activity.name,
            certificate_hours=activity.certificate_hours,
            credited_hours=activity.credited_hours,
            source=pending.source,
            file_id=pending.file_id,
            explanation=activity.explanation,
            course=pending.course,
        )


def suggestions(chat_id: int, course: str | None) -> str | None:
    if not supports(course):
        return None
    rules = COURSE_RULES[course]
    by_group = db.hours_by_group(chat_id, course)
    total = sum(min(by_group.get(group, 0.0), cap) for group, (_, cap) in rules["groups"].items())
    if total >= rules["total"]:
        return None
    lines = ["Onde ainda dá para ganhar horas:"]
    for group, (name, cap) in rules["groups"].items():
        room = cap - min(by_group.get(group, 0.0), cap)
        if room > 0:
            lines.append(f"Grupo {ROMAN[group]} - {name} (cabem mais {fmt(room)}h): {rules['hints'][group]}")
    return "\n".join(lines)


def summary(chat_id: int, course: str | None) -> str | None:
    if not supports(course):
        return None
    by_group = db.hours_by_group(chat_id, course)
    if not by_group:
        return None
    rules = COURSE_RULES[course]
    lines, total = [], 0.0
    for group, (name, cap) in rules["groups"].items():
        registered = by_group.get(group, 0.0)
        counted = min(registered, cap)
        total += counted
        line = f"Grupo {ROMAN[group]} - {name}: {fmt(counted)}/{cap}h"
        if registered > cap:
            line += f" (registradas {fmt(registered)}h, acima do teto do grupo)"
        lines.append(line)
    required = rules["total"]
    lines.append(f"Total: {fmt(min(total, required))}/{required}h" + (" (concluído)" if total >= required else f" (faltam {fmt(required - total)}h)"))
    return "\n".join(lines)
