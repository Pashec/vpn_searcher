import hashlib
import hmac
import os
import secrets
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def get_db_path() -> Path:
    """
    Определяет путь к файлу базы данных SQLite:
    База данных размещается в каталоге data/ в корне проекта.
    """
    base_dir = Path(__file__).resolve().parent.parent.parent
    data_dir = base_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "vpn_searcher.db"


def get_avatars_dir() -> Path:
    """Определяет директорию для хранения загруженных аватарок пользователей."""
    base_dir = Path(__file__).resolve().parent.parent.parent
    avatars_dir = base_dir / "data" / "avatars"
    avatars_dir.mkdir(parents=True, exist_ok=True)
    return avatars_dir


def get_db_connection() -> sqlite3.Connection:
    """Создает соединение с SQLite базой данных со словарем строк (Row)."""
    conn = sqlite3.connect(str(get_db_path()), timeout=15.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


# ------------------------------------------------------------------------------
# Безопасное хеширование паролей (PBKDF2 HMAC SHA-256)
# ------------------------------------------------------------------------------

def hash_password(password: str) -> str:
    """Генерирует криптографически стойкий хеш пароля с солью."""
    salt = os.urandom(16)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
    return f"{salt.hex()}${key.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Проверяет пароль на соответствие сохраненному хешу."""
    try:
        salt_hex, key_hex = stored_hash.split("$")
        salt = bytes.fromhex(salt_hex)
        expected_key = bytes.fromhex(key_hex)
        computed_key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
        return hmac.compare_digest(computed_key, expected_key)
    except Exception:
        return False


# ------------------------------------------------------------------------------
# Инициализация схемы и сидирование суперпользователя
# ------------------------------------------------------------------------------

def init_db() -> None:
    """
    Создает необходимые таблицы при первом старте и добавляет
    учетную запись администратора по умолчанию (admin / admin), если она отсутствует.
    """
    with get_db_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                full_name TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                avatar_url TEXT DEFAULT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS search_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                query TEXT NOT NULL,
                result_summary TEXT DEFAULT NULL,
                searched_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_history_user_id ON search_history(user_id);
            CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(token);
        """)

        # Создание учетной записи администратора по умолчанию
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE username = 'admin'")
        if not cur.fetchone():
            now_iso = datetime.now(timezone.utc).isoformat()
            admin_pwd_hash = hash_password("admin")
            cur.execute("""
                INSERT INTO users (username, password_hash, full_name, role, avatar_url, is_active, created_at)
                VALUES ('admin', ?, 'Администратор системы', 'admin', NULL, 1, ?)
            """, (admin_pwd_hash, now_iso))
        conn.commit()


# ------------------------------------------------------------------------------
# Операции с пользователями
# ------------------------------------------------------------------------------

def get_user_by_id(user_id: int) -> dict[str, Any] | None:
    """Возвращает информацию о пользователе по его числовому ID."""
    with get_db_connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None


def get_user_by_username(username: str) -> dict[str, Any] | None:
    """Возвращает информацию о пользователе по логину."""
    with get_db_connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username.strip(),)).fetchone()
        return dict(row) if row else None


def get_all_users() -> list[dict[str, Any]]:
    """Возвращает список всех сотрудников для панели администратора."""
    with get_db_connection() as conn:
        rows = conn.execute("""
            SELECT 
                u.id, 
                u.username, 
                u.full_name, 
                u.role, 
                u.avatar_url, 
                u.is_active, 
                u.created_at,
                (SELECT COUNT(*) FROM search_history sh WHERE sh.user_id = u.id) as search_count
            FROM users u
            ORDER BY u.id ASC
        """).fetchall()
        return [dict(r) for r in rows]


def create_user(username: str, password: str, full_name: str, role: str = "user") -> dict[str, Any]:
    """Создает нового сотрудника в системе."""
    clean_login = username.strip().lower()
    pwd_hash = hash_password(password)
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO users (username, password_hash, full_name, role, avatar_url, is_active, created_at)
            VALUES (?, ?, ?, ?, NULL, 1, ?)
        """, (clean_login, pwd_hash, full_name.strip(), role, now_iso))
        user_id = cur.lastrowid
        conn.commit()
    user = get_user_by_id(user_id)
    assert user is not None
    return user


