import os
import sqlite3
from datetime import datetime, timedelta, timezone

DB_PATH = os.environ.get("DB_PATH", "bot.db")

# A mesma conexão é usada só pela thread do event loop do bot (as atualizações concorrentes são
# corrotinas na mesma thread e estas funções não têm await), então check_same_thread=False evita o
# erro de afinidade de thread do sqlite3 sem precisar de lock.
_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
_conn.execute("PRAGMA foreign_keys = ON")


def _ensure_column(table: str, column: str, coltype: str) -> None:
    cols = [row[1] for row in _conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in cols:
        _conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")
        _conn.commit()


def init_db() -> None:
    _conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            chat_id INTEGER PRIMARY KEY,
            course TEXT,
            created_at TEXT NOT NULL,
            last_active_at TEXT
        )
        """
    )
    _ensure_column("users", "last_active_at", "TEXT")
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
    _ensure_column("complementary_hours", "activity_item", "TEXT")
    _ensure_column("complementary_hours", "certificate_hours", "REAL")
    _ensure_column("complementary_hours", "source", "TEXT")
    _ensure_column("complementary_hours", "file_id", "TEXT")
    _ensure_column("complementary_hours", "explanation", "TEXT")
    _ensure_column("complementary_hours", "course", "TEXT")
    # Feedback saved before it was made anonymous still carried the student's chat id.
    _conn.execute("UPDATE feedback SET chat_id = ? WHERE chat_id != ?", (ANONYMOUS_CHAT_ID, ANONYMOUS_CHAT_ID))
    _conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages (chat_id, id)")
    _conn.execute("CREATE INDEX IF NOT EXISTS idx_hours_chat ON complementary_hours (chat_id)")
    _conn.commit()


def _ensure_user(chat_id: int) -> None:
    now = datetime.now(timezone.utc).isoformat()
    _conn.execute(
        "INSERT OR IGNORE INTO users (chat_id, course, created_at, last_active_at) VALUES (?, ?, ?, ?)",
        (chat_id, None, now, now),
    )
    _conn.commit()


def _touch_activity(chat_id: int) -> None:
    _conn.execute(
        "UPDATE users SET last_active_at = ? WHERE chat_id = ?",
        (datetime.now(timezone.utc).isoformat(), chat_id),
    )
    _conn.commit()


def save_message(chat_id: int, role: str, content: str) -> None:
    _ensure_user(chat_id)
    _conn.execute(
        "INSERT INTO messages (chat_id, role, content, created_at) VALUES (?, ?, ?, ?)",
        (chat_id, role, content, datetime.now(timezone.utc).isoformat()),
    )
    _touch_activity(chat_id)
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


def get_course(chat_id: int) -> str | None:
    row = _conn.execute("SELECT course FROM users WHERE chat_id = ?", (chat_id,)).fetchone()
    return row[0] if row else None


ANONYMOUS_CHAT_ID = 0


def save_feedback(content: str) -> None:
    # The bot promises anonymous feedback, so nothing links it back to the student.
    _conn.execute(
        "INSERT INTO feedback (chat_id, content, created_at) VALUES (?, ?, ?)",
        (ANONYMOUS_CHAT_ID, content, datetime.now(timezone.utc).isoformat()),
    )
    _conn.commit()


def add_complementary_hours(
    chat_id: int,
    group: int,
    item: str | None,
    name: str,
    certificate_hours: float | None,
    credited_hours: float,
    source: str,
    file_id: str | None,
    explanation: str,
    course: str | None,
) -> None:
    _ensure_user(chat_id)
    _conn.execute(
        """
        INSERT INTO complementary_hours
            (chat_id, activity_group, activity_item, activity_name, certificate_hours, hours,
             status, source, file_id, explanation, course, created_at)
        VALUES (?, ?, ?, ?, ?, ?, 'registrado pelo aluno', ?, ?, ?, ?, ?)
        """,
        (chat_id, group, item, name, certificate_hours, credited_hours, source, file_id, explanation, course,
         datetime.now(timezone.utc).isoformat()),
    )
    _touch_activity(chat_id)
    _conn.commit()


def list_complementary_hours(chat_id: int) -> list[tuple[int, int, str, float, str | None]]:
    return _conn.execute(
        "SELECT id, activity_group, activity_name, hours, course FROM complementary_hours WHERE chat_id = ? ORDER BY id",
        (chat_id,),
    ).fetchall()


def delete_complementary_hours(chat_id: int, entry_id: int) -> bool:
    cursor = _conn.execute("DELETE FROM complementary_hours WHERE id = ? AND chat_id = ?", (entry_id, chat_id))
    _conn.commit()
    return cursor.rowcount > 0


def hours_by_group(chat_id: int, course: str | None = None) -> dict[int, float]:
    """Hours per group; with a course, only entries registered under it (or before courses were stored)."""
    query = "SELECT activity_group, SUM(hours) FROM complementary_hours WHERE chat_id = ?"
    params: tuple = (chat_id,)
    if course is not None:
        query += " AND (course = ? OR course IS NULL)"
        params += (course,)
    rows = _conn.execute(query + " GROUP BY activity_group", params).fetchall()
    return {group: total for group, total in rows}


def delete_inactive_users(days: int) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = _conn.execute(
        "SELECT chat_id FROM users WHERE last_active_at IS NOT NULL AND last_active_at < ?",
        (cutoff,),
    ).fetchall()
    chat_ids = [row[0] for row in rows]
    for chat_id in chat_ids:
        _conn.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
        _conn.execute("DELETE FROM complementary_hours WHERE chat_id = ?", (chat_id,))
        _conn.execute("DELETE FROM users WHERE chat_id = ?", (chat_id,))
    _conn.commit()
    return len(chat_ids)
