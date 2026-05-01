from typing import Optional

from fastapi import APIRouter, Header

from app.schemas.auth import AuthResponse, LoginRequest, RegisterRequest, SessionUserResponse, TokenResponse
from app.services.auth_service import current_user, login_user, logout_user, register_user


router = APIRouter(prefix="/auth")


@router.post("/register", response_model=AuthResponse)
def register(payload: RegisterRequest) -> AuthResponse:
    return register_user(payload)


@router.post("/login", response_model=AuthResponse)
def login(payload: LoginRequest) -> AuthResponse:
    return login_user(payload)


@router.get("/me", response_model=SessionUserResponse)
def me(authorization: Optional[str] = Header(default=None)) -> SessionUserResponse:
    return current_user(authorization)


@router.post("/logout", response_model=TokenResponse)
def logout(authorization: Optional[str] = Header(default=None)) -> TokenResponse:
    return logout_user(authorization)
