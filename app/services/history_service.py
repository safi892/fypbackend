from datetime import UTC, datetime

from app.core.database import get_db_connection, get_db_lock
from app.schemas.history import HistoryEntry


def _utc_now() -> datetime:
    return datetime.now(UTC)


def record_history(
    user_id: int,
    input_code: str,
    commented_code: str,
    explanation: str,
    source: str | None,
) -> int:
    created_at = _utc_now().isoformat()

    with get_db_lock():
        with get_db_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO analysis_history
                (user_id, input_code, commented_code, explanation, source, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, input_code, commented_code, explanation, source, created_at),
            )
            connection.commit()
            return int(cursor.lastrowid) if cursor.lastrowid is not None else 0


def list_history(user_id: int, limit: int, offset: int) -> tuple[list[HistoryEntry], int]:
    with get_db_lock():
        with get_db_connection() as connection:
            total_row = connection.execute(
                "SELECT COUNT(*) AS total FROM analysis_history WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            total = int(total_row["total"]) if total_row else 0

            rows = connection.execute(
                """
                SELECT id, input_code, commented_code, explanation, source, created_at
                FROM analysis_history
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT ? OFFSET ?
                """,
                (user_id, limit, offset),
            ).fetchall()

    items = [
        HistoryEntry(
            id=int(row["id"]),
            input_code=row["input_code"],
            commented_code=row["commented_code"],
            explanation=row["explanation"],
            source=row["source"],
            created_at=row["created_at"],
        )
        for row in rows
    ]

    return items, total
