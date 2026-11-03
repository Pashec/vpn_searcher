import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_missing_query_parameters(client):
    """Запрос без параметров должен возвращать HTTP 400 Bad Request."""
    response = client.get("/api/v1/memo/search")
    assert response.status_code == 400
    assert "Необходимо указать один критерий поиска" in response.json()["detail"]


def test_multiple_query_parameters(client):
    """Одновременный поиск по нескольким критериям запрещен (HTTP 400)."""
    response = client.get("/api/v1/memo/search?name=Иванов&ip=10.100.0.144")
    assert response.status_code == 400
    assert "Должен быть указан ровно один критерий поиска" in response.json()["detail"]


def test_mock_search_by_name(client):
    """Поиск по ФИО с единственным совпадением в тестовом режиме возвращает готовую памятку."""
    prev_mode = settings.MOCK_MODE
    try:
        settings.MOCK_MODE = True
        response = client.get("/api/v1/memo/search?name=Иванов")
        assert response.status_code == 200
        data = response.json()
        assert "employee" in data
        assert data["employee"]["full_name"] == "Иванов Иван Иванович"
        assert data["employee"]["building"] == "1"
        assert data["employee"]["room"] == "324"
        assert data["network"]["ip_addresses"] == ["10.100.0.144"]
        assert data["network"]["mac_addresses"] == ["F0-22-1D-33-77-D0"]
    finally:
        settings.MOCK_MODE = prev_mode


def test_mock_search_multiple_candidates(client):
    """При неоднозначном поиске (несколько совпадений) возвращается список кандидатов."""
    prev_mode = settings.MOCK_MODE
    try:
        settings.MOCK_MODE = True
        response = client.get("/api/v1/memo/search?name=Демин")
        assert response.status_code == 200
        data = response.json()
        assert "candidates" in data
        assert len(data["candidates"]) == 2

        # Проверяем структуру кандидата
        first = data["candidates"][0]
        assert "user_id" in first
        assert "full_name" in first
        assert "login" in first
        assert "building" in first
        assert "room" in first
        assert "phone" in first
    finally:
        settings.MOCK_MODE = prev_mode


def test_mock_get_by_user_id(client):
    """Прямое получение памятки сотрудника по числовому user_id."""
    prev_mode = settings.MOCK_MODE
    try:
        settings.MOCK_MODE = True
        response = client.get("/api/v1/memo/search?user_id=4")
        assert response.status_code == 200
        data = response.json()
        assert "employee" in data
        assert data["employee"]["full_name"] == "Демин Вячеслав Юрьевич"
        assert data["statistics"]["stat_login"] == "vdemin"
        assert len(data["vpn"]["vpn_accounts"]) > 0
    finally:
        settings.MOCK_MODE = prev_mode


def test_mock_search_not_found(client):
    """Поиск несуществующего пользователя в тестовом режиме возвращает 404."""
    prev_mode = settings.MOCK_MODE
    try:
        settings.MOCK_MODE = True
        response = client.get("/api/v1/memo/search?name=НесуществующийСотрудник")
        assert response.status_code == 404

        response_id = client.get("/api/v1/memo/search?user_id=999999")
        assert response_id.status_code == 404
    finally:
        settings.MOCK_MODE = prev_mode


def test_live_urfa_search_by_name(client):
    """Проверка живого поиска через боевой сервер биллинга."""
    prev_mode = settings.MOCK_MODE
    try:
        settings.MOCK_MODE = False
        response = client.get("/api/v1/memo/search?name=Баранов")
        assert response.status_code == 200
        data = response.json()
        assert "employee" in data
        assert "Баранов" in data["employee"]["full_name"]
        assert data["statistics"]["stat_login"] == "dbaranov"
        assert len(data["network"]["ip_addresses"]) > 0
    finally:
        settings.MOCK_MODE = prev_mode


def test_live_urfa_multiple_candidates(client):
    """Проверка живого поиска с несколькими совпадениями (список кандидатов)."""
    prev_mode = settings.MOCK_MODE
    try:
        settings.MOCK_MODE = False
        response = client.get("/api/v1/memo/search?name=Демин")
        assert response.status_code == 200
        data = response.json()
        assert "candidates" in data
        assert len(data["candidates"]) >= 2
        logins = [c["login"] for c in data["candidates"]]
        assert any("demin" in l for l in logins)
    finally:
        settings.MOCK_MODE = prev_mode


def test_live_urfa_vpn_passwords_extraction(client):
    """
    Проверка корректного извлечения паролей VPN через rpcf_get_document (0x4620).
    Пароль VPN не должен быть равен паролю от сайта статистики.
    """
    prev_mode = settings.MOCK_MODE
    try:
        settings.MOCK_MODE = False
        response = client.get("/api/v1/memo/search?name=Купчук")
        assert response.status_code == 200
        data = response.json()

        # Проверяем, что вернулась полная памятка
        assert "employee" in data
        assert "Купчук" in data["employee"]["full_name"]

        # Пароль статистики
        stat_password = data["statistics"]["stat_password"]
        assert stat_password == "710Pashec"

        # VPN учетные записи
        vpn_accounts = data["vpn"]["vpn_accounts"]
        assert len(vpn_accounts) >= 2

        acc0 = next((a for a in vpn_accounts if a["login"] == "pkupchuk"), None)
        assert acc0 is not None
        assert acc0["password"] == "0d8bccb4"
        assert acc0["password"] != stat_password
        assert acc0["vpn_ip"] == "172.22.254.18"

        acc1 = next((a for a in vpn_accounts if a["login"] == "pkupchuk2"), None)
        assert acc1 is not None
        assert acc1["password"] == "b4701231"
        assert acc1["password"] != stat_password
        assert acc1["vpn_ip"] == "172.22.254.24"
    finally:
        settings.MOCK_MODE = prev_mode
