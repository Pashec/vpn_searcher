from typing import Any, Union

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.v1.auth import get_current_user
from app.core.config import settings
from app.core.database import add_search_history
from app.schemas.memo import MemoResponseSchema, UserCandidatesResponseSchema
from app.services.base import BaseMemoService
from app.services.urfa_client import UrfaMemoService

router = APIRouter(prefix="/memo", tags=["Памятка сотрудника"])


def get_memo_service() -> BaseMemoService:
    """
    Фабрика внедрения зависимостей (Dependency Injection).
    Возвращает боевой UrfaMemoService для взаимодействия с сервером биллинга.
    """
    return UrfaMemoService()


@router.get(
    "/search",
    response_model=Union[MemoResponseSchema, UserCandidatesResponseSchema],
    summary="Единый поиск памятки или списка кандидатов",
    description=(
        "Универсальный поиск по единой строке (?q=): "
        "поддерживает аудитории ('1-709', '709'), ФИО ('Иванов'), "
        "логин абонента ('ivanov_ii'), IP-адрес ('10.100.0.144') "
        "или MAC-адрес (полный или хвост '77-D0'). "
        "Также поддерживает прямой выбор сотрудника по ?user_id=."
    )
)
async def search_memo(
    q: str | None = Query(
        None,
        description="Единая поисковая строка (аудитория 1-709, ФИО, логин, IP, MAC или его фрагмент)",
        examples=["1-709", "Иванов", "ivanov_ii", "77-D0", "10.100.0.144"]
    ),
    user_id: int | None = Query(
        None,
        description="Точный числовой ID пользователя в биллинге (для открытия выбранного кандидата)",
        examples=[11593]
    ),
    name: str | None = Query(None, description="Поиск по ФИО (совместимость)", include_in_schema=False),
    mac: str | None = Query(None, description="Поиск по MAC (совместимость)", include_in_schema=False),
    ip: str | None = Query(None, description="Поиск по IP (совместимость)", include_in_schema=False),
    service: BaseMemoService = Depends(get_memo_service),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> MemoResponseSchema | UserCandidatesResponseSchema:
    """
    Обработчик HTTP GET запроса:
    - Требует авторизации сотрудника.
    - При передаче user_id возвращает готовую памятку сотрудника.
    - При поиске по q (или устаревшим name/mac/ip):
      - Если найден 1 сотрудник — возвращает памятку (MemoResponseSchema).
      - Если найдено несколько — возвращает список кандидатов (UserCandidatesResponseSchema).
    - Автоматически сохраняет успешный запрос в историю поисков текущего пользователя.
    """
    # 1. Валидация входных параметров: ровно один критерий поиска
    params = [param for param in (q, name, mac, ip, user_id) if param is not None]

    if len(params) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Необходимо указать один критерий поиска: ?q=, ?user_id= (или ?name=, ?mac=, ?ip=)"
        )
    if len(params) > 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Должен быть указан ровно один критерий поиска. Нельзя совмещать одновременный поиск по нескольким полям."
        )

    # 2. Выполнение запроса через выбранную реализацию сервиса
    result: MemoResponseSchema | UserCandidatesResponseSchema | None = None
    try:
        if user_id is not None:
            result = await service.get_by_user_id(user_id)
        elif q is not None:
            result = await service.search(q)
        elif name is not None:
            result = await service.search_by_name(name)
        elif ip is not None:
            result = await service.search_by_ip(ip)
        elif mac is not None:
            result = await service.search_by_mac(mac)
    except ConnectionError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e)
        )

    # 3. Обработка случая, когда абонент не найден в базе
    if result is None:
        search_target = str(user_id) if user_id is not None else (q or name or ip or mac)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Сотрудник по запросу '{search_target}' не найден в базе биллинга."
        )

    # 4. Сохранение запроса в персональную историю поиска пользователя
    try:
        summary = None
        if isinstance(result, MemoResponseSchema):
            summary = f"{result.employee.full_name} (корп. {result.employee.building}, каб. {result.employee.room})"
        elif isinstance(result, UserCandidatesResponseSchema):
            summary = f"Найдено сотрудников: {len(result.candidates)}"

        raw_query = q or name or ip or mac or (f"ID={user_id}" if user_id else "")
        if raw_query and current_user:
            add_search_history(current_user["id"], raw_query, summary)
    except Exception:
        pass

    return result
