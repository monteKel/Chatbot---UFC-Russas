#Imports
import logging
import os
import asyncio
import chromadb
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, ContextTypes, filters
from telegram.constants import ChatAction
from google import genai
from google.genai import types
from google.genai.errors import APIError

import db
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

#Keys
TELEGRAM_BOT_TOKEN = os.environ['TELEGRAM_BOT_TOKEN']
GEMINI_API_KEY = os.environ['GEMINI_API_KEY']
EMBEDDING_MODEL = os.environ.get('EMBEDDING_MODEL', 'gemini-embedding-001')
CHROMA_PATH = os.environ.get('CHROMA_PATH', 'chroma_db')
HISTORY_LIMIT = int(os.environ.get('HISTORY_LIMIT', 6))
SYSTEM_INSTRUCTION = (
    os.environ.get('PROMPT_GENAI', '')
    + "\n\nRegras adicionais: Responda sempre em português do Brasil, em texto simples, sem tabelas. "
    "Se o curso do aluno não estiver registrado e a resposta depender do curso, pergunte qual é o curso dele. "
    "Você não tem acesso à internet: use somente o contexto fornecido. Nunca invente exemplos, números, "
    "limites de horas ou regras que não estejam escritos no contexto; se o contexto não trouxer exemplos de uma "
    "categoria, diga que o documento não lista exemplos para ela. Atividades complementares, extensão "
    "(curricularização da extensão), estágio e TCC são componentes diferentes, com cargas horárias diferentes: "
    "nunca use a carga horária de um como se fosse de outro. Se a informação não estiver no contexto, "
    "diga que não encontrou nos documentos oficiais e oriente o aluno a procurar a coordenação do curso. "
    "Comandos de contato das coordenações: /coordcc (Ciência da Computação), /coordes (Engenharia de Software), "
    "/coordep (Engenharia de Produção), /coordec (Engenharia Civil), /coordem (Engenharia Mecânica)."
)
TELEGRAM_MAX_LEN = 4000
MAX_CERTIFICATE_BYTES = 10 * 1024 * 1024
ERROR_REPLY = "Desculpe, tive um problema para gerar a resposta agora. Tente novamente em instantes."
logger.info("Prompt carregado: %r", SYSTEM_INSTRUCTION)
logger.info("Provedores de geração: %s", [p["name"] for p in llm.get_providers()])

#Gemini (embeddings only)
gemini_client = genai.Client(api_key=GEMINI_API_KEY)
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
    "/coordcc - Contato da coordenação de Ciência da Computação\n"
    "/coordes - Contato da coordenação de Engenharia de Software\n"
    "/coordep - Contato da coordenação de Engenharia de Produção\n"
    "/coordem - Contato da coordenação de Engenharia Mecânica\n"
    "/coordec - Contato da coordenação de Engenharia Civil\n"
    "/reset - Reinicia a memória da nossa conversa"
)

#Functions
async def retrieve_context(question: str, course_prefix: str | None, n_results: int = 10) -> list[str] | None:
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
        documents = results.get("documents") or []
        return documents[0] if documents else []
    except APIError as e:
        logger.warning("Falha ao buscar contexto no RAG: %s", e)
        return None


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


def build_messages(chat_id: int, user_text: str, chunks: list[str] | None, course: str | None) -> list[dict]:
    system = SYSTEM_INSTRUCTION
    if course:
        system += f"\n\nCurso registrado do aluno: {course}."
    hours_summary = horas.summary(chat_id, course)
    if hours_summary:
        system += (
            "\n\nHoras complementares que o próprio aluno registrou no bot (estimativa, ainda não validada "
            f"pela coordenação; os tetos de cada grupo já foram aplicados):\n{hours_summary}"
        )
    messages = [{"role": "system", "content": system}]
    for role, content in db.get_history(chat_id, limit=HISTORY_LIMIT):
        messages.append({"role": "assistant" if role == "model" else "user", "content": content})

    if chunks is None:
        context_block = "(Não foi possível consultar os documentos oficiais agora. Não invente informações.)"
    elif not chunks:
        context_block = "(Nenhum trecho relevante encontrado nos documentos oficiais.)"
    else:
        context_block = "\n\n---\n\n".join(chunks)
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
    return await llm.answer(messages)


#Application Handlers
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_text = update.message.text
    chat_id = update.effective_chat.id

    if chat_id in awaiting_feedback:
        awaiting_feedback.discard(chat_id)
        logger.info("Feedback recebido de %s: %s", chat_id, user_text)
        db.save_feedback(chat_id, user_text)
        await update.message.reply_text("Obrigado pelo feedback!")
        return

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    reply_text, provider = None, None
    try:
        async with asyncio.timeout(50):
            course = await resolve_course(chat_id, user_text)
            if horas.supports(course) and horas.declares_activity(user_text):
                activities = await horas.extract(user_text, course)
                if activities:
                    await send_hours_confirmation(update, course, activities, "texto", None)
                    return
            reply_text, provider = await generate_reply(chat_id, user_text, course)
    except TimeoutError:
        logger.error("Tempo esgotado gerando resposta para %s", chat_id)

    if reply_text is None:
        logger.error("Todos os provedores falharam para %s", chat_id)
        reply_text = ERROR_REPLY
    else:
        logger.info("Resposta para %s gerada por %s", chat_id, provider)
        db.save_message(chat_id, "user", user_text)
        db.save_message(chat_id, "model", reply_text)
    for part in split_message(reply_text):
        await update.message.reply_text(part)


