#Imports
import logging
import os
import asyncio
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from telegram.constants import ChatAction
from google import genai
from google.genai import types
from google.genai.errors import APIError

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
SYSTEM_INSTRUCTION = os.environ.get('PROMPT_GENAI')
logger.info("Prompt carregado: %r", SYSTEM_INSTRUCTION)

#Gemini setup/deep-config
gemini_client = genai.Client(api_key=GEMINI_API_KEY)
chats: dict[int,object] = {}

#Functions
def get_chat(chat_id:int):
    if chat_id not in chats:
        chats[chat_id] = gemini_client.aio.chats.create(model=GEMINI_MODEL,
        config=types.GenerateContentConfig(system_instruction=SYSTEM_INSTRUCTION),
        )
    return chats[chat_id]
async def generate_response(chat,user_text: str, tries: int = 3) -> str:
    for exp in range(tries):
        try:
            response = await chat.send_message(user_text)
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
    chat = get_chat(chat_id)

    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
        reply_text = await generate_response(chat, user_text)
    except APIError as e:
        logger.error("Todas as tentativas falharam: %s", e)
        reply_text = "Desculpe, tive um problema para gerar a resposta agora. Tente novamente em instantes."
    await update.message.reply_text(reply_text)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Olá! Eu sou o assistente virtual da UFC Russas. Pode me mandar sua pergunta."
    )
async def handle_unsupported(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Desculpe, por enquanto só consigo entender mensagens de texto, futuramente serei capaz de receber outros tipos de arquivos como certificados em pdf ou imagens :)")
async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    chats.pop(chat_id, None)
    await update.message.reply_text("Memória da conversa reiniciada.")
#Main
def main() -> None:
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("reset", reset))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.ALL & ~filters.TEXT, handle_unsupported))


    application.run_polling()
if __name__ == "__main__":
    main()