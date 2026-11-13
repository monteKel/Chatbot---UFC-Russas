#Imports
import logging
import html
import os
import re
import asyncio
import chromadb
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, ContextTypes, filters
from telegram.constants import ChatAction
from telegram.error import BadRequest, TelegramError
from google import genai
from google.genai import types
from google.genai.errors import APIError

import db
import fontes
import horas
import llm

#Load the .env file to load the tokens
load_dotenv()
#Config the logger
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)
# httpx logs every request URL at INFO, and Telegram URLs embed the bot token.
logging.getLogger("httpx").setLevel(logging.WARNING)

#Keys
TELEGRAM_BOT_TOKEN = os.environ['TELEGRAM_BOT_TOKEN']
GEMINI_API_KEY = os.environ['GEMINI_API_KEY']
EMBEDDING_MODEL = os.environ.get('EMBEDDING_MODEL', 'gemini-embedding-001')
CHROMA_PATH = os.environ.get('CHROMA_PATH', 'chroma_db')
HISTORY_LIMIT = int(os.environ.get('HISTORY_LIMIT', 6))
SYSTEM_INSTRUCTION = (
    os.environ.get('PROMPT_GENAI', '')
    + "\n\nO que este bot sabe fazer: o aluno pode mandar aqui no chat o certificado ou declaração em PDF ou foto, "
    "ou contar uma atividade que já fez (ex.: \"fiz um curso de 40h\"), e o bot calcula as horas complementares pelo "
    "regulamento do curso e pede confirmação antes de salvar no registro pessoal do aluno. O comando /horas mostra e "
    "permite apagar as horas registradas; /comoentregar explica como entregar oficialmente na coordenação; /faq tem "
    "as dúvidas mais comuns. Esse registro é só um acompanhamento pessoal: a validação oficial continua sendo da "
    "coordenação. Quando o aluno quiser registrar horas ou mandar um certificado, diga que ele pode enviar o arquivo "
    "aqui mesmo; nunca diga que o bot não recebe documentos."
    "\n\nRegras adicionais: Responda sempre em português do Brasil, em texto simples, sem tabelas. "
    "Se o curso do aluno não estiver registrado e a resposta depender do curso, pergunte qual é o curso dele. "
    "Você não tem acesso à internet: use somente o contexto fornecido. Nunca invente exemplos, números, "
    "limites de horas ou regras que não estejam escritos no contexto; se o contexto não trouxer exemplos de uma "
    "categoria, diga que o documento não lista exemplos para ela. Atividades complementares, extensão "
    "(curricularização da extensão), estágio e TCC são componentes diferentes, com cargas horárias diferentes: "
    "nunca use a carga horária de um como se fosse de outro. Se a informação não estiver no contexto, "
    "diga que não encontrou nos documentos oficiais e oriente o aluno a procurar a coordenação do curso. "
    "Comandos de contato das coordenações: /coordcc (Ciência da Computação), /coordes (Engenharia de Software), "
    "/coordep (Engenharia de Produção), /coordec (Engenharia Civil), /coordem (Engenharia Mecânica). "
    "Cada trecho do contexto começa com [Fonte: título do documento]. Ao final da resposta, em uma linha "
    "começando com \"Fonte:\", cite apenas os títulos dos documentos que você realmente usou, exatamente como "
    "aparecem no contexto. Não coloque citações no meio do texto, só nessa linha final. Se não usou nenhum "
    "trecho do contexto, não escreva a linha de fonte."
)
TELEGRAM_MAX_LEN = 4000
MAX_CERTIFICATE_BYTES = 10 * 1024 * 1024
MAX_VOICE_SECONDS = 180
CERTIFICATE_TIMEOUT = 300
# Text messages may need course detection + certificate-style extraction (which waits out the
# Groq token window) + the answer itself.
MESSAGE_TIMEOUT = 90
EMBEDDING_TIMEOUT_MS = 15_000
# Keeps prompts under Groq's 8K tokens/minute free limit even after several long answers.
MAX_HISTORY_CHARS = 4000
MAX_HISTORY_MESSAGE_CHARS = 1200
MAX_LISTED_ACTIVITIES = 30
# Certificates are analysed one at a time for everyone, so one student can't queue an unbounded batch.
MAX_CERTIFICATES_IN_FLIGHT = 5
_certificates_in_flight: dict[int, int] = {}
EMPTY_SOURCE_LINE = re.compile(r"\n+\W*fonte\W*:?\W*\(?\s*(nenhum|nenhuma|n/a|-)[^\n]*\s*$", re.IGNORECASE)
ERROR_REPLY = "Desculpe, tive um problema para gerar a resposta agora. Tente novamente em instantes."
logger.info("Prompt carregado: %r", SYSTEM_INSTRUCTION)
logger.info("Provedores de geração: %s", [p["name"] for p in llm.get_providers()])

