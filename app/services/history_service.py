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
    optimized_code: str | None = None,
    optimization_verified: bool | None = None,
    speedup: float | None = None,
    optimization_note: str | None = None,
) -> int:
    created_at = _utc_now().isoformat()
    verified_int = (
        1 if optimization_verified is True else (0 if optimization_verified is False else None)
    )

    with get_db_lock():
        with get_db_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO analysis_history
                (user_id, input_code, commented_code, explanation, source, created_at,
                 optimized_code, optimization_verified, speedup, optimization_note)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    input_code,
                    commented_code,
                    explanation,
                    source,
                    created_at,
                    optimized_code,
                    verified_int,
                    speedup,
                    optimization_note,
                ),
            )
            connection.commit()
            return int(cursor.lastrowid) if cursor.lastrowid is not None else 0


def record_optimization(
    user_id: int,
    input_code: str,
    optimized_code: str | None,
    optimization_verified: bool | None,
    speedup: float | None,
    optimization_note: str | None,
    commented_code: str = "",
    explanation: str = "",
    source: str | None = None,
) -> int:
    """Persist optimization results against an existing analysis row or insert a new row."""
    clean_code = input_code.strip()
    verified_int = (
        1 if optimization_verified is True else (0 if optimization_verified is False else None)
    )

    with get_db_lock():
        with get_db_connection() as connection:
            # Check for most recent matching history entry for this user and code
            row = connection.execute(
                """
                SELECT id FROM analysis_history
                WHERE user_id = ? AND (input_code = ? OR TRIM(input_code) = ?)
                ORDER BY id DESC LIMIT 1
                """,
                (user_id, input_code, clean_code),
            ).fetchone()

            if row:
                entry_id = int(row["id"])
                connection.execute(
                    """
                    UPDATE analysis_history
                    SET optimized_code = ?,
                        optimization_verified = ?,
                        speedup = ?,
                        optimization_note = ?
                    WHERE id = ?
                    """,
                    (optimized_code, verified_int, speedup, optimization_note, entry_id),
                )
                connection.commit()
                return entry_id

            created_at = _utc_now().isoformat()
            cursor = connection.execute(
                """
                INSERT INTO analysis_history
                (user_id, input_code, commented_code, explanation, source, created_at,
                 optimized_code, optimization_verified, speedup, optimization_note)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    input_code,
                    commented_code,
                    explanation,
                    source,
                    created_at,
                    optimized_code,
                    verified_int,
                    speedup,
                    optimization_note,
                ),
            )
            connection.commit()
            return int(cursor.lastrowid) if cursor.lastrowid is not None else 0


def get_history_entry(user_id: int, entry_id: int) -> HistoryEntry | None:
    """Return a single history entry by ID belonging to user_id, or None."""
    with get_db_lock():
        with get_db_connection() as connection:
            row = connection.execute(
                """
                SELECT id, input_code, commented_code, explanation, source, created_at,
                       optimized_code, optimization_verified, speedup, optimization_note
                FROM analysis_history
                WHERE user_id = ? AND id = ?
                """,
                (user_id, entry_id),
            ).fetchone()

    if not row:
        return None

    return HistoryEntry(
        id=int(row["id"]),
        input_code=row["input_code"],
        commented_code=row["commented_code"],
        explanation=row["explanation"],
        source=row["source"],
        created_at=row["created_at"],
        optimized_code=row["optimized_code"] if row["optimized_code"] is not None else None,
        optimization_verified=(
            bool(row["optimization_verified"])
            if row["optimization_verified"] is not None
            else None
        ),
        speedup=float(row["speedup"]) if row["speedup"] is not None else None,
        optimization_note=(
            row["optimization_note"] if row["optimization_note"] is not None else None
        ),
    )


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
                SELECT id, input_code, commented_code, explanation, source, created_at,
                       optimized_code, optimization_verified, speedup, optimization_note
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
            optimized_code=row["optimized_code"] if row["optimized_code"] is not None else None,
            optimization_verified=(
                bool(row["optimization_verified"])
                if row["optimization_verified"] is not None
                else None
            ),
            speedup=float(row["speedup"]) if row["speedup"] is not None else None,
            optimization_note=(
                row["optimization_note"] if row["optimization_note"] is not None else None
            ),
        )
        for row in rows
    ]

    return items, total
