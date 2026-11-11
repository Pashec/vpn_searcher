from abc import ABC, abstractmethod

from app.schemas.memo import MemoResponseSchema, UserCandidatesResponseSchema


class BaseMemoService(ABC):
    """
    Абстрактный интерфейс сервиса получения памяток сотрудников.
    Определяет единый контракт взаимодействия с сервером биллинга.
    """

    @abstractmethod
    async def search(self, query: str) -> MemoResponseSchema | UserCandidatesResponseSchema | None:
        """
        Универсальный поиск по единой поисковой строке:
        - Аудитория / кабинет (формат '1-709', '2-709' или просто '709').
        - MAC-адрес (полный 'F0-22-1D-33-77-D0' или суффикс/фрагмент '77-D0').
        - Ф.И.О. сотрудника ('Иванов', 'Иван Иванов').
        - Учетная запись / логин абонента ('ivanov', 'petrov').
        - IP-адрес рабочего места или VPN ('10.100.0.144').
        """
        pass

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