#Gemini (embeddings only)
gemini_client = genai.Client(api_key=GEMINI_API_KEY, http_options=types.HttpOptions(timeout=EMBEDDING_TIMEOUT_MS))
awaiting_feedback: set[int] = set()

#RAG setup
chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
rag_collection = chroma_client.get_or_create_collection("ufc_russas_docs")

COURSE_TO_PREFIX = {
    "Ciência da Computação": "cc",
    "Engenharia de Software": "es",
    "Engenharia de Produção": "ep",
    "Engenharia Civil": "ec",
    "Engenharia Mecânica": "em",
}

COMMANDS_TEXT = (
    "*Comandos disponíveis:*\n"
    "/start - Mensagem de boas-vindas\n"
    "/help - Mostra a lista de comandos\n"
    "/faq - Perguntas frequentes\n"
    "/feedback - Envia um feedback anônimo\n"
    "/horas - Mostra (e permite apagar) suas horas complementares registradas\n"
    "/comoentregar - Passo a passo para entregar suas horas complementares\n"
    "/coordcc - Contato da coordenação de Ciência da Computação\n"
    "/coordes - Contato da coordenação de Engenharia de Software\n"
    "/coordep - Contato da coordenação de Engenharia de Produção\n"
    "/coordem - Contato da coordenação de Engenharia Mecânica\n"
    "/coordec - Contato da coordenação de Engenharia Civil\n"
    "/reset - Reinicia a memória da nossa conversa"
)

#Functions
async def retrieve_context(question: str, course_prefix: str | None, n_results: int = 10) -> list[tuple[str, str]] | None:
    try:
        embed_response = await gemini_client.aio.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=[question],
            config=types.EmbedContentConfig(task_type="RETRIEVAL_QUERY"),
        )
        query_embedding = embed_response.embeddings[0].values
        results = rag_collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            where={"course": course_prefix} if course_prefix else None,
        )
        documents = (results.get("documents") or [[]])[0]
        metadatas = (results.get("metadatas") or [[]])[0]
        return [
            (text, fontes.doc_title((metadata or {}).get("filename")))
            for text, metadata in zip(documents, metadatas)
        ]
    except APIError as e:
        logger.warning("Falha ao buscar contexto no RAG: %s", e)
        return None
    except Exception:
        # Network errors, timeouts or Chroma failures: answer without documents instead of crashing.
        logger.exception("Falha inesperada ao buscar contexto no RAG")
        return None


def to_telegram_html(text: str) -> str:
    text = html.escape(text, quote=False)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text, flags=re.S)
    text = re.sub(r"^#{1,6}\s*(.+)$", r"<b>\1</b>", text, flags=re.M)
    text = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", text)
    return text.replace("**", "")


async def send_formatted(update: Update, text: str) -> None:
    for part in split_message(text):
        try:
            await update.message.reply_text(to_telegram_html(part), parse_mode="HTML")
        except BadRequest:
            await update.message.reply_text(re.sub(r"\*\*|`|^#{1,6}\s*", "", part, flags=re.M))


def split_message(text: str, limit: int = TELEGRAM_MAX_LEN) -> list[str]:
    parts = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut <= 0:
            cut = limit
        parts.append(text[:cut])
        text = text[cut:].lstrip("\n")
    if text:
        parts.append(text)
    return parts


def _bounded_history(chat_id: int) -> list[tuple[str, str]]:
    """Most recent history that fits the size budget, with long messages shortened."""
    kept, total = [], 0
    for role, content in reversed(db.get_history(chat_id, limit=HISTORY_LIMIT)):
        if len(content) > MAX_HISTORY_MESSAGE_CHARS:
            content = content[:MAX_HISTORY_MESSAGE_CHARS] + " […]"
        if total + len(content) > MAX_HISTORY_CHARS:
            break
        kept.append((role, content))
        total += len(content)
    return list(reversed(kept))