def update_user_password(user_id: int, new_password: str) -> bool:
    """Обновляет пароль пользователя (сброс админом или смена самим юзером)."""
    pwd_hash = hash_password(new_password)
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE users SET password_hash = ? WHERE id = ?", (pwd_hash, user_id))
        # Сбрасываем старые сессии пользователя при смене пароля
        cur.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        conn.commit()
        return cur.rowcount > 0


def update_user_avatar(user_id: int, avatar_url: str) -> bool:
    """Сохраняет путь к новой аватарке профиля."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE users SET avatar_url = ? WHERE id = ?", (avatar_url, user_id))
        conn.commit()
        return cur.rowcount > 0


def toggle_user_active(user_id: int) -> bool:
    """Переключает статус блокировки пользователя (активен / заблокирован)."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE users SET is_active = CASE WHEN is_active = 1 THEN 0 ELSE 1 END WHERE id = ?", (user_id,))
        conn.commit()
        return cur.rowcount > 0


def delete_user(user_id: int) -> bool:
    """Удаляет сотрудника из системы."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
        return cur.rowcount > 0


# ------------------------------------------------------------------------------
# Операции с сессиями авторизации
# ------------------------------------------------------------------------------

def create_session(user_id: int, duration_days: int = 30) -> str:
    """Генерирует случайный криптостойкий токен сессии и сохраняет его в БД."""
    token = secrets.token_urlsafe(36)
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=duration_days)
    with get_db_connection() as conn:
        conn.execute("""
            INSERT INTO sessions (token, user_id, created_at, expires_at)
            VALUES (?, ?, ?, ?)
        """, (token, user_id, now.isoformat(), expires.isoformat()))
        conn.commit()
    return token


def get_user_by_session_token(token: str) -> dict[str, Any] | None:
    """
    Проверяет валидность сессионного токена и возвращает активного пользователя.
    Если срок действия сессии истек, удаляет ее.
    """
    if not token:
        return None
    with get_db_connection() as conn:
        row = conn.execute("""
            SELECT u.*, s.expires_at 
            FROM sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token = ? AND u.is_active = 1
        """, (token,)).fetchone()
        if not row:
            return None

        # Проверка срока действия токена
        try:
            expires_at = datetime.fromisoformat(row["expires_at"])
            if datetime.now(timezone.utc) > expires_at:
                conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
                conn.commit()
                return None
        except Exception:
            return None

        user_dict = dict(row)
        user_dict.pop("password_hash", None)
        user_dict.pop("expires_at", None)
        return user_dict


def delete_session(token: str) -> bool:
    """Удаляет сессию при выходе из аккаунта (Logout)."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM sessions WHERE token = ?", (token,))
        conn.commit()
        return cur.rowcount > 0


# ------------------------------------------------------------------------------
# История поисковых запросов
# ------------------------------------------------------------------------------

def add_search_history(user_id: int, query: str, result_summary: str | None = None) -> None:
    """Записывает поисковый запрос в персональную историю сотрудника."""
    clean_q = query.strip()
    if not clean_q:
        return
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_db_connection() as conn:
        conn.execute("""
            INSERT INTO search_history (user_id, query, result_summary, searched_at)
            VALUES (?, ?, ?, ?)
        """, (user_id, clean_q, result_summary, now_iso))
        conn.commit()


def get_user_search_history(user_id: int, limit: int = 50) -> list[dict[str, Any]]:
    """Возвращает последние поисковые запросы сотрудника."""
    with get_db_connection() as conn:
        rows = conn.execute("""
            SELECT id, query, result_summary, searched_at
            FROM search_history
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT ?
        """, (user_id, limit)).fetchall()
        return [dict(r) for r in rows]


def clear_user_search_history(user_id: int) -> bool:
    """Очищает всю историю поиска конкретного сотрудника."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM search_history WHERE user_id = ?", (user_id,))
        conn.commit()
        return True


def delete_search_history_item(user_id: int, history_id: int) -> bool:
    """Удаляет одну запись из истории сотрудника."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM search_history WHERE id = ? AND user_id = ?", (history_id, user_id))
        conn.commit()
        return cur.rowcount > 0
