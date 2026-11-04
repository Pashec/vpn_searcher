import io
import pytest

from app.main import app


def test_admin_login_success(client):
    """Проверка входа под учетной записью администратора admin / admin."""
    resp = client.post("/api/v1/auth/login", json={
        "username": "admin",
        "password": "admin",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "token" in data
    assert len(data["token"]) > 20
    assert data["user"]["username"] == "admin"
    assert data["user"]["role"] == "admin"


def test_login_invalid_credentials(client):
    """Попытка входа с неверным паролем возвращает HTTP 401."""
    resp = client.post("/api/v1/auth/login", json={
        "username": "admin",
        "password": "wrong_password_123",
    })
    assert resp.status_code == 401
    assert "Неверное имя пользователя или пароль" in resp.json()["detail"]


def test_auth_me_profile(client):
    """Получение профиля текущего пользователя по Bearer токену."""
    login_resp = client.post("/api/v1/auth/login", json={
        "username": "admin",
        "password": "admin",
    })
    token = login_resp.json()["token"]

    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    profile = resp.json()
    assert profile["username"] == "admin"
    assert profile["role"] == "admin"


def test_search_history_flow(client):
    """Проверка фиксации поисковых запросов в персональной истории и ее очистки."""
    # 1. Авторизация
    login_resp = client.post("/api/v1/auth/login", json={
        "username": "admin",
        "password": "admin",
    })
    token = login_resp.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Очистка старой истории перед тестом
    client.delete("/api/v1/history", headers=headers)

    # 3. Выполнение поиска
    search_resp = client.get("/api/v1/memo/search?q=1-324", headers=headers)
    assert search_resp.status_code == 200

    # 4. Проверка записи в истории
    hist_resp = client.get("/api/v1/history", headers=headers)
    assert hist_resp.status_code == 200
    history_items = hist_resp.json()
    assert len(history_items) >= 1
    assert history_items[0]["query"] == "1-324"

    # 5. Очистка истории
    del_resp = client.delete("/api/v1/history", headers=headers)
    assert del_resp.status_code == 200

    hist_after = client.get("/api/v1/history", headers=headers)
    assert len(hist_after.json()) == 0


def test_admin_user_management_and_password_reset(client):
    """
    Проверка полного цикла управления сотрудниками администратором:
    1. Создание нового сотрудника.
    2. Вход под новым сотрудником.
    3. Сброс пароля сотрудника администратором.
    4. Проверка блокировки входа по старому паролю и успешного входа по новому.
    5. Запрет доступа обычного сотрудника к панели администратора (HTTP 403).
    """
    # 1. Вход администратора
    admin_login = client.post("/api/v1/auth/login", json={
        "username": "admin",
        "password": "admin",
    })
    admin_token = admin_login.json()["token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # 2. Создание нового сотрудника
    test_user_login = "engineer_test"
    # Удаляем на случай повторного запуска
    all_users = client.get("/api/v1/admin/users", headers=admin_headers).json()
    for u in all_users:
        if u["username"] == test_user_login:
            client.delete(f"/api/v1/admin/users/{u['id']}", headers=admin_headers)

    create_resp = client.post("/api/v1/admin/users", headers=admin_headers, json={
        "username": test_user_login,
        "password": "InitialPassword1",
        "full_name": "Инженеров Инженер Инженерович",
        "role": "user",
    })
    assert create_resp.status_code == 201
    new_user_data = create_resp.json()
    new_user_id = new_user_data["id"]

    # 3. Вход под новым сотрудником
    user_login = client.post("/api/v1/auth/login", json={
        "username": test_user_login,
        "password": "InitialPassword1",
    })
    assert user_login.status_code == 200
    user_token = user_login.json()["token"]
    user_headers = {"Authorization": f"Bearer {user_token}"}

    # 4. Проверка запрета доступа к админке для обычного пользователя
    forbidden_resp = client.get("/api/v1/admin/users", headers=user_headers)
    assert forbidden_resp.status_code == 403

    # 5. Сброс пароля сотрудника администратором
    reset_resp = client.post(
        f"/api/v1/admin/users/{new_user_id}/reset-password",
        headers=admin_headers,
        json={"new_password": "NewSecretPassword2026"}
    )
    assert reset_resp.status_code == 200

    # 6. Старый пароль больше не должен работать
    failed_login = client.post("/api/v1/auth/login", json={
        "username": test_user_login,
        "password": "InitialPassword1",
    })
    assert failed_login.status_code == 401

    # 7. Новый пароль успешно работает
    success_login = client.post("/api/v1/auth/login", json={
        "username": test_user_login,
        "password": "NewSecretPassword2026",
    })
    assert success_login.status_code == 200

    # Очистка за собой
    client.delete(f"/api/v1/admin/users/{new_user_id}", headers=admin_headers)


def test_avatar_upload(client):
    """Проверка загрузки и сохранения файла аватарки сотрудника."""
    login_resp = client.post("/api/v1/auth/login", json={
        "username": "admin",
        "password": "admin",
    })
    token = login_resp.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Минимальный PNG-файл (1x1 пиксель)
    dummy_png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\rIDATx\x9cc`\x00\x00\x00"
        b"\x02\x00\x01H\xaf\xa4q\x00\x00\x00\x00IEND\xaeB`\x82"
    )

    resp = client.post(
        "/api/v1/auth/avatar",
        headers=headers,
        files={"file": ("test_avatar.png", io.BytesIO(dummy_png), "image/png")}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "avatar_url" in data
    assert data["avatar_url"].startswith("/static/avatars/avatar_")

    # Проверяем, что в профиле обновился URL аватарки
    profile_resp = client.get("/api/v1/auth/me", headers=headers)
    assert profile_resp.json()["avatar_url"] == data["avatar_url"]