def build_messages(chat_id: int, user_text: str, chunks: list[tuple[str, str]] | None, course: str | None) -> list[dict]:
    system = SYSTEM_INSTRUCTION
    if course:
        system += f"\n\nCurso registrado do aluno: {course}."
    hours_summary = horas.summary(chat_id, course)
    if hours_summary:
        system += (
            "\n\nHoras complementares que o próprio aluno registrou no bot (estimativa, ainda não validada "
            f"pela coordenação; os tetos de cada grupo já foram aplicados):\n{hours_summary}"
        )
    if "hora" in llm.normalize(user_text):
        hours_suggestions = horas.suggestions(chat_id, course)
        if hours_suggestions:
            system += f"\n\n{hours_suggestions}"
    messages = [{"role": "system", "content": system}]
    for role, content in _bounded_history(chat_id):
        messages.append({"role": "assistant" if role == "model" else "user", "content": content})

    if chunks is None:
        context_block = "(Não foi possível consultar os documentos oficiais agora. Não invente informações.)"
    elif not chunks:
        context_block = "(Nenhum trecho relevante encontrado nos documentos oficiais.)"
    else:
        context_block = "\n\n---\n\n".join(f"[Fonte: {title}]\n{text}" for text, title in chunks)
    messages.append({
        "role": "user",
        "content": f"Contexto de documentos oficiais da UFC Russas:\n{context_block}\n\nPergunta do aluno: {user_text}",
    })
    return messages


async def resolve_course(chat_id: int, user_text: str) -> str | None:
    course = db.get_course(chat_id)
    if llm.mentions_course(user_text):
        detected = await llm.detect_course(user_text, course)
        if detected and detected != course:
            db.set_course(chat_id, detected)
            logger.info("Curso de %s registrado: %s", chat_id, detected)
            course = detected
    return course


async def generate_reply(chat_id: int, user_text: str, course: str | None) -> tuple[str | None, str | None]:
    search_course = llm.course_named_in(user_text) or course
    course_prefix = COURSE_TO_PREFIX.get(search_course) if search_course else None
    retrieved_chunks = await retrieve_context(user_text, course_prefix)
    messages = build_messages(chat_id, user_text, retrieved_chunks, course)
    reply_text, provider = await llm.answer(messages)
    if reply_text:
        reply_text = EMPTY_SOURCE_LINE.sub("", reply_text).rstrip()
    return reply_text, provider


class TemporaryMessage:
    """Status message ("Digitando...") that is deleted right before the real reply is sent."""

    def __init__(self, message: Message | None):
        self._message = message

    @classmethod
    async def send(cls, update: Update, text: str) -> "TemporaryMessage":
        try:
            return cls(await update.message.reply_text(text))
        except TelegramError:
            logger.warning("Não consegui enviar a mensagem temporária para %s", update.effective_chat.id)
            return cls(None)

    async def remove(self) -> None:
        message, self._message = self._message, None
        if message is None:
            return
        try:
            await message.delete()
        except TelegramError:
            logger.info("Não consegui apagar a mensagem temporária %s", message.message_id)


#Application Handlers
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await process_text(update, context, update.message.text)


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    audio = update.message.voice or update.message.audio
    if audio.duration and audio.duration > MAX_VOICE_SECONDS:
        await update.message.reply_text("Esse áudio é longo demais (máximo 3 minutos). Tente mandar um áudio mais curto ou escrever.")
        return
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    try:
        telegram_file = await audio.get_file()
        data = bytes(await telegram_file.download_as_bytearray())
    except Exception:
        logger.exception("Falha ao baixar áudio de %s", update.effective_chat.id)
        data = None
    text = await llm.transcribe(data, getattr(audio, "file_name", None) or "audio.ogg") if data else None
    if not text:
        await update.message.reply_text("Não consegui entender esse áudio. Pode tentar de novo ou escrever sua pergunta?")
        return
    await process_text(update, context, text)


