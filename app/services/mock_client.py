import logging
from typing import Any

from app.schemas.memo import (
    EmployeeInfoSchema,
    MemoResponseSchema,
    NetworkInfoSchema,
    StatAccessSchema,
    UserCandidateSchema,
    UserCandidatesResponseSchema,
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

    _MOCK_USERS: list[dict[str, Any]] = [
        {
            "user_id": 1,
            "memo": MemoResponseSchema(
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
        },
        {
            "user_id": 2,
            "memo": MemoResponseSchema(
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
        },
        {
            "user_id": 3,
            "memo": MemoResponseSchema(
                employee=EmployeeInfoSchema(
                    full_name="Демина Виктория Юрьевна",
                    position="Специалист по документообороту",
                    building="1",
                    room="110",
                    phone="27-19",
                    tariff="100Гб",
                ),
                network=NetworkInfoSchema(
                    inventory_number="01340101",
                    ip_addresses=["10.224.0.136"],
                    mac_addresses=["A0-36-BC-11-22-33"],
                ),
                statistics=StatAccessSchema(
                    stat_server="utmweb.corp.local",
                    stat_login="vdemina",
                    stat_password="StatPassDemina1",
                ),
                vpn=VpnSettingsSchema(
                    vpn_server="vpn.corp.local",
                    vpn_type="PPTP",
                    vpn_encryption="без шифрования",
                    vpn_auth_method="MS-CHAP v2",
                    vpn_accounts=[
                        VpnAccountSchema(
                            login="vdemina",
                            password="VpnPassDemina1",
                            vpn_ip="172.22.10.15",
                            host_ip="10.224.0.136",
                        )
                    ],
                ),
            ),
        },
        {
            "user_id": 4,
            "memo": MemoResponseSchema(
                employee=EmployeeInfoSchema(
                    full_name="Демин Вячеслав Юрьевич",
                    position="Ведущий инженер",
                    building="2",
                    room="709",
                    phone="27-64",
                    tariff="100Гб",
                ),
                network=NetworkInfoSchema(
                    inventory_number="01340102",
                    ip_addresses=["10.146.0.104"],
                    mac_addresses=["B4-2E-99-44-55-66"],
                ),
                statistics=StatAccessSchema(
                    stat_server="utmweb.corp.local",
                    stat_login="vdemin",
                    stat_password="StatPassDemin2",
                ),
                vpn=VpnSettingsSchema(
                    vpn_server="vpn.corp.local",
                    vpn_type="PPTP",
                    vpn_encryption="без шифрования",
                    vpn_auth_method="MS-CHAP v2",
                    vpn_accounts=[
                        VpnAccountSchema(
                            login="vdemin",
                            password="094e537c",
                            vpn_ip="172.22.6.122",
                            host_ip="10.146.0.104",
                        )
                    ],
                ),
            ),
        },
    ]

    async def get_by_user_id(self, user_id: int) -> MemoResponseSchema | None:
        """Получение памятки по ID пользователя."""
        for u in self._MOCK_USERS:
            if u["user_id"] == user_id:
                return u["memo"]
        return None

    def _format_result(self, matched: list[dict[str, Any]]) -> MemoResponseSchema | UserCandidatesResponseSchema | None:
        if not matched:
            return None
        if len(matched) == 1:
            return matched[0]["memo"]
        candidates = [
            UserCandidateSchema(
                user_id=u["user_id"],
                full_name=u["memo"].employee.full_name,
                login=u["memo"].statistics.stat_login,
                building=u["memo"].employee.building,
                room=u["memo"].employee.room,
                phone=u["memo"].employee.phone,
                ip=u["memo"].network.ip_addresses[0] if u["memo"].network.ip_addresses else None,
            )
            for u in matched
        ]
        return UserCandidatesResponseSchema(candidates=candidates)

    async def search_by_name(self, name: str) -> MemoResponseSchema | UserCandidatesResponseSchema | None:
        """Поиск по подстроке в Ф.И.О."""
        query = name.strip().lower()
        matched = [
            u for u in self._MOCK_USERS
            if query in u["memo"].employee.full_name.lower() or query in u["memo"].statistics.stat_login.lower()
        ]
        return self._format_result(matched)

    async def search_by_ip(self, ip: str) -> MemoResponseSchema | UserCandidatesResponseSchema | None:
        """Поиск по IP-адресу."""
        query = ip.strip()
        matched = []
        for u in self._MOCK_USERS:
            memo = u["memo"]
            if query in memo.network.ip_addresses:
                matched.append(u)
                continue
            for acc in memo.vpn.vpn_accounts:
                if query == acc.vpn_ip or query == acc.host_ip:
                    matched.append(u)
                    break
        return self._format_result(matched)

    async def search_by_mac(self, mac: str) -> MemoResponseSchema | UserCandidatesResponseSchema | None:
        """Поиск по MAC-адресу."""
        clean_mac = mac.strip().upper().replace(":", "-")
        matched = [
            u for u in self._MOCK_USERS
            if clean_mac in u["memo"].network.mac_addresses
        ]
        return self._format_result(matched)
