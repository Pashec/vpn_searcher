from abc import ABC, abstractmethod

from app.schemas.memo import MemoResponseSchema, UserCandidatesResponseSchema


class BaseMemoService(ABC):
    """
    Абстрактный интерфейс сервиса получения памяток сотрудников.
    Определяет единый контракт как для тестового mock-клиента,
    так и для боевого подключения к ядру биллинга.
    """

    @abstractmethod
    async def search_by_name(self, name: str) -> MemoResponseSchema | UserCandidatesResponseSchema | None:
        """Поиск памятки по частичному совпадению в Ф.И.О. сотрудника."""
        pass

    @abstractmethod
    async def search_by_ip(self, ip: str) -> MemoResponseSchema | UserCandidatesResponseSchema | None:
        """Поиск памятки по локальному IP-адресу или IP из VPN-аккаунта."""
        pass

    @abstractmethod
    async def search_by_mac(self, mac: str) -> MemoResponseSchema | UserCandidatesResponseSchema | None:
        """Поиск памятки по MAC-адресу сетевого интерфейса."""
        pass

    @abstractmethod
    async def get_by_user_id(self, user_id: int) -> MemoResponseSchema | None:
        """Получение детальной памятки конкретного сотрудника по числовому ID пользователя."""
        pass