async def process_text(update: Update, context: ContextTypes.DEFAULT_TYPE, user_text: str) -> None:
    chat_id = update.effective_chat.id

    if chat_id in awaiting_feedback:
        awaiting_feedback.discard(chat_id)
        logger.info("Feedback anônimo recebido")
        db.save_feedback(user_text)
        await update.message.reply_text("Obrigado pelo feedback!")
        return

    status = await TemporaryMessage.send(update, "Digitando...")
    reply_text, provider, course, activities = None, None, None, None
    try:
        async with asyncio.timeout(MESSAGE_TIMEOUT):
            course = await resolve_course(chat_id, user_text)
            if horas.supports(course) and horas.declares_activity(user_text):
                activities = await horas.extract(user_text, course)
            if not activities:
                reply_text, provider = await generate_reply(chat_id, user_text, course)
    except TimeoutError:
        logger.error("Tempo esgotado gerando resposta para %s", chat_id)
    except Exception:
        logger.exception("Erro inesperado respondendo %s", chat_id)
        activities = None
    finally:
        await status.remove()

    if activities:
        await send_hours_confirmation(update, course, activities, "texto", None, user_text)
        return
    if reply_text is None:
        logger.error("Todos os provedores falharam para %s", chat_id)
        reply_text = ERROR_REPLY
    else:
        logger.info("Resposta para %s gerada por %s", chat_id, provider)
        db.save_message(chat_id, "user", user_text)
        db.save_message(chat_id, "model", reply_text)
    await send_formatted(update, reply_text)


async def send_hours_confirmation(
    update: Update, course: str, activities: list, source: str, file_id: str | None, history_label: str
) -> None:
    chat_id = update.effective_chat.id
    complete = [a for a in activities if a.credited_hours is not None]
    incomplete = [a for a in activities if a.credited_hours is None]
    sections = []
    if complete:
        sections.append("Encontrei isto:\n\n" + "\n\n".join(horas.describe(a, course) for a in complete))
    if incomplete:
        sections.append(
            "Não consegui calcular as horas destas atividades:\n\n"
            + "\n\n".join(horas.describe(a, course) for a in incomplete)
            + "\n\nMe mande a informação que faltou (por exemplo: \"fiz monitoria por 16 semanas, 12h por semana\") "
            "que eu tento de novo."
        )
    keyboard = None
    if complete:
        sections.append("Posso salvar no seu registro de horas? (É uma estimativa: quem valida oficialmente é a coordenação.)")
        token = horas.add_pending(chat_id, complete, source, file_id, course)
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("Salvar", callback_data=f"hrs:ok:{token}"),
            InlineKeyboardButton("Cancelar", callback_data=f"hrs:no:{token}"),
        ]])
    text = "\n\n".join(sections)
    db.save_message(chat_id, "user", history_label)
    db.save_message(chat_id, "model", text)
    parts = split_message(text)
    for part in parts[:-1]:
        await update.message.reply_text(part)
    await update.message.reply_text(parts[-1], reply_markup=keyboard)


async def handle_certificate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    chat_id = update.effective_chat.id
    course = db.get_course(chat_id)
    if not course:
        await message.reply_text(
            "Antes de registrar horas, me diga qual é o seu curso (por exemplo: \"sou de Engenharia Civil\") "
            "e depois mande o certificado de novo."
        )
        return
    if not horas.supports(course):
        await message.reply_text(
            f"Ainda não tenho o regulamento de atividades complementares de {course}, então não consigo "
            "calcular as horas. Procure a coordenação do seu curso."
        )
        return

    if message.photo:
        attachment, is_pdf = message.photo[-1], False
    else:
        attachment = message.document
        is_pdf = attachment.mime_type == "application/pdf"
    if attachment.file_size and attachment.file_size > MAX_CERTIFICATE_BYTES:
        await message.reply_text("Esse arquivo é grande demais (máximo 10 MB). Tente mandar uma versão menor.")
        return

    if _certificates_in_flight.get(chat_id, 0) >= MAX_CERTIFICATES_IN_FLIGHT:
        await message.reply_text(
            f"Já estou analisando {MAX_CERTIFICATES_IN_FLIGHT} certificados seus. Espere eu terminar esses "
            "e depois mande os próximos."
        )
        return
    _certificates_in_flight[chat_id] = _certificates_in_flight.get(chat_id, 0) + 1
    try:
        await _analyze_certificate(update, message, chat_id, course, attachment, is_pdf)
    finally:
        _certificates_in_flight[chat_id] -= 1
        if not _certificates_in_flight[chat_id]:
            del _certificates_in_flight[chat_id]


