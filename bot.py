#Imports
import logging
import os
import asyncio
import chromadb
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from telegram.constants import ChatAction
from google import genai
from google.genai import types
from google.genai.errors import APIError

import db

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
GEMINI_MODEL = os.environ.get('GEMINI_MODEL', 'gemini-3.1-flash-lite')
EMBEDDING_MODEL = os.environ.get('EMBEDDING_MODEL', 'gemini-embedding-001')
CHROMA_PATH = os.environ.get('CHROMA_PATH', 'chroma_db')
SYSTEM_INSTRUCTION = os.environ.get('PROMPT_GENAI')
logger.info("Prompt carregado: %r", SYSTEM_INSTRUCTION)

#Gemini setup/deep-config
gemini_client = genai.Client(api_key=GEMINI_API_KEY)
chats: dict[int,object] = {}
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
    "/coordcc - Contato da coordenação de Ciência da Computação\n"
    "/coordes - Contato da coordenação de Engenharia de Software\n"
    "/coordep - Contato da coordenação de Engenharia de Produção\n"
    "/coordem - Contato da coordenação de Engenharia Mecânica\n"
    "/coordec - Contato da coordenação de Engenharia Civil\n"
    "/reset - Reinicia a memória da nossa conversa"
)

VALID_COURSES = {
    "Ciência da Computação",
    "Engenharia de Software",
    "Engenharia de Produção",
    "Engenharia Civil",
    "Engenharia Mecânica",
}

SET_COURSE_DECLARATION = types.FunctionDeclaration(
    name="set_course",
    description=(
        "Registra ou corrige o curso de graduação do aluno. Só chame esta função quando "
        "o aluno afirmar claramente e sem ambiguidade qual curso faz (ex: 'eu sou de "
        "engenharia de software', 'meu curso é ciência da computação'), ou quando ele "
        "pedir explicitamente para corrigir/trocar o curso já registrado. NÃO chame com "
        "base em pistas indiretas, suposições ou menções a disciplinas/atividades que "
        "poderiam pertencer a mais de um curso — nesses casos, pergunte ao aluno qual é "
        "o curso antes de registrar."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "course": types.Schema(
                type=types.Type.STRING,
                enum=sorted(VALID_COURSES),
                description="Nome completo do curso de graduação do aluno, na lista de cursos do Campus de Russas.",
            )
        },
        required=["course"],
    ),
)

#Functions
async def retrieve_context(question: str, course_prefix: str | None, n_results: int = 10) -> list[str]:
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
        return []


def get_chat(chat_id:int):
    if chat_id not in chats:
        history = [
            types.Content(role=role, parts=[types.Part(text=content)])
            for role, content in db.get_history(chat_id)
        ]
        chats[chat_id] = gemini_client.aio.chats.create(model=GEMINI_MODEL,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            tools=[
                types.Tool(google_search=types.GoogleSearch()),
                types.Tool(function_declarations=[SET_COURSE_DECLARATION]),
            ],
        ),
        history=history,
        )
    return chats[chat_id]
async def generate_response(chat, chat_id: int, user_text: str, tries: int = 3) -> str:
    for exp in range(tries):
        try:
            response = await chat.send_message(user_text)
            while response.function_calls:
                function_responses = []
                for call in response.function_calls:
                    if call.name == "set_course":
                        course = call.args.get("course")
                        if course in VALID_COURSES:
                            db.set_course(chat_id, course)
                            result = {"status": "ok"}
                        else:
                            result = {"status": "error", "message": "curso invalido"}
                    else:
                        result = {"status": "error", "message": "funcao desconhecida"}
                    function_responses.append(types.Part.from_function_response(name=call.name, response=result))
                response = await chat.send_message(function_responses)
            return response.text
        except APIError as e:
            logger.warning("Tentativa %d falhou: %s", exp + 1, e)
            if exp == tries - 1:
                raise
            await asyncio.sleep(2 ** exp)


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

    chat = get_chat(chat_id)
    course = db.get_course(chat_id)
    course_prefix = COURSE_TO_PREFIX.get(course) if course else None
    retrieved_chunks = await retrieve_context(user_text, course_prefix)
    if retrieved_chunks:
        context_block = "\n\n---\n\n".join(retrieved_chunks)
        prompt_text = (
            f"Contexto de documentos oficiais da UFC Russas:\n{context_block}\n\n"
            f"Pergunta do aluno: {user_text}"
        )
    else:
        prompt_text = user_text

    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
        reply_text = await generate_response(chat, chat_id, prompt_text)
    except APIError as e:
        logger.error("Todas as tentativas falharam: %s", e)
        reply_text = "Desculpe, tive um problema para gerar a resposta agora. Tente novamente em instantes."
    else:
        db.save_message(chat_id, "user", user_text)
        db.save_message(chat_id, "model", reply_text)
    await update.message.reply_text(reply_text)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "👋 *Olá! Eu sou o assistente virtual da UFC Russas.*\n\n"
        "Posso te ajudar com dúvidas acadêmicas, especialmente sobre horas complementares.\n\n"
        f"{COMMANDS_TEXT}\n\n"
        "Fora isso, é só me mandar sua pergunta diretamente!"
    )
    await update.message.reply_text(text, parse_mode="Markdown")
async def handle_unsupported(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Desculpe, por enquanto só consigo entender mensagens de texto, futuramente serei capaz de receber outros tipos de arquivos como certificados em pdf ou imagens :)")
async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    chats.pop(chat_id, None)
    db.clear_history(chat_id)
    await update.message.reply_text("Memória da conversa reiniciada.")
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "*Assistente Virtual - UFC Russas*\n\n"
        "Posso te ajudar com dúvidas acadêmicas, especialmente sobre horas complementares.\n\n"
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
    application.add_handler(CommandHandler("coordcc", coordcc))
    application.add_handler(CommandHandler("coordes", coordes))
    application.add_handler(CommandHandler("coordep", coordep))
    application.add_handler(CommandHandler("coordem", coordem))
    application.add_handler(CommandHandler("coordec", coordec))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.ALL & ~filters.TEXT, handle_unsupported))


    application.run_polling()
if __name__ == "__main__":
    main()