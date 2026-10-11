from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class RegisterRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(..., min_length=1, description="User name")
    email: str = Field(..., min_length=1, description="User email")
    password: str = Field(..., min_length=6, description="User password")
    confirm_password: str = Field(
        ...,
        min_length=6,
        description="Password confirmation",
        validation_alias=AliasChoices("confirm_password", "confirmPassword"),
    )


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=1, description="User email")
    password: str = Field(..., min_length=1, description="User password")


class AuthUser(BaseModel):
    id: int
    name: str
    email: str


class AuthResponse(BaseModel):
    message: str
    token: str
    user: AuthUser


class TokenResponse(BaseModel):
    message: str


class SessionUserResponse(BaseModel):
    user: AuthUser
