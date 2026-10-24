import os
import sqlite3
from datetime import datetime, timezone

DB_PATH = os.environ.get("DB_PATH", "bot.db")

# A mesma conexão é reaproveitada pelo event loop único do bot (polling sequencial),
# então check_same_thread=False evita o erro de afinidade de thread do sqlite3 sem precisar de lock.
_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
_conn.execute("PRAGMA foreign_keys = ON")


def init_db() -> None:
    _conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            chat_id INTEGER PRIMARY KEY,
            course TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    _conn.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (chat_id) REFERENCES users(chat_id)
        )
        """
    )
    _conn.execute(
        """
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    _conn.execute(
        """
        CREATE TABLE IF NOT EXISTS complementary_hours (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            activity_group INTEGER NOT NULL,
            activity_name TEXT NOT NULL,
            hours REAL NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    _conn.commit()


def _ensure_user(chat_id: int) -> None:
    _conn.execute(
        "INSERT OR IGNORE INTO users (chat_id, course, created_at) VALUES (?, ?, ?)",
        (chat_id, None, datetime.now(timezone.utc).isoformat()),
    )
    _conn.commit()


def save_message(chat_id: int, role: str, content: str) -> None:
    _ensure_user(chat_id)
    _conn.execute(
        "INSERT INTO messages (chat_id, role, content, created_at) VALUES (?, ?, ?, ?)",
        (chat_id, role, content, datetime.now(timezone.utc).isoformat()),
    )
    _conn.commit()


def get_history(chat_id: int, limit: int = 30) -> list[tuple[str, str]]:
    rows = _conn.execute(
        "SELECT role, content FROM messages WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
        (chat_id, limit),
    ).fetchall()
    return list(reversed(rows))


def clear_history(chat_id: int) -> None:
    _conn.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
    _conn.commit()


def set_course(chat_id: int, course: str) -> None:
    _ensure_user(chat_id)
    _conn.execute("UPDATE users SET course = ? WHERE chat_id = ?", (course, chat_id))
    _conn.commit()


def save_feedback(chat_id: int, content: str) -> None:
    _ensure_user(chat_id)
    _conn.execute(
        "INSERT INTO feedback (chat_id, content, created_at) VALUES (?, ?, ?)",
        (chat_id, content, datetime.now(timezone.utc).isoformat()),
    )
    _conn.commit()
