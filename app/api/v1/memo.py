from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.config import settings
from app.schemas.memo import MemoResponseSchema
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
    response_model=MemoResponseSchema,
    summary="Поиск памятки сотрудника",
    description="Позволяет найти памятку по одному из критериев: ФИО, MAC-адрес или IP-адрес рабочего места."
)
async def search_memo(
    name: str | None = Query(None, description="Ф.И.О. сотрудника (частичное совпадение)", examples=["Иванов"]),
    mac: str | None = Query(None, description="MAC-адрес сетевой платы", examples=["F0-22-1D-33-77-D0"]),
    ip: str | None = Query(None, description="Локальный IP или VPN IP", examples=["10.100.0.144"]),
    service: BaseMemoService = Depends(get_memo_service),
) -> MemoResponseSchema:
    """
    Обработчик HTTP GET запроса поиска памятки:
    - Проверяет обязательное наличие ровно одного параметра поиска.
    - Вызывает соответствующий поисковый метод сервиса.
    - Возвращает структурированную карточку сотрудника или ошибку 404/503.
    """
    # 1. Проверка входящих параметров запроса
    params = [param for param in (name, mac, ip) if param is not None]
    
    if len(params) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Необходимо указать один критерий поиска: ?name=, ?mac= или ?ip="
        )
    if len(params) > 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Должен быть указан ровно один критерий поиска. Нельзя совмещать одновременный поиск по нескольким полям."
        )

    # 2. Выполнение поиска через выбранный сервис
    memo: MemoResponseSchema | None = None
    try:
        if name is not None:
            memo = await service.search_by_name(name)
        elif ip is not None:
            memo = await service.search_by_ip(ip)
        elif mac is not None:
            memo = await service.search_by_mac(mac)
    except ConnectionError as e:
        # Сетевые ошибки связи с ядром биллинга возвращаются как 503 Service Unavailable
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e)
        )

    # 3. Обработка случая, когда абонент не найден
    if memo is None:
        search_target = name or ip or mac
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Памятка по запросу '{search_target}' не найдена в базе биллинга."
        )

    return memo
