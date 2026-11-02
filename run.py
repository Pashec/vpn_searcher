import io
import os
import sys
import threading
import time
import urllib.request
import webbrowser
import uvicorn

# Защита от аварийного завершения при запуске без консоли (PyInstaller --noconsole)
if sys.stdout is None:
    sys.stdout = io.StringIO()
if sys.stderr is None:
    sys.stderr = io.StringIO()

from app.main import app


def is_already_running(port: int = 8000) -> bool:
    """Проверяет, запущен ли наш сервис уже в фоне."""
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/health",
            headers={"User-Agent": "UTM_Launcher_Checker"}
        )
        with urllib.request.urlopen(req, timeout=0.8) as response:
            return response.status == 200
    except Exception:
        return False


def open_browser():
    """Автоматически открывает интерфейс в браузере после старта сервера."""
    time.sleep(1.0)
    webbrowser.open("http://127.0.0.1:8000")


if __name__ == "__main__":
    # Если процесс уже работает в фоне — не плодим дубли и не ломаем порт,
    # а просто мгновенно открываем вкладку браузера и выходим.
    if is_already_running(8000):
        webbrowser.open("http://127.0.0.1:8000")
        sys.exit(0)

    # Фоновое открытие браузера при первом холодном старте
    threading.Thread(target=open_browser, daemon=True).start()

    # Запуск сервера
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
