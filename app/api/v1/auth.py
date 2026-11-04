import shutil
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from app.core.database import (
    create_session,
    delete_session,
    get_avatars_dir,
    get_user_by_id,
    get_user_by_session_token,
    get_user_by_username,
    update_user_avatar,
    update_user_password,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["Аутентификация и профиль"])


# ------------------------------------------------------------------------------
# Pydantic-схемы
# ------------------------------------------------------------------------------

class LoginRequest(BaseModel):
    username: str = Field(..., description="Логин учетной записи", examples=["ivanov"])
    password: str = Field(..., description="Пароль пользователя", examples=["MyPassword123"])


class UserProfileResponse(BaseModel):
    id: int
    username: str
    full_name: str
    role: str
    avatar_url: str | None = None
    is_active: bool = True


class LoginResponse(BaseModel):
    token: str
    user: UserProfileResponse


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., description="Текущий пароль")
    new_password: str = Field(..., min_length=4, description="Новый пароль")


# ------------------------------------------------------------------------------
# Dependency Injection: Текущий авторизованный пользователь
# ------------------------------------------------------------------------------

def get_current_user_optional(
    authorization: str | None = Header(None, alias="Authorization"),
    x_auth_token: str | None = Header(None, alias="X-Auth-Token"),
) -> dict[str, Any] | None:
    """
    Извлекает сессионный токен из заголовка Authorization (Bearer <token>)
    или X-Auth-Token. Если токен валиден, возвращает данные пользователя.
    """
    raw_token = None
    if authorization and authorization.startswith("Bearer "):
        raw_token = authorization.split("Bearer ", 1)[1].strip()
    elif x_auth_token:
        raw_token = x_auth_token.strip()

    if raw_token:
        user = get_user_by_session_token(raw_token)
        if user:
            return user

    return None


def get_current_user(
    current_user: dict[str, Any] | None = Depends(get_current_user_optional),
) -> dict[str, Any]:
    """
    Обязательная аутентификация: если пользователь не опознан, возвращает HTTP 401.
    """
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Пожалуйста, войдите в систему.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return current_user


# ------------------------------------------------------------------------------
# Роуты аутентификации
# ------------------------------------------------------------------------------

@router.post("/login", response_model=LoginResponse, summary="Авторизация по логину и паролю")
async def login(req: LoginRequest):
    """
    Проверяет логин и пароль сотрудника. При успешном совпадении
    создает сессию и возвращает персональный токен доступа.
    """
    user = get_user_by_username(req.username)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверное имя пользователя или пароль."
        )

    if not user.get("is_active", 1):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Учетная запись отключена администратором."
        )

    if not verify_password(req.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверное имя пользователя или пароль."
        )

    token = create_session(user["id"])
    profile = UserProfileResponse(
        id=user["id"],
        username=user["username"],
        full_name=user["full_name"],
        role=user["role"],
        avatar_url=user.get("avatar_url"),
        is_active=bool(user.get("is_active", 1)),
    )
    return LoginResponse(token=token, user=profile)


@router.post("/logout", summary="Выход из системы (аннулирование сессии)")
async def logout(
    authorization: str | None = Header(None, alias="Authorization"),
    x_auth_token: str | None = Header(None, alias="X-Auth-Token"),
):
    """Аннулирует текущую сессию пользователя."""
    raw_token = None
    if authorization and authorization.startswith("Bearer "):
        raw_token = authorization.split("Bearer ", 1)[1].strip()
    elif x_auth_token:
        raw_token = x_auth_token.strip()

    if raw_token:
        delete_session(raw_token)
    return {"status": "ok", "message": "Сессия успешно завершена."}


@router.get("/me", response_model=UserProfileResponse, summary="Профиль текущего пользователя")
async def get_my_profile(user: dict[str, Any] = Depends(get_current_user)):
    """Возвращает информацию о текущем авторизованном сотруднике."""
    return UserProfileResponse(
        id=user["id"],
        username=user["username"],
        full_name=user["full_name"],
        role=user["role"],
        avatar_url=user.get("avatar_url"),
        is_active=bool(user.get("is_active", 1)),
    )


@router.post("/change-password", summary="Смена собственного пароля")
async def change_password(
    req: ChangePasswordRequest,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Позволяет сотруднику изменить свой пароль."""
    db_user = get_user_by_id(user["id"])
    if not db_user or not verify_password(req.old_password, db_user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Текущий пароль указан неверно."
        )

    update_user_password(user["id"], req.new_password)
    return {"status": "ok", "message": "Пароль успешно обновлен."}


@router.post("/avatar", summary="Загрузка аватарки профиля")
async def upload_avatar(
    file: UploadFile = File(...),
    user: dict[str, Any] = Depends(get_current_user),
):
    """
    Загружает изображение профиля (JPEG, PNG, WebP, GIF),
    сохраняет его в локальное хранилище и привязывает к учетной записи.
    """
    # Проверка типа файла
    allowed_types = {"image/jpeg", "image/png", "image/webp", "image/gif"}
    content_type = file.content_type or ""
    if content_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Недопустимый формат файла. Разрешены: JPEG, PNG, WebP, GIF."
        )

    # Определение расширения
    ext = ".jpg"
    if "png" in content_type:
        ext = ".png"
    elif "webp" in content_type:
        ext = ".webp"
    elif "gif" in content_type:
        ext = ".gif"

    avatars_dir = get_avatars_dir()
    filename = f"avatar_{user['id']}_{int(time.time())}{ext}"
    dest_path = avatars_dir / filename

    try:
        with open(dest_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Не удалось сохранить файл аватарки: {e}"
        )

    avatar_url = f"/static/avatars/{filename}"
    update_user_avatar(user["id"], avatar_url)

    return {"status": "ok", "avatar_url": avatar_url}
