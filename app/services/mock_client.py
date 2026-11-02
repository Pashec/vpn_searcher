import logging
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


class MockMemoService(BaseMemoService):
    """
    Тестовый сервис с изолированными данными сотрудников в оперативной памяти.
    Используется для локальной разработки, отладки интерфейса и юнит-тестирования.
    """

    # Тестовые данные абонентов для проверки всех сценариев поиска
    _MOCK_DATA: list[MemoResponseSchema] = [
        MemoResponseSchema(
            employee=EmployeeInfoSchema(
                full_name="Иванов Иван Иванович",
                position="Инженер отдела технической поддержки",
                building="1",
                room="324",
                phone="12-34",
                tariff="Безлимитный",
            ),
            network=NetworkInfoSchema(
                inventory_number="01340056",
                ip_addresses=["10.100.0.144"],
                mac_addresses=["F0-22-1D-33-77-D0"],
            ),
            statistics=StatAccessSchema(
                stat_server="utmweb.corp.local",
                stat_login="ivanov_ii",
                stat_password="WebPassword123",
            ),
            vpn=VpnSettingsSchema(
                vpn_server="vpn.corp.local",
                vpn_type="PPTP",
                vpn_encryption="без шифрования",
                vpn_auth_method="MS-CHAP v2",
                vpn_accounts=[
                    VpnAccountSchema(
                        login="vpn_ivanov",
                        password="VpnSecretPass1",
                        vpn_ip="10.10.15.42",
                        host_ip="10.100.0.144",
                    )
                ],
            ),
        ),
        MemoResponseSchema(
            employee=EmployeeInfoSchema(
                full_name="Петров Петр Сергеевич",
                position="Начальник отдела сетевой инфраструктуры",
                building="2",
                room="709",
                phone="27-64",
                tariff="Служебный",
            ),
            network=NetworkInfoSchema(
                inventory_number="01340099",
                ip_addresses=["10.100.1.50", "10.100.1.51"],
                mac_addresses=["E4-5F-01-AB-CD-12"],
            ),
            statistics=StatAccessSchema(
                stat_server="utmweb.corp.local",
                stat_login="petrov_ps",
                stat_password="PetrovStatPass!",
            ),
            vpn=VpnSettingsSchema(
                vpn_server="vpn.corp.local",
                vpn_type="PPTP",
                vpn_encryption="без шифрования",
                vpn_auth_method="MS-CHAP v2",
                vpn_accounts=[
                    VpnAccountSchema(
                        login="vpn_petrov",
                        password="VpnSecretPass2",
                        vpn_ip="10.10.15.99",
                        host_ip="10.100.1.50",
                    )
                ],
            ),
        ),
    ]

    async def search_by_name(self, name: str) -> MemoResponseSchema | None:
        """Поиск по подстроке в Ф.И.О. без учета регистра символов."""
        query = name.strip().lower()
        logger.info(f"[MOCK] Поиск сотрудника по имени: '{name}'")
        for item in self._MOCK_DATA:
            if query in item.employee.full_name.lower():
                logger.info(f"[MOCK] Найден абонент: {item.employee.full_name}")
                return item
        logger.warning(f"[MOCK] Абонент с именем '{name}' не найден")
        return None

    async def search_by_ip(self, ip: str) -> MemoResponseSchema | None:
        """Поиск по совпадению с локальным IP-адресом ПК или статическим IP VPN."""
        query = ip.strip()
        logger.info(f"[MOCK] Поиск сотрудника по IP-адресу: '{ip}'")
        for item in self._MOCK_DATA:
            if query in item.network.ip_addresses:
                logger.info(f"[MOCK] Найден абонент по локальному IP: {item.employee.full_name}")
                return item
            for acc in item.vpn.vpn_accounts:
                if query == acc.vpn_ip or query == acc.host_ip:
                    logger.info(f"[MOCK] Найден абонент по VPN IP: {item.employee.full_name}")
                    return item
        logger.warning(f"[MOCK] Абонент с IP '{ip}' не найден")
        return None

    async def search_by_mac(self, mac: str) -> MemoResponseSchema | None:
        """Поиск по MAC-адресу с предварительной нормализацией разделителей и регистра."""
        normalized_query = mac.strip().upper().replace(":", "-")
        logger.info(f"[MOCK] Поиск сотрудника по MAC-адресу: '{mac}' -> '{normalized_query}'")
        for item in self._MOCK_DATA:
            if normalized_query in item.network.mac_addresses:
                logger.info(f"[MOCK] Найден абонент по MAC: {item.employee.full_name}")
                return item
        logger.warning(f"[MOCK] Абонент с MAC '{normalized_query}' не найден")
        return None