async def _analyze_certificate(update: Update, message, chat_id: int, course: str, attachment, is_pdf: bool) -> None:
    file_name = getattr(attachment, "file_name", None)
    label = f"\"{file_name}\"" if file_name else "sua foto"
    if horas.extraction_busy():
        status = await TemporaryMessage.send(update, f"Recebi {label}! Tem outros certificados na fila, já já eu analiso este.")
    else:
        status = await TemporaryMessage.send(update, f"Analisando {label}...")

    async def reply(text: str) -> None:
        await status.remove()
        await message.reply_text(text)

    try:
        try:
            telegram_file = await attachment.get_file()
            data = bytes(await telegram_file.download_as_bytearray())
            text = await asyncio.to_thread(horas.read_pdf if is_pdf else horas.read_image, data)
        except Exception:
            logger.exception("Falha ao ler certificado de %s", chat_id)
            await reply("Não consegui abrir esse arquivo. Tente mandar de novo, de preferência em PDF.")
            return
        if message.caption:
            text = f"{text}\n\nMensagem do aluno: {message.caption}"
        if not horas.is_readable(text):
            await reply("Não consegui ler o texto desse arquivo. Tente uma foto mais nítida e reta, ou mande o PDF do certificado.")
            return

        activities = None
        try:
            async with asyncio.timeout(CERTIFICATE_TIMEOUT):
                activities = await horas.extract(text, course)
        except TimeoutError:
            logger.error("Tempo esgotado extraindo certificado de %s", chat_id)
        if activities is None:
            await reply(f"Desculpe, não consegui analisar {label} agora. Pode mandar de novo daqui a pouco?")
            return
        if not activities:
            await reply(
                f"Não identifiquei em {label} uma atividade complementar que se encaixe nas regras do seu curso. "
                "Se achar que é um erro, me diga qual foi a atividade e a carga horária."
            )
            return
        await status.remove()
        await send_hours_confirmation(
            update, course, activities, "pdf" if is_pdf else "imagem", attachment.file_id,
            f"[Enviei um certificado: {file_name or 'foto'}]",
        )
    finally:
        await status.remove()


def hours_listing(chat_id: int) -> tuple[str, InlineKeyboardMarkup | None]:
    course = db.get_course(chat_id)
    entries = db.list_complementary_hours(chat_id)
    hints = horas.suggestions(chat_id, course)
    if not entries:
        text = "Você ainda não registrou nenhuma atividade. Mande um certificado em PDF ou foto, ou me conte uma atividade que você fez."
        return (f"{text}\n\n{hints}" if hints else text), None
    shown = entries[-MAX_LISTED_ACTIVITIES:]
    first_number = len(entries) - len(shown) + 1
    lines = ["Atividades registradas:"]
    if len(entries) > len(shown):
        lines[0] = f"Atividades registradas (mostrando as {len(shown)} mais recentes de {len(entries)}):"
    buttons = []
    for number, (entry_id, group, name, hours, entry_course) in enumerate(shown, start=first_number):
        note = f" [registrada como {entry_course}, não conta no total]" if entry_course and entry_course != course else ""
        lines.append(f"{number}. {name[:60]} (Grupo {horas.ROMAN.get(group, group)}): {horas.fmt(hours)}h{note}")
        buttons.append([InlineKeyboardButton(f"Apagar {number}. {name[:30]}", callback_data=f"hrs:del:{entry_id}")])
    footer = []
    summary = horas.summary(chat_id, course)
    if summary:
        footer.append(f"\nTotal por grupo (estimativa; a validação oficial é da coordenação):\n{summary}")
    if hints:
        footer.append(f"\n{hints}")
    footer.append("\nPara saber como entregar na coordenação, use /comoentregar.")
    text = "\n".join(lines + footer)
    if len(text) > TELEGRAM_MAX_LEN and hints:
        footer.remove(f"\n{hints}")
        text = "\n".join(lines + footer)
    return text[:TELEGRAM_MAX_LEN], InlineKeyboardMarkup(buttons)


