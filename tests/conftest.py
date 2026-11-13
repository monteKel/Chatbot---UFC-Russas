import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Isolated environment: temp SQLite/Chroma, no real API keys (empty values stop load_dotenv
# from filling them in from .env), so unit tests never touch the network.
_TMP = tempfile.mkdtemp(prefix="ufc_bot_tests_")
os.environ["DB_PATH"] = os.path.join(_TMP, "test.db")
os.environ["CHROMA_PATH"] = os.path.join(_TMP, "chroma")
os.environ["TELEGRAM_BOT_TOKEN"] = "123456:TEST-TOKEN"
os.environ["GEMINI_API_KEY"] = "test-key"
os.environ["GROQ_API_KEY"] = ""
os.environ["OPENROUTER_API_KEY"] = ""
os.environ["GEMINI_FALLBACK"] = "0"
os.environ["PROMPT_GENAI"] = "Você é o assistente de teste."

import pytest  # noqa: E402

import db  # noqa: E402
import horas  # noqa: E402
import llm  # noqa: E402


@pytest.fixture(autouse=True)
def clean_state():
    db.init_db()
    for table in ("messages", "feedback", "complementary_hours", "users"):
        db._conn.execute(f"DELETE FROM {table}")
    db._conn.commit()
    horas._pending.clear()
    llm._cooldown_until.clear()
    llm._providers = []
    import bot

    bot.awaiting_feedback.clear()
    yield


@pytest.fixture
def no_sleep(monkeypatch):
    waits = []

    async def fake_sleep(seconds):
        waits.append(seconds)

    monkeypatch.setattr(llm.asyncio, "sleep", fake_sleep)
    return waits
