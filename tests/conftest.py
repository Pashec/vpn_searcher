from typing import Any
import pytest
from fastapi.testclient import TestClient

from app.api.v1.memo import get_memo_service
from app.main import app
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


class FakeMemoService(BaseMemoService):
    """
    Тестовый двойник сервиса поиска для изолированного запуска юнит-тестов
    без подключения к корпоративному серверу биллинга.
    """

    _TEST_USERS: list[dict[str, Any]] = [
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
                            login="petrov",
                            password="VpnPetrovKey2026",
                            vpn_ip="10.10.15.10",
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
                    full_name="Сидорова Анна Павловна",
                    position="Бухгалтер",
                    building="1",
                    room="205",
                    phone="45-12",
                    tariff="Стандартный",
                ),
                network=NetworkInfoSchema(
                    inventory_number="01340112",
                    ip_addresses=["10.100.2.15"],
                    mac_addresses=["A8-66-7F-89-99-EE"],
                ),
                statistics=StatAccessSchema(
                    stat_server="utmweb.corp.local",
                    stat_login="sidorova",
                    stat_password="SidorovaPass2026",
                ),
                vpn=VpnSettingsSchema(
                    vpn_server="vpn.corp.local",
                    vpn_type="PPTP",
                    vpn_encryption="без шифрования",
                    vpn_auth_method="MS-CHAP v2",
                    vpn_accounts=[],
                ),
            ),
        },
        {
            "user_id": 4,
            "memo": MemoResponseSchema(
                employee=EmployeeInfoSchema(
                    full_name="Сидоров Алексей Юрьевич",
                    position="Ведущий специалист",
                    building="2",
                    room="709",
                    phone="27-65",
                    tariff="Служебный",
                ),
                network=NetworkInfoSchema(
                    inventory_number="01340120",
                    ip_addresses=["10.100.2.80"],
                    mac_addresses=["BC-EE-7B-11-22-33"],
                ),
                statistics=StatAccessSchema(
                    stat_server="utmweb.corp.local",
                    stat_login="sidorov",
                    stat_password="SidorovPassword789",
                ),
                vpn=VpnSettingsSchema(
                    vpn_server="vpn.corp.local",
                    vpn_type="PPTP",
                    vpn_encryption="без шифрования",
                    vpn_auth_method="MS-CHAP v2",
                    vpn_accounts=[
                        VpnAccountSchema(
                            login="sidorov_vpn",
                            password="VpnSidorovSecure1",
                            vpn_ip="10.10.15.77",
                            host_ip="10.100.2.80",
                        )
                    ],
                ),
            ),
        },
    ]

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

    async def get_by_user_id(self, user_id: int) -> MemoResponseSchema | None:
        for u in self._TEST_USERS:
            if u["user_id"] == user_id:
                return u["memo"]
        return None

    async def search(self, query: str) -> MemoResponseSchema | UserCandidatesResponseSchema | None:
        raw = query.strip()
        if not raw:
            return None

        # 1. Формат корпус-аудитория (например, '2-709', '1-324')
        if "-" in raw and any(char.isdigit() for char in raw):
            parts = raw.split("-", 1)
            bldg, rm = parts[0].strip(), parts[1].strip()
            matched = [
                u for u in self._TEST_USERS
                if u["memo"].employee.building.lower() == bldg.lower()
                and u["memo"].employee.room.lower() == rm.lower()
            ]
            if matched:
                return self._format_result(matched)

        # 2. Номер аудитории/кабинета без корпуса ('709')
        if raw.isdigit():
            matched = [
                u for u in self._TEST_USERS
                if u["memo"].employee.room.lower() == raw.lower()
            ]
            if matched:
                return self._format_result(matched)

        # 3. MAC-адрес или его фрагмент/суффикс ('77-D0', 'CD-12', 'F0:22:1D:33:77:D0')
        clean_mac = raw.upper().replace(":", "-")
        matched = [
            u for u in self._TEST_USERS
            if any(clean_mac in m.upper().replace(":", "-") for m in u["memo"].network.mac_addresses)
        ]
        if matched:
            return self._format_result(matched)

        # 4. IP-адрес
        ip_matched = []
        for u in self._TEST_USERS:
            memo = u["memo"]
            if raw in memo.network.ip_addresses:
                ip_matched.append(u)
                continue
            for acc in memo.vpn.vpn_accounts:
                if raw == acc.vpn_ip or raw == acc.host_ip:
                    ip_matched.append(u)
                    break
        if ip_matched:
            return self._format_result(ip_matched)

        # 5. ФИО или логин
        q_lower = raw.lower()
        matched = [
            u for u in self._TEST_USERS
            if q_lower in u["memo"].employee.full_name.lower() or q_lower in u["memo"].statistics.stat_login.lower()
        ]
        return self._format_result(matched)

    async def search_by_name(self, name: str) -> MemoResponseSchema | UserCandidatesResponseSchema | None:
        return await self.search(name)

    async def search_by_ip(self, ip: str) -> MemoResponseSchema | UserCandidatesResponseSchema | None:
        return await self.search(ip)

    async def search_by_mac(self, mac: str) -> MemoResponseSchema | UserCandidatesResponseSchema | None:
        return await self.search(mac)


@pytest.fixture
def fake_service():
    return FakeMemoService()


@pytest.fixture
def client(fake_service):
    app.dependency_overrides[get_memo_service] = lambda: fake_service
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(get_memo_service, None)


@pytest.fixture
def auth_headers(client):
    resp = client.post("/api/v1/auth/login", json={
        "username": "admin",
        "password": "admin",
    })
    token = resp.json()["token"]
    return {"Authorization": f"Bearer {token}"}