async def _edit(query, text: str | None = None, reply_markup=None) -> None:
    """Edits the clicked message, ignoring Telegram's "message is not modified" on repeated clicks."""
    try:
        if text is None:
            await query.edit_message_reply_markup(reply_markup=reply_markup)
        else:
            await query.edit_message_text(text, reply_markup=reply_markup)
    except BadRequest as error:
        if "not modified" not in str(error).lower():
            raise


async def hours_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text, keyboard = hours_listing(update.effective_chat.id)
    await update.message.reply_text(text, reply_markup=keyboard)


async def submission_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    course = db.get_course(update.effective_chat.id)
    if not course:
        text = "Me diga qual é o seu curso (por exemplo: \"sou de Engenharia de Software\") e use /comoentregar de novo."
    elif not horas.supports(course):
        text = f"Ainda não tenho o regulamento de atividades complementares de {course}. Procure a coordenação do seu curso."
    else:
        text = horas.COURSE_RULES[course]["submission"]
    await update.message.reply_text(text)


async def handle_hours_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    try:
        await query.answer()
    except BadRequest:
        # Telegram expires a click after ~15s; the click itself is still valid, so keep going.
        logger.info("Callback de %s respondido fora do prazo do Telegram", update.effective_chat.id)
    _, action, token = query.data.split(":", 2)
    chat_id = update.effective_chat.id
    if action == "del":
        if token.isdigit():
            db.delete_complementary_hours(chat_id, int(token))
        text, keyboard = hours_listing(chat_id)
        await _edit(query, text, keyboard)
        return
    pending = horas.pop_pending(token, chat_id)
    if pending is None:
        # Already handled (double click) or lost in a restart: just drop the buttons.
        await _edit(query, reply_markup=None)
        if query.message.text and not query.message.text.endswith(("Salvo!", "Cancelado, nada foi salvo.")):
            await query.message.reply_text("Esse registro expirou. Mande o certificado de novo.")
        return
    names = ", ".join(a.name for a in pending.activities)
    if action != "ok":
        db.save_message(chat_id, "user", "[Cliquei em Cancelar]")
        db.save_message(chat_id, "model", f"Cancelado, não salvei: {names}.")
        await _edit(query, f"{query.message.text}\n\nCancelado, nada foi salvo.")
        return
    horas.save(pending)
    db.save_message(chat_id, "user", "[Cliquei em Salvar]")
    db.save_message(chat_id, "model", f"Salvei no seu registro de horas: {names}.")
    await _edit(query, f"{query.message.text}\n\nSalvo!")
    summary = horas.summary(chat_id, db.get_course(chat_id))
    if summary:
        await query.message.reply_text(
            f"Suas horas registradas até agora (estimativa; a validação oficial é da coordenação):\n\n{summary}"
        )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "👋 *Olá! Eu sou o assistente virtual da UFC Russas.*\n\n"
        "Posso te ajudar com dúvidas acadêmicas, especialmente sobre horas complementares.\n\n"
        "Também posso registrar suas horas complementares: me mande o certificado em PDF ou foto "
        "(ou me conte a atividade que você fez) e eu calculo as horas pelo regulamento do seu curso.\n\n"
        f"{COMMANDS_TEXT}\n\n"
        "Fora isso, é só me mandar sua pergunta diretamente!"
    )
    await update.message.reply_text(text, parse_mode="Markdown")
async def handle_unsupported(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Desculpe, só consigo entender mensagens de texto, áudios e certificados em PDF ou foto."
    )
async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    db.clear_history(chat_id)
    await update.message.reply_text("Memória da conversa reiniciada.")
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "*Assistente Virtual - UFC Russas*\n\n"
        "Posso te ajudar com dúvidas acadêmicas, especialmente sobre horas complementares.\n\n"
        "Para registrar horas, mande o certificado em PDF ou foto, ou me conte a atividade que você fez. "
        "Para consultar, é só perguntar \"quantas horas eu já tenho?\".\n\n"
        f"{COMMANDS_TEXT}\n\n"
        "Fora isso, é só me mandar sua pergunta diretamente."
    )
    await update.message.reply_text(text, parse_mode="Markdown")
