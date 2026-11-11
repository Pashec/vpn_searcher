import logging
from collections import deque
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1.admin import router as admin_router
from app.api.v1.auth import router as auth_router
from app.api.v1.history import router as history_router
from app.api.v1.memo import router as memo_router
from app.core.config import settings
from app.core.database import get_avatars_dir, init_db

# ------------------------------------------------------------------------------
# In-Memory буфер логов для скрытой консоли в веб-интерфейсе
# ------------------------------------------------------------------------------
class InMemoryLogHandler(logging.Handler):
    """Хранит последние 150 записей логов для просмотра в скрытом окне."""
    def __init__(self, max_records: int = 150):
        super().__init__()
        self.records: deque = deque(maxlen=max_records)

    def emit(self, record: logging.LogRecord):
        try:
            entry = {
                "time": datetime.fromtimestamp(record.created).strftime("%H:%M:%S"),
                "level": record.levelname,
                "name": record.name,
                "msg": self.format(record),
            }
            self.records.append(entry)
        except Exception:
            self.handleError(record)

    def clear(self):
        self.records.clear()


memory_logger = InMemoryLogHandler()
memory_logger.setFormatter(logging.Formatter("%(message)s"))
memory_logger.setLevel(logging.INFO)

# Подключаем перехватчик ко всем ключевым логгерам
logging.getLogger().addHandler(memory_logger)
logging.getLogger("uvicorn").addHandler(memory_logger)
logging.getLogger("uvicorn.access").addHandler(memory_logger)
logging.getLogger("utm_service").addHandler(memory_logger)


# ------------------------------------------------------------------------------
# Приложение FastAPI
# ------------------------------------------------------------------------------
STATIC_DIR = Path(__file__).parent / "static"
AVATARS_DIR = get_avatars_dir()

# Инициализируем базу данных пользователей и суперпользователя
init_db()

app = FastAPI(
    title=settings.APP_TITLE,
    version=settings.APP_VERSION,
    description="Легковесный веб-сервис для поиска памяток сотрудников и параметров корпоративной сети.",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if AVATARS_DIR.exists():
    app.mount("/static/avatars", StaticFiles(directory=AVATARS_DIR), name="avatars")

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

app.include_router(auth_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/api/v1")
app.include_router(history_router, prefix="/api/v1")
app.include_router(memo_router, prefix="/api/v1")


@app.get("/", include_in_schema=False)
async def serve_index():
    """Отдает красивый веб-интерфейс поиска памятки."""
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"status": "online", "message": "Static index.html not found"}


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """Отдает иконку вкладки для браузера."""
    favicon_file = STATIC_DIR / "favicon.svg"
    if favicon_file.exists():
        return FileResponse(favicon_file, media_type="image/svg+xml")
    return {"status": "not found"}


@app.get("/health", tags=["Служебные"])
async def health_check():
    """Проверка доступности сервиса."""
    return {
        "status": "online",
        "app": settings.APP_TITLE,
        "version": settings.APP_VERSION,
    }


@app.get("/api/v1/system/logs", tags=["Служебные"])
async def get_system_logs():
    """Возвращает историю последних системных логов для встроенной консоли."""
    return list(memory_logger.records)


@app.delete("/api/v1/system/logs", tags=["Служебные"])
async def clear_system_logs():
    """Очищает историю системных логов."""
    memory_logger.clear()
    return {"status": "cleared"}
