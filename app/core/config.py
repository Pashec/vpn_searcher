import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Конфигурация приложения.
    Загружает параметры из системного окружения или локального файла .env.
    """
    # Сетевые реквизиты ядра биллинга UTM5
    UTM_HOST: str = "10.0.0.1"
    UTM_PORT: int = 11758
    UTM_LOGIN: str = "staff"
    UTM_PASSWORD: str = ""

    # Корпоративные серверы
    VPN_SERVER: str = "vpn.dstu.local"
    STAT_SERVER: str = "utmweb.corp.local"

    # Метаданные сервиса
    APP_TITLE: str = "Pashec Inc. vpn_searcher"
    APP_VERSION: str = "v1.0.0"

    # Telegram Bot
    TG_BOT_TOKEN: str = ""
    TG_ADMIN_ID: int = 0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()