async def faq(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "*Perguntas Frequentes*\n\n"
        "*Quantas horas complementares eu preciso?*\n"
        "Ciência da Computação: 192h. Engenharia de Software: 288h. Engenharia Civil: 60h. "
        "Engenharia de Produção: 60h. Engenharia Mecânica: confirme com a coordenação (/coordem).\n\n"
        "*Como registro e acompanho minhas horas aqui?*\n"
        "Mande o certificado em PDF ou foto, ou me conte a atividade (ex.: \"fiz um curso de 40h\"). "
        "Eu calculo pelo regulamento do seu curso e salvo depois da sua confirmação. Use /horas para ver o total.\n\n"
        "*Como entrego as horas para a coordenação?*\n"
        "Use /comoentregar para ver o passo a passo do seu curso.\n\n"
        "*Perdi uma prova. Tenho direito a segunda chamada?*\n"
        "Sim, desde que você peça por escrito em até 3 dias úteis depois da prova (Regimento Geral, art. 110, § 3º), "
        "usando o requerimento de segunda chamada do Campus de Russas.\n\n"
        "*Quantas faltas posso ter?*\n"
        "A frequência mínima é de 75%. Duas reprovações por falta na mesma disciplina, ou quatro no total, "
        "bloqueiam a matrícula do semestre seguinte. Depois de assinar o termo de compromisso para desbloquear, "
        "mais uma reprovação por falta cancela a matrícula. Isso não vale para TCC/monografia, estágio e projeto final "
        "(Resolução 12/CEPE/2008).\n\n"
        "*Posso trancar o curso?*\n"
        "O trancamento total vale por doença, mudança de cidade, trabalho com horário incompatível ou serviço militar, "
        "com comprovação. Peça na coordenação (em caso de doença, na perícia da UFC) durante a matrícula ou em até "
        "15 dias depois do fato. No primeiro semestre do curso, só por doença ou serviço militar "
        "(Portarias 47 e 48/2019 da Prograd).\n\n"
        "*Posso aproveitar disciplinas que já cursei?*\n"
        "Sim, pedindo aproveitamento de estudos na coordenação, no período do calendário, com histórico e planos "
        "de ensino. Disciplinas feitas antes de entrar no curso devem ser pedidas até o semestre seguinte ao seu "
        "ingresso (Portaria 103/2019 da Prograd).\n\n"
        "*Onde vejo notas, histórico e atestado de matrícula?*\n"
        "No SIGAA, onde também é feita a matrícula.\n\n"
        "*Como crio meu e-mail institucional?*\n"
        "Depois do cadastro no SIGAA, acesse webmail.ufc.br e crie sua conta @alu.ufc.br.\n\n"
        "*Onde encontro apoio psicológico?*\n"
        "A Assistência Estudantil do Campus de Russas atende por agendamento: (88) 3411-9235 "
        "ou pelo Instagram @ae.ufcrussas.\n\n"
        "*Como consigo bolsas e auxílios?*\n"
        "Os auxílios da PRAE exigem o Cadastro Socioeconômico; os editais (como a Bolsa de Iniciação Acadêmica) "
        "saem no site da PRAE. Bolsas como PET e monitoria são divulgadas pela coordenação do curso.\n\n"
        "Não achou sua dúvida aqui? Pode me perguntar diretamente!"
    )
    await update.message.reply_text(text, parse_mode="Markdown")
async def coordcc(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "*Contato da Coordenação do Curso de Ciência da Computação:*\n\n"
        "Coordenador: Prof. Dr. Reuber Regis de Melo\n"
        "e-mail: reuber.regis@ufc.br\n"
        "Vice-coordenadora:  Profa. Dra. Jacilane de Holanda Rabelo\n"
        "e-mail: jacilane.rabelo@ufc.br\n"
        "Tel: (88) 3411-9209\n"
        "Secretário de Curso: Igor de Sousa da Silva\n"
        "e-mail: coordcc.russas@ufc.br\n"
        "Tel: (88) 3411-9216\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown")
async def coordes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "*Contato da Coordenação do Curso de Engenharia de Software:*\n\n"
        "Coordenador: Prof. Dr. Anderson Feitoza Leitão Maia\n"
        "e-mail: andersonflmaia@ufc.br\n"
        "Tel: (88) 3411-9208\n"
        "Vice-Coordenador: Cenez Araujo de Rezende\n"
        "e-mail: cenezaraujo@ufc.br\n"
        "Secretária do Curso : Isabelle Ferreira Xavier\n"
        "e-mail: coord.software@ufc.br\n"
        "Tel:(88) 3411-9217\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown")
