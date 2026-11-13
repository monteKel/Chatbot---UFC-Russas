import sqlite3
from datetime import datetime, timedelta, timezone

import db


def test_history_order_limit_and_clear():
    for i in range(5):
        db.save_message(1, "user" if i % 2 == 0 else "model", f"m{i}")
    assert db.get_history(1, limit=3) == [("user", "m2"), ("model", "m3"), ("user", "m4")]
    db.save_message(2, "user", "outro aluno")
    db.clear_history(1)
    assert db.get_history(1) == []
    assert db.get_history(2) == [("user", "outro aluno")]


def test_course_roundtrip():
    assert db.get_course(5) is None
    db.set_course(5, "Engenharia Civil")
    db.set_course(5, "Engenharia de Software")
    assert db.get_course(5) == "Engenharia de Software"


def test_hours_crud_and_ownership():
    db.add_complementary_hours(1, 4, "c", "Curso A", 8, 8, "pdf", "F1", "x", course="Engenharia Civil")
    db.add_complementary_hours(1, 4, "c", "Curso B", 4, 4, "pdf", "F2", "x", course="Engenharia Civil")
    db.add_complementary_hours(2, 4, "c", "Outro aluno", 10, 10, "pdf", "F3", "x", course="Engenharia Civil")
    entries = db.list_complementary_hours(1)
    assert [e[2] for e in entries] == ["Curso A", "Curso B"]
    assert db.hours_by_group(1) == {4: 12}
    other_id = db.list_complementary_hours(2)[0][0]
    assert db.delete_complementary_hours(1, other_id) is False   # can't delete someone else's
    assert db.delete_complementary_hours(1, entries[0][0]) is True
    assert db.hours_by_group(1) == {4: 4}


def test_feedback_is_anonymous():
    db.save_feedback("o bot é ótimo")
    rows = db._conn.execute("SELECT chat_id, content FROM feedback").fetchall()
    assert rows == [(0, "o bot é ótimo")]
    assert db._conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0


def test_old_feedback_is_anonymized_on_startup():
    db._conn.execute("INSERT INTO feedback (chat_id, content, created_at) VALUES (5834858732, 'antigo', 'x')")
    db._conn.commit()
    db.init_db()
    assert db._conn.execute("SELECT chat_id FROM feedback").fetchall() == [(0,)]


def test_delete_inactive_users_removes_everything_for_old_users_only():
    db.save_message(1, "user", "antigo")
    db.add_complementary_hours(1, 4, None, "Curso", 8, 8, "texto", None, "x", course="Engenharia Civil")
    db.save_message(2, "user", "recente")
    old = (datetime.now(timezone.utc) - timedelta(days=2000)).isoformat()
    db._conn.execute("UPDATE users SET last_active_at = ? WHERE chat_id = 1", (old,))
    db._conn.commit()
    assert db.delete_inactive_users(5 * 365) == 1
    assert db.get_history(1) == [] and db.list_complementary_hours(1) == []
    assert db.get_history(2) == [("user", "recente")]


def test_migration_adds_new_columns_to_old_database(monkeypatch, tmp_path):
    old = sqlite3.connect(tmp_path / "old.db", check_same_thread=False)
    old.execute("CREATE TABLE users (chat_id INTEGER PRIMARY KEY, course TEXT, created_at TEXT NOT NULL)")
    old.execute("CREATE TABLE complementary_hours (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL, "
                "activity_group INTEGER NOT NULL, activity_name TEXT NOT NULL, hours REAL NOT NULL, "
                "status TEXT NOT NULL, created_at TEXT NOT NULL)")
    old.execute("INSERT INTO complementary_hours (chat_id, activity_group, activity_name, hours, status, created_at) "
                "VALUES (1, 7, 'Legado', 24, 'x', 'agora')")
    old.commit()
    monkeypatch.setattr(db, "_conn", old)
    db.init_db()
    columns = {row[1] for row in old.execute("PRAGMA table_info(complementary_hours)")}
    assert {"activity_item", "certificate_hours", "source", "file_id", "explanation", "course"} <= columns
    assert "last_active_at" in {row[1] for row in old.execute("PRAGMA table_info(users)")}
    # Rows saved before the course column existed still count for the student's current course.
    assert db.hours_by_group(1, "Engenharia Civil") == {7: 24}
