import logging
from collections import deque
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1.memo import router as memo_router
from app.core.config import settings

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

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

app.include_router(memo_router, prefix="/api/v1")


@app.get("/", include_in_schema=False)
async def serve_index():
    """Отдает красивый веб-интерфейс поиска памятки."""
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"status": "online", "message": "Static index.html not found"}


@app.get("/health", tags=["Служебные"])
async def health_check():
    """Проверка доступности сервиса и текущего статуса конфигурации."""
    return {
        "status": "online",
        "app": settings.APP_TITLE,
        "version": settings.APP_VERSION,
        "mock_mode": settings.MOCK_MODE,
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


@app.post("/api/v1/system/shutdown", tags=["Служебные"])
async def shutdown_system():
    """Завершает работу фонового процесса приложения."""
    import os
    import threading
    import time

    def kill_process():
        time.sleep(0.4)
        os._exit(0)

    threading.Thread(target=kill_process, daemon=True).start()
    return {"status": "shutting_down"}