async def coordep(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "*Contato da Coordenação do Curso de Engenharia de Produção:*\n\n"
        "Coordenador:  Prof. Dr. Pedro Helton Magalhães Pinheiro\n"
        "e-mail: pedrohelton@ufc.br\n"
        "Vice-Coordenador: Prof. Dr. Dmontier Pinheiro Aragão Junior\n"
        "e-mail: dmontier.aragao@ufc.br\n"
        "Secretário de Curso: Edí Carlos Rebouças de Oliveira\n"
        "e-mail: producaorussas@ufc.br\n"
        "Tel: (88) 3411-9215\n"

    )
    await update.message.reply_text(text, parse_mode="Markdown")
async def coordem(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "*Contato da Coordenação do Curso de Engenharia Mecânica:*\n\n"
        "Coordenador: Prof. Dr. George Luiz Gomes de Oliveira\n"
        "e-mail: georgeluiz@ufc.br\n"
        "Vice-Coordenador: Prof. Dr. Edvan Cordeiro de Miranda\n"
        "e-mail: edvan@ufc.br\n"
        "Tel: (88) 3411-9212\n"
        "Secretário de Curso: Francisco Elvis Sombra Rodrigues\n"
        "e-mail: elvissombra@ufc.br\n"
        "e-mail: mecanicarussas@ufc.br\n"
        "Tel: (88) 3411-9214\n"

    )
    await update.message.reply_text(text, parse_mode="Markdown")
async def coordec(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "*Contato da Coordenação do Curso de Engenharia Civil:*\n\n"
        "Coordenador: Prof. Dr. Jerfson Moura Lima\n"
        "e-mail: jerfson.lima@ufc.br\n"
        "Vice-Coordenadora: Prof. Dra. Mylene de Melo Vieira\n"
        "e-mail: mylene.melo@ufc.br\n"
        "Tel: (88) 3411-9211\n"
        "Secretária de Curso: Hyngla Emanuelle de Oliveira Gonsalves\n"
        "e-mail: hynglamanu@ufc.br\n"
        "Tel: (88) 3411-9213\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown")
async def feedback_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    awaiting_feedback.add(chat_id)
    await update.message.reply_text(
        "Pode mandar seu feedback na próxima mensagem. Ele é salvo de forma anônima, sem nenhuma "
        "informação que identifique você."
    )

async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Não conheço esse comando. Use /help para ver os comandos disponíveis.")


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Erro não tratado", exc_info=context.error)
    message = update.effective_message if isinstance(update, Update) else None
    if message is not None:
        try:
            await message.reply_text(ERROR_REPLY)
        except TelegramError:
            pass


#Main
COMMANDS = {
    "start": start,
    "reset": reset,
    "help": help_command,
    "faq": faq,
    "feedback": feedback_command,
    "horas": hours_command,
    "comoentregar": submission_command,
    "coordcc": coordcc,
    "coordes": coordes,
    "coordep": coordep,
    "coordem": coordem,
    "coordec": coordec,
}


def build_application() -> Application:
    # Concurrent updates so one student's slow request (e.g. a queued certificate) doesn't block
    # everyone else or make button clicks expire. Everything still runs on one event loop thread,
    # so the shared SQLite connection stays safe.
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).concurrent_updates(True).build()

    # Only new messages in private chats: edited messages have no update.message, and in a group the
    # chat id (used as the student's identity) would be shared by everyone.
    new_private = filters.UpdateType.MESSAGE & filters.ChatType.PRIVATE
    for command, callback in COMMANDS.items():
        application.add_handler(CommandHandler(command, callback, filters=new_private))
    application.add_handler(MessageHandler(new_private & filters.COMMAND, unknown_command))
    application.add_handler(MessageHandler(new_private & filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(
        new_private & (filters.PHOTO | filters.Document.PDF | filters.Document.IMAGE), handle_certificate))
    application.add_handler(CallbackQueryHandler(handle_hours_callback, pattern=r"^hrs:"))
    application.add_handler(MessageHandler(new_private & (filters.VOICE | filters.AUDIO), handle_voice))
    application.add_handler(MessageHandler(new_private & ~filters.TEXT, handle_unsupported))
    application.add_error_handler(on_error)
    return application


def main() -> None:
    db.init_db()
    build_application().run_polling()


if __name__ == "__main__":
    main()