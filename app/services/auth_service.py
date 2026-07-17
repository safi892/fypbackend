import hashlib
import secrets
import sqlite3
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException

from app.core.config import PASSWORD_HASH_ITERATIONS, SESSION_TTL_HOURS
from app.core.database import get_db_connection, get_db_lock
from app.schemas.auth import (
    AuthResponse,
    AuthUser,
    LoginRequest,
    RegisterRequest,
    SessionUserResponse,
    TokenResponse,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        PASSWORD_HASH_ITERATIONS,
    ).hex()


def _create_password_record(password: str) -> tuple[str, str]:
    salt = secrets.token_hex(16)
    return salt, _hash_password(password, salt)


def _verify_password(password: str, salt: str, password_hash: str) -> bool:
    return secrets.compare_digest(_hash_password(password, salt), password_hash)


def _create_session(connection: sqlite3.Connection, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    created_at = _utc_now().isoformat()
    expires_at = (_utc_now() + timedelta(hours=SESSION_TTL_HOURS)).isoformat()
    connection.execute(
        "INSERT INTO sessions (user_id, token, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (user_id, token, created_at, expires_at),
    )
    return token


def _get_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization token")

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="Invalid authorization token")

    return token.strip()


def _get_user_from_session(token: str) -> AuthUser:
    with get_db_lock():
        with get_db_connection() as connection:
            session = connection.execute(
                """
                SELECT s.expires_at, u.id, u.name, u.email
                FROM sessions s
                JOIN users u ON u.id = s.user_id
                WHERE s.token = ?
                """,
                (token,),
            ).fetchone()

            if session is None:
                raise HTTPException(status_code=401, detail="Invalid session")

            expires_at = datetime.fromisoformat(session["expires_at"])
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if expires_at <= _utc_now():
                connection.execute("DELETE FROM sessions WHERE token = ?", (token,))
                connection.commit()
                raise HTTPException(status_code=401, detail="Session expired")

            return AuthUser(id=int(session["id"]), name=session["name"], email=session["email"])


def _delete_session(token: str) -> None:
    with get_db_lock():
        with get_db_connection() as connection:
            connection.execute("DELETE FROM sessions WHERE token = ?", (token,))
            connection.commit()


def register_user(payload: RegisterRequest) -> AuthResponse:
    name = payload.name.strip()
    email = _normalize_email(payload.email)

    if payload.password != payload.confirm_password:
        raise HTTPException(status_code=400, detail="Password and confirm password do not match")

    if not name:
        raise HTTPException(status_code=400, detail="Name is required")

    salt, password_hash = _create_password_record(payload.password)
    created_at = _utc_now().isoformat()

    with get_db_lock():
        with get_db_connection() as connection:
            existing_user = connection.execute(
                "SELECT id FROM users WHERE email = ?",
                (email,),
            ).fetchone()
            if existing_user is not None:
                raise HTTPException(status_code=409, detail="Email is already registered")

            cursor = connection.execute(
                """
                INSERT INTO users (name, email, password_salt, password_hash, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (name, email, salt, password_hash, created_at),
            )
            user_id = int(cursor.lastrowid) if cursor.lastrowid is not None else 0
            token = _create_session(connection, user_id)
            connection.commit()

    user = AuthUser(id=user_id, name=name, email=email)
    return AuthResponse(message="Registration successful", token=token, user=user)


def login_user(payload: LoginRequest) -> AuthResponse:
    email = _normalize_email(payload.email)

    with get_db_lock():
        with get_db_connection() as connection:
            user = connection.execute(
                """
                SELECT id, name, email, password_salt, password_hash
                FROM users
                WHERE email = ?
                """,
                (email,),
            ).fetchone()

            if user is None:
                raise HTTPException(status_code=401, detail="Invalid email or password")

            if not _verify_password(payload.password, user["password_salt"], user["password_hash"]):
                raise HTTPException(status_code=401, detail="Invalid email or password")

            token = _create_session(connection, int(user["id"]))
            connection.commit()

    auth_user = AuthUser(id=int(user["id"]), name=user["name"], email=user["email"])
    return AuthResponse(message="Login successful", token=token, user=auth_user)


def current_user(authorization: str | None) -> SessionUserResponse:
    token = _get_bearer_token(authorization)
    user = _get_user_from_session(token)
    return SessionUserResponse(user=user)


def require_user(authorization: str | None) -> AuthUser:
    token = _get_bearer_token(authorization)
    return _get_user_from_session(token)


def logout_user(authorization: str | None) -> TokenResponse:
    token = _get_bearer_token(authorization)
    _delete_session(token)
    return TokenResponse(message="Logged out successfully")
