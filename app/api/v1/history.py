from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.v1.auth import get_current_user
from app.core.database import (
    clear_user_search_history,
    delete_search_history_item,
    get_user_search_history,
)

router = APIRouter(prefix="/history", tags=["История поисковых запросов"])


class HistoryItem(BaseModel):
    id: int
    query: str
    result_summary: str | None = None
    searched_at: str


@router.get("", response_model=list[HistoryItem], summary="История поисков текущего сотрудника")
async def get_my_history(user: dict[str, Any] = Depends(get_current_user)):
    """Возвращает персональную историю поисковых запросов пользователя."""
    rows = get_user_search_history(user["id"], limit=50)
    return [
        HistoryItem(
            id=r["id"],
            query=r["query"],
            result_summary=r.get("result_summary"),
            searched_at=r["searched_at"],
        )
        for r in rows
    ]


@router.delete("", summary="Очистить всю историю поисков")
async def clear_my_history(user: dict[str, Any] = Depends(get_current_user)):
    """Удаляет все записи поисковой истории для текущего пользователя."""
    clear_user_search_history(user["id"])
    return {"status": "ok", "message": "История поиска успешно очищена."}


@router.delete("/{history_id}", summary="Удалить одну запись из истории")
async def delete_history_item(history_id: int, user: dict[str, Any] = Depends(get_current_user)):
    """Удаляет выбранную запись из истории поиска."""
    success = delete_search_history_item(user["id"], history_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Запись истории не найдена."
        )
    return {"status": "ok", "message": "Запись истории удалена."}
