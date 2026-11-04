from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.v1.auth import get_current_user
from app.core.database import (
    create_user,
    delete_user,
    get_all_users,
    get_user_by_id,
    get_user_by_username,
    toggle_user_active,
    update_user_password,
)

router = APIRouter(prefix="/admin", tags=["Панель администратора"])


# ------------------------------------------------------------------------------
# Dependency: Проверка прав суперпользователя / администратора
# ------------------------------------------------------------------------------

def require_admin(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    """Проверяет, что текущий пользователь обладает ролью admin."""
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ запрещен. Действие доступно только администраторам."
        )
    return user


# ------------------------------------------------------------------------------
# Pydantic-схемы
# ------------------------------------------------------------------------------

class AdminUserItem(BaseModel):
    id: int
    username: str
    full_name: str
    role: str
    avatar_url: str | None = None
    is_active: bool
    created_at: str
    search_count: int = 0


class CreateUserRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=50, description="Логин учетной записи")
    password: str = Field(..., min_length=4, description="Первоначальный пароль сотрудника")
    full_name: str = Field(..., min_length=2, max_length=150, description="Ф.И.О. сотрудника")
    role: str = Field(default="user", description="Роль: 'user' или 'admin'")


class ResetPasswordAdminRequest(BaseModel):
    new_password: str = Field(..., min_length=4, description="Новый пароль для сотрудника")


# ------------------------------------------------------------------------------
# Эндпоинты администратора
# ------------------------------------------------------------------------------

@router.get("/users", response_model=list[AdminUserItem], summary="Список всех сотрудников")
async def list_users(_: dict[str, Any] = Depends(require_admin)):
    """Возвращает перечень всех сотрудников системы с количеством выполненных поисков."""
    rows = get_all_users()
    return [
        AdminUserItem(
            id=r["id"],
            username=r["username"],
            full_name=r["full_name"],
            role=r["role"],
            avatar_url=r.get("avatar_url"),
            is_active=bool(r.get("is_active", 1)),
            created_at=r["created_at"],
            search_count=r.get("search_count", 0),
        )
        for r in rows
    ]


@router.post("/users", response_model=AdminUserItem, status_code=status.HTTP_201_CREATED, summary="Создание нового сотрудника")
async def add_new_user(req: CreateUserRequest, _: dict[str, Any] = Depends(require_admin)):
    """Создает новую учетную запись для доступа к сервису."""
    existing = get_user_by_username(req.username)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Пользователь с логином '{req.username}' уже существует."
        )

    user = create_user(
        username=req.username,
        password=req.password,
        full_name=req.full_name,
        role=req.role if req.role in {"admin", "user"} else "user",
    )
    return AdminUserItem(
        id=user["id"],
        username=user["username"],
        full_name=user["full_name"],
        role=user["role"],
        avatar_url=user.get("avatar_url"),
        is_active=bool(user.get("is_active", 1)),
        created_at=user["created_at"],
        search_count=0,
    )


@router.post("/users/{user_id}/reset-password", summary="Сброс пароля сотрудника администратором")
async def reset_password(
    user_id: int,
    req: ResetPasswordAdminRequest,
    _: dict[str, Any] = Depends(require_admin),
):
    """
    Позволяет администратору принудительно установить новый пароль
    любому сотруднику (например, при утере доступа).
    """
    target = get_user_by_id(user_id)
    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Пользователь с ID={user_id} не найден."
        )

    update_user_password(user_id, req.new_password)
    return {
        "status": "ok",
        "message": f"Пароль для пользователя '{target['username']}' успешно сброшен."
    }


@router.post("/users/{user_id}/toggle-active", summary="Блокировка / разблокировка учетной записи")
async def toggle_active(
    user_id: int,
    admin: dict[str, Any] = Depends(require_admin),
):
    """Включает или выключает доступ пользователя к системе."""
    if user_id == admin["id"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Нельзя заблокировать собственную учетную запись администратора."
        )

    target = get_user_by_id(user_id)
    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Пользователь с ID={user_id} не найден."
        )

    toggle_user_active(user_id)
    updated = get_user_by_id(user_id)
    assert updated is not None
    new_state = "активен" if updated["is_active"] else "заблокирован"
    return {"status": "ok", "is_active": bool(updated["is_active"]), "message": f"Статус изменен на: {new_state}"}


@router.delete("/users/{user_id}", summary="Удаление пользователя")
async def remove_user(
    user_id: int,
    admin: dict[str, Any] = Depends(require_admin),
):
    """Удаляет сотрудника из базы данных."""
    if user_id == admin["id"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Нельзя удалить собственную учетную запись администратора."
        )

    target = get_user_by_id(user_id)
    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Пользователь с ID={user_id} не найден."
        )

    delete_user(user_id)
    return {"status": "ok", "message": f"Пользователь '{target['username']}' удален."}