async def send_hours_confirmation(update: Update, course: str, activities: list, source: str, file_id: str | None) -> None:
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
    if not complete:
        await update.message.reply_text("\n\n".join(sections))
        return
    sections.append("Posso salvar no seu registro de horas? (É uma estimativa: quem valida oficialmente é a coordenação.)")
    token = horas.add_pending(update.effective_chat.id, complete, source, file_id)
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("Salvar", callback_data=f"hrs:ok:{token}"),
        InlineKeyboardButton("Cancelar", callback_data=f"hrs:no:{token}"),
    ]])
    await update.message.reply_text("\n\n".join(sections), reply_markup=keyboard)


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

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    try:
        telegram_file = await attachment.get_file()
        data = bytes(await telegram_file.download_as_bytearray())
        text = await asyncio.to_thread(horas.read_pdf if is_pdf else horas.read_image, data)
    except Exception:
        logger.exception("Falha ao ler certificado de %s", chat_id)
        await message.reply_text("Não consegui abrir esse arquivo. Tente mandar de novo, de preferência em PDF.")
        return
    if message.caption:
        text = f"{text}\n\nMensagem do aluno: {message.caption}"
    if not horas.is_readable(text):
        await message.reply_text(
            "Não consegui ler o texto desse arquivo. Tente uma foto mais nítida e reta, ou mande o PDF do certificado."
        )
        return

    activities = None
    try:
        async with asyncio.timeout(50):
            activities = await horas.extract(text, course)
    except TimeoutError:
        logger.error("Tempo esgotado extraindo certificado de %s", chat_id)
    if activities is None:
        await message.reply_text(ERROR_REPLY)
        return
    if not activities:
        await message.reply_text(
            "Não identifiquei nesse arquivo uma atividade complementar que se encaixe nas regras do seu curso. "
            "Se achar que é um erro, me diga qual foi a atividade e a carga horária."
        )
        return
    await send_hours_confirmation(update, course, activities, "pdf" if is_pdf else "imagem", attachment.file_id)


def hours_listing(chat_id: int) -> tuple[str, InlineKeyboardMarkup | None]:
    course = db.get_course(chat_id)
    entries = db.list_complementary_hours(chat_id)
    if not entries:
        return "Você ainda não registrou nenhuma atividade. Mande um certificado em PDF ou foto, ou me conte uma atividade que você fez.", None
    lines = ["Atividades registradas:"]
    buttons = []
    for number, (entry_id, group, name, hours) in enumerate(entries, start=1):
        lines.append(f"{number}. {name} (Grupo {horas.ROMAN.get(group, group)}): {horas.fmt(hours)}h")
        buttons.append([InlineKeyboardButton(f"Apagar {number}. {name[:30]}", callback_data=f"hrs:del:{entry_id}")])
    summary = horas.summary(chat_id, course)
    if summary:
        lines.append(f"\nTotal por grupo (estimativa; a validação oficial é da coordenação):\n{summary}")
    return "\n".join(lines), InlineKeyboardMarkup(buttons)


async def hours_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text, keyboard = hours_listing(update.effective_chat.id)
    await update.message.reply_text(text, reply_markup=keyboard)


async def handle_hours_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    _, action, token = query.data.split(":", 2)
    chat_id = update.effective_chat.id
    if action == "del":
        if token.isdigit():
            db.delete_complementary_hours(chat_id, int(token))
        text, keyboard = hours_listing(chat_id)
        await query.edit_message_text(text, reply_markup=keyboard)
        return
    pending = horas.pop_pending(token, chat_id)
    if pending is None:
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("Esse registro expirou. Mande o certificado de novo.")
        return
    if action != "ok":
        await query.edit_message_text(f"{query.message.text}\n\nCancelado, nada foi salvo.")
        return
    horas.save(pending)
    await query.edit_message_text(f"{query.message.text}\n\nSalvo!")
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
        "Desculpe, só consigo entender mensagens de texto e certificados em PDF ou foto."
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
        "*[PERGUNTA 1 - preencher]*\n"
        "[RESPOSTA 1 - preencher]\n\n"
        "*[PERGUNTA 2 - preencher]*\n"
        "[RESPOSTA 2 - preencher]\n\n"
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
        "Pode mandar seu feedback na próxima mensagem. Ele é registrado de forma anônima "
        "(por enquanto só no log do servidor — o armazenamento permanente ainda está em desenvolvimento)."
    )

#Main
def main() -> None:
    db.init_db()
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("reset", reset))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("faq", faq))
    application.add_handler(CommandHandler("feedback", feedback_command))
    application.add_handler(CommandHandler("horas", hours_command))
    application.add_handler(CommandHandler("coordcc", coordcc))
    application.add_handler(CommandHandler("coordes", coordes))
    application.add_handler(CommandHandler("coordep", coordep))
    application.add_handler(CommandHandler("coordem", coordem))
    application.add_handler(CommandHandler("coordec", coordec))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.PHOTO | filters.Document.PDF | filters.Document.IMAGE, handle_certificate))
    application.add_handler(CallbackQueryHandler(handle_hours_callback, pattern=r"^hrs:"))
    application.add_handler(MessageHandler(filters.ALL & ~filters.TEXT, handle_unsupported))


    application.run_polling()
if __name__ == "__main__":
    main()