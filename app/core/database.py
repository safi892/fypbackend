import sqlite3
import threading
from pathlib import Path

from app.core.config import DB_PATH

_DB_LOCK = threading.Lock()


def get_db_lock() -> threading.Lock:
    return _DB_LOCK


def get_db_connection() -> sqlite3.Connection:
    path = Path(DB_PATH).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database() -> None:
    with _DB_LOCK:
        with get_db_connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    email TEXT NOT NULL UNIQUE,
                    password_salt TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    token TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS analysis_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    input_code TEXT NOT NULL,
                    commented_code TEXT NOT NULL,
                    explanation TEXT NOT NULL,
                    source TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_analysis_history_user_id
                ON analysis_history (user_id)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_analysis_history_created_at
                ON analysis_history (created_at)
                """
            )
            connection.commit()
