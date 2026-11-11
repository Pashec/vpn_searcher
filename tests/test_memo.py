import pytest

from app.api.v1.memo import get_memo_service
from app.core.config import settings
from app.main import app


def is_live_server_available() -> bool:
    """Проверяет возможность полноценного URFA-рукопожатия с боевым сервером биллинга."""
    try:
        from app.services.urfa_client import UrfaConnection
        conn = UrfaConnection(
            host=settings.UTM_HOST,
            port=settings.UTM_PORT,
            login=settings.UTM_LOGIN,
            password=settings.UTM_PASSWORD,
            timeout=1.5,
        )
        conn.connect()
        conn.close()
        return True
    except Exception:
        return False


def test_missing_query_parameters(client, auth_headers):
    """Запрос без параметров должен возвращать HTTP 400 Bad Request."""
    response = client.get("/api/v1/memo/search", headers=auth_headers)
    assert response.status_code == 400
    assert "Необходимо указать один критерий поиска" in response.json()["detail"]


def test_multiple_query_parameters(client, auth_headers):
    """Одновременный поиск по нескольким критериям запрещен (HTTP 400)."""
    response = client.get("/api/v1/memo/search?name=Иванов&ip=10.100.0.144", headers=auth_headers)
    assert response.status_code == 400
    assert "Должен быть указан ровно один критерий поиска" in response.json()["detail"]


def test_search_unauthorized(client):
    """Попытка поиска без авторизации возвращает HTTP 401."""
    response = client.get("/api/v1/memo/search?q=1-324")
    assert response.status_code == 401


