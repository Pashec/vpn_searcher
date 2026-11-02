import os
import sys
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


def get_env_file_path() -> str:
    """
    Определяет путь к файлу .env:
    Если приложение собрано в .exe (PyInstaller), ищет .env рядом с .exe файлом.
    Иначе ищет в текущей рабочей директории проекта.
    """
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).parent
        candidate = exe_dir / ".env"
        if candidate.exists():
            return str(candidate)
    return ".env"


class Settings(BaseSettings):
    """
    Конфигурация приложения.
    Загружает параметры из системного окружения или локального файла .env.
    """
    # Сетевые параметры ядра UTM5
    UTM_HOST: str = "10.1.0.29"
    UTM_PORT: int = 11758
    UTM_LOGIN: str = "staff"
    UTM_PASSWORD: str = ""

    # Режим работы: True — тестовый mock, False — боевой опрос сервера UTM5
    MOCK_MODE: bool = False

    # Метаданные
    APP_TITLE: str = "Pashec Inc. vpn_searcher"
    APP_VERSION: str = "beta_v1.0.0"

    model_config = SettingsConfigDict(
        env_file=get_env_file_path(),
        env_file_encoding="utf-8",
        case_sensitive=True,
    )


settings = Settings()
