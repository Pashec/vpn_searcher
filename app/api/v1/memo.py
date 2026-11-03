from typing import Union

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.config import settings
from app.schemas.memo import MemoResponseSchema, UserCandidatesResponseSchema
from app.services.base import BaseMemoService
from app.services.mock_client import MockMemoService
from app.services.urfa_client import UrfaMemoService

router = APIRouter(prefix="/memo", tags=["Памятка сотрудника"])


def get_memo_service() -> BaseMemoService:
    """
    Фабрика зависимостей (Dependency Injection).
    Определяет, какой сервис отдавать роутеру в зависимости от флага MOCK_MODE в .env.
    """
    if settings.MOCK_MODE:
        return MockMemoService()
    return UrfaMemoService()


@router.get(
    "/search",
    response_model=Union[MemoResponseSchema, UserCandidatesResponseSchema],
    summary="Поиск памятки или списка кандидатов",
    description="Позволяет найти памятку по ФИО, MAC-адресу, IP-адресу или напрямую по user_id."
)
async def search_memo(
    name: str | None = Query(None, description="Ф.И.О. сотрудника (частичное совпадение)", examples=["Купчук"]),
    mac: str | None = Query(None, description="MAC-адрес сетевой платы", examples=["30-85-A9-9C-D2-8E"]),
    ip: str | None = Query(None, description="Локальный IP или VPN IP", examples=["10.146.0.115"]),
    user_id: int | None = Query(None, description="Точный числовой ID пользователя в биллинге", examples=[11593]),
    service: BaseMemoService = Depends(get_memo_service),
) -> MemoResponseSchema | UserCandidatesResponseSchema:
    """
    Обработчик HTTP GET запроса:
    - При указании user_id сразу выгружает готовую памятку сотрудника.
    - При поиске по name/mac/ip:
      - Если найден 1 сотрудник — возвращает памятку (MemoResponseSchema).
      - Если найдено несколько — возвращает список кандидатов (UserCandidatesResponseSchema).
    """
    # 1. Проверка входящих параметров запроса
    params = [param for param in (name, mac, ip, user_id) if param is not None]

    if len(params) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Необходимо указать один критерий поиска: ?name=, ?mac=, ?ip= или ?user_id="
        )
    if len(params) > 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Должен быть указан ровно один критерий поиска. Нельзя совмещать одновременный поиск по нескольким полям."
        )

    # 2. Выполнение запроса через выбранный сервис
    result: MemoResponseSchema | UserCandidatesResponseSchema | None = None
    try:
        if user_id is not None:
            result = await service.get_by_user_id(user_id)
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

    # 3. Обработка случая, когда абонент не найден
    if result is None:
        search_target = str(user_id) if user_id is not None else (name or ip or mac)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Сотрудник по запросу '{search_target}' не найден в базе биллинга."
        )

    return result