def test_search_by_name(client, auth_headers):
    """Поиск по ФИО с единственным совпадением возвращает готовую памятку."""
    response = client.get("/api/v1/memo/search?name=Иванов", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert "employee" in data
    assert data["employee"]["full_name"] == "Иванов Иван Иванович"
    assert data["employee"]["building"] == "1"
    assert data["employee"]["room"] == "324"
    assert data["network"]["ip_addresses"] == ["10.100.0.144"]
    assert data["network"]["mac_addresses"] == ["F0-22-1D-33-77-D0"]


def test_search_multiple_candidates(client, auth_headers):
    """При неоднозначном поиске (несколько совпадений) возвращается список кандидатов."""
    response = client.get("/api/v1/memo/search?name=Сидоров", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert "candidates" in data
    assert len(data["candidates"]) == 2

    first = data["candidates"][0]
    assert "user_id" in first
    assert "full_name" in first
    assert "login" in first
    assert "building" in first
    assert "room" in first
    assert "phone" in first


def test_get_by_user_id(client, auth_headers):
    """Прямое получение памятки сотрудника по числовому user_id."""
    response = client.get("/api/v1/memo/search?user_id=4", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert "employee" in data
    assert data["employee"]["full_name"] == "Сидоров Алексей Юрьевич"
    assert data["statistics"]["stat_login"] == "sidorov"
    assert len(data["vpn"]["vpn_accounts"]) > 0


def test_search_not_found(client, auth_headers):
    """Поиск несуществующего пользователя возвращает 404."""
    response = client.get("/api/v1/memo/search?q=НесуществующийСотрудник", headers=auth_headers)
    assert response.status_code == 404

    response_id = client.get("/api/v1/memo/search?user_id=999999", headers=auth_headers)
    assert response_id.status_code == 404


# ------------------------------------------------------------------------------
# Тесты единой поисковой строки (?q=)
# ------------------------------------------------------------------------------

def test_unified_search_by_room_building(client, auth_headers):
    """Единый поиск по формату 'корпус-аудитория' (например, '2-709' или '1-324')."""
    resp_multi = client.get("/api/v1/memo/search?q=2-709", headers=auth_headers)
    assert resp_multi.status_code == 200
    data_multi = resp_multi.json()
    assert "candidates" in data_multi
    assert len(data_multi["candidates"]) == 2
    logins = [c["login"] for c in data_multi["candidates"]]
    assert "petrov_ps" in logins
    assert "sidorov" in logins

    resp_single = client.get("/api/v1/memo/search?q=1-324", headers=auth_headers)
    assert resp_single.status_code == 200
    data_single = resp_single.json()
    assert "employee" in data_single
    assert data_single["employee"]["full_name"] == "Иванов Иван Иванович"
    assert data_single["employee"]["building"] == "1"
    assert data_single["employee"]["room"] == "324"


def test_unified_search_by_room_only(client, auth_headers):
    """Единый поиск по номеру кабинета/аудитории без корпуса ('709')."""
    resp = client.get("/api/v1/memo/search?q=709", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "candidates" in data
    assert len(data["candidates"]) == 2


def test_unified_search_by_mac_suffix(client, auth_headers):
    """Единый поиск по фрагменту/суффиксу MAC-адреса (например, '77-D0' или 'CD-12')."""
    resp_ivanov = client.get("/api/v1/memo/search?q=77-D0", headers=auth_headers)
    assert resp_ivanov.status_code == 200
    data = resp_ivanov.json()
    assert "employee" in data
    assert data["employee"]["full_name"] == "Иванов Иван Иванович"
    assert "F0-22-1D-33-77-D0" in data["network"]["mac_addresses"]

    resp_petrov = client.get("/api/v1/memo/search?q=CD-12", headers=auth_headers)
    assert resp_petrov.status_code == 200
    data_petrov = resp_petrov.json()
    assert "employee" in data_petrov
    assert data_petrov["employee"]["full_name"] == "Петров Петр Сергеевич"


def test_unified_search_by_unique_login(client, auth_headers):
    """Единый поиск по уникальному логину учетной записи абонента ('ivanov_ii')."""
    resp = client.get("/api/v1/memo/search?q=ivanov_ii", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "employee" in data
    assert data["employee"]["full_name"] == "Иванов Иван Иванович"
    assert data["statistics"]["stat_login"] == "ivanov_ii"


def test_unified_search_by_partial_login(client, auth_headers):
    """Единый поиск по частичному логину с несколькими кандидатами ('sidorov' -> sidorov, sidorova)."""
    resp = client.get("/api/v1/memo/search?q=sidorov", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "candidates" in data
    assert len(data["candidates"]) == 2
    logins = [c["login"] for c in data["candidates"]]
    assert "sidorov" in logins
    assert "sidorova" in logins


def test_unified_search_by_full_name(client, auth_headers):
    """Единый поиск по Ф.И.О. ('Иван Иванов')."""
    resp = client.get("/api/v1/memo/search?q=Иван Иванов", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "employee" in data
    assert data["employee"]["full_name"] == "Иванов Иван Иванович"


def test_unified_search_by_ip(client, auth_headers):
    """Единый поиск по рабочему IP-адресу ('10.100.0.144')."""
    resp = client.get("/api/v1/memo/search?q=10.100.0.144", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "employee" in data
    assert data["employee"]["full_name"] == "Иванов Иван Иванович"


# ------------------------------------------------------------------------------
# Тесты боевого сервера биллинга (запускаются при доступности UTM5)
# ------------------------------------------------------------------------------

@pytest.mark.skipif(not is_live_server_available(), reason="Боевой сервер биллинга недоступен из текущей сети")
def test_live_urfa_search_by_name(client, auth_headers):
    """Проверка живого поиска через боевой сервер биллинга."""
    app.dependency_overrides.pop(get_memo_service, None)
    response = client.get("/api/v1/memo/search?name=Баранов", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert "employee" in data
    assert "Баранов" in data["employee"]["full_name"]
    assert data["statistics"]["stat_login"] == "dbaranov"
    assert len(data["network"]["ip_addresses"]) > 0


@pytest.mark.skipif(not is_live_server_available(), reason="Боевой сервер биллинга недоступен из текущей сети")
def test_live_urfa_multiple_candidates(client, auth_headers):
    """Проверка живого поиска с несколькими совпадениями (список кандидатов)."""
    app.dependency_overrides.pop(get_memo_service, None)
    response = client.get("/api/v1/memo/search?name=Иванов", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert "candidates" in data
    assert len(data["candidates"]) >= 2
    logins = [c["login"] for c in data["candidates"]]
    assert any("ivanov" in l for l in logins)


@pytest.mark.skipif(not is_live_server_available(), reason="Боевой сервер биллинга недоступен из текущей сети")
def test_live_urfa_vpn_passwords_extraction(client, auth_headers):
    """
    Проверка корректного извлечения паролей VPN через rpcf_get_document (0x4620).
    """
    app.dependency_overrides.pop(get_memo_service, None)
    response = client.get("/api/v1/memo/search?name=Баранов", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()

    assert "employee" in data
    assert "Баранов" in data["employee"]["full_name"]

    vpn_accounts = data["vpn"]["vpn_accounts"]
    if vpn_accounts:
        assert vpn_accounts[0]["password"] is not None
        assert len(vpn_accounts[0]["password"]) > 0
