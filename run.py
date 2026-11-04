import os
import sys
import threading
import time
import urllib.request
import webbrowser
import uvicorn


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


def open_browser(url: str = "http://127.0.0.1:8000"):
    """Автоматически открывает интерфейс в браузере после старта сервера."""
    time.sleep(1.0)
    try:
        webbrowser.open(url)
    except Exception:
        pass


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))

    # Если сервис уже запущен — просто открываем вкладку в браузере
    if is_already_running(port):
        print(f"\n[+] Сервис уже запущен! Открываем браузер: http://127.0.0.1:{port}\n")
        try:
            webbrowser.open(f"http://127.0.0.1:{port}")
        except Exception:
            pass
        sys.exit(0)

    # При локальном запуске (на ПК) автоматически открываем браузер
    threading.Thread(target=open_browser, args=(f"http://127.0.0.1:{port}",), daemon=True).start()

    print(f"\n=======================================================")
    print(f"  Сервис vpn_searcher успешно запущен!")
    print(f"  Адрес в браузере: http://127.0.0.1:{port} (или http://localhost:{port})")
    print(f"=======================================================\n")

    # host="0.0.0.0" позволяет подключаться как локально, так и с других ПК в сети / Docker
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, log_level="info")
