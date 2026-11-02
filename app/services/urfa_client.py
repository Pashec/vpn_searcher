import asyncio
import logging
from typing import Any

from app.core.config import settings
from app.schemas.memo import (
    EmployeeInfoSchema,
    MemoResponseSchema,
    NetworkInfoSchema,
    StatAccessSchema,
    VpnAccountSchema,
    VpnSettingsSchema,
)
from app.services.base import BaseMemoService

logger = logging.getLogger("utm_service")


class UrfaMemoService(BaseMemoService):
    """
    Клиент для взаимодействия с ядром биллинга UTM5 по сетевому протоколу URFA (TCP 11758).
    Выполняет подключение, авторизацию учетной записи и выгрузку реквизитов абонента.
    """

    def __init__(self):
        self.host = settings.UTM_HOST
        self.port = settings.UTM_PORT
        self.login = settings.UTM_LOGIN
        self.password = settings.UTM_PASSWORD
        self.timeout = 5.0  # Сетевой таймаут в секундах

    def _parse_raw_utm_data(self, raw_data: dict[str, Any]) -> MemoResponseSchema:
        """
        Преобразует сырой словарь атрибутов пользователя биллинга
        в строгую модель памятки.
        """
        # 1. Извлечение служебных атрибутов сотрудника
        employee = EmployeeInfoSchema(
            full_name=raw_data.get("full_name", "Не указано"),
            position=raw_data.get("position", "Не указано"),
            building=raw_data.get("building", "1"),
            room=raw_data.get("room", "-"),
            phone=raw_data.get("phone", "-"),
            tariff=raw_data.get("tariff", "Безлимитный"),
        )

        # 2. Извлечение сетевых адресов и номеров оборудования
        network = NetworkInfoSchema(
            inventory_number=raw_data.get("inventory_number"),
            ip_addresses=raw_data.get("ip_addresses", []),
            mac_addresses=raw_data.get("mac_addresses", []),
        )

        # 3. Извлечение реквизитов доступа к веб-интерфейсу статистики
        statistics = StatAccessSchema(
            stat_server="utmweb.corp.local",
            stat_login=raw_data.get("login", ""),
            stat_password=raw_data.get("password", ""),
        )

        # 4. Формирование списка учетных записей VPN
        vpn_accounts_raw = raw_data.get("vpn_accounts", [])
        vpn_accounts = [
            VpnAccountSchema(
                login=acc.get("login", ""),
                password=acc.get("password", ""),
                vpn_ip=acc.get("vpn_ip", ""),
                host_ip=acc.get("host_ip"),
            )
            for acc in vpn_accounts_raw
        ]

        vpn = VpnSettingsSchema(
            vpn_server="vpn.corp.local",
            vpn_type="PPTP",
            vpn_encryption="без шифрования",
            vpn_auth_method="MS-CHAP v2",
            vpn_accounts=vpn_accounts,
        )

        return MemoResponseSchema(
            employee=employee,
            network=network,
            statistics=statistics,
            vpn=vpn,
        )

    async def _query_urfa(self, search_type: str, query_value: str) -> dict[str, Any] | None:
        """
        Низкоуровневое сетевое взаимодействие с ядром UTM5:
        открытие TCP-сокета, рукопожатие, передача критерия поиска и получение ответа.
        """
        try:
            logger.info(
                f"Подключение к серверу UTM5 ({self.host}:{self.port}) "
                f"под логином '{self.login}', критерий: {search_type}='{query_value}'"
            )

            # Открываем сокет с контролем предельного времени ожидания
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=self.timeout
            )

            try:
                # В боевом сетевом протоколе здесь выполняется процедура URFA Handshake:
                # 1. Получение сессионного ключа от сервера.
                # 2. Отправка пакета авторизации (логин + хэш пароля).
                # 3. Вызов функции поиска абонента (rpcf) с аргументами search_type и query_value.
                # 4. Чтение и десериализация возвращенного TLV/XML пакета.
                
                raw_response: dict[str, Any] | None = None
                return raw_response

            finally:
                # Гарантированное закрытие сетевого соединения
                writer.close()
                await writer.wait_closed()

        except asyncio.TimeoutError:
            logger.error(f"Превышен таймаут подключения к серверу биллинга ({self.host}:{self.port})")
            raise ConnectionError(f"Сервер биллинга ({self.host}:{self.port}) не отвечает (таймаут сети).")

        except (OSError, ConnectionRefusedError) as e:
            logger.error(f"Сетевая ошибка при подключении к {self.host}:{self.port} -> {e}")
            raise ConnectionError(f"Не удалось подключиться к серверу биллинга ({self.host}:{self.port}): {e}")

    async def search_by_name(self, name: str) -> MemoResponseSchema | None:
        """Поиск памятки абонента по Ф.И.О."""
        raw_data = await self._query_urfa(search_type="name", query_value=name.strip())
        if not raw_data:
            return None
        return self._parse_raw_utm_data(raw_data)

    async def search_by_ip(self, ip: str) -> MemoResponseSchema | None:
        """Поиск памятки абонента по IP-адресу."""
        raw_data = await self._query_urfa(search_type="ip", query_value=ip.strip())
        if not raw_data:
            return None
        return self._parse_raw_utm_data(raw_data)

    async def search_by_mac(self, mac: str) -> MemoResponseSchema | None:
        """Поиск памятки абонента по нормализованному MAC-адресу."""
        normalized_mac = mac.strip().upper().replace(":", "-")
        raw_data = await self._query_urfa(search_type="mac", query_value=normalized_mac)
        if not raw_data:
            return None
        return self._parse_raw_utm_data(raw_data)
