FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Установка зависимостей Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копирование исходного кода приложения
COPY app/ app/
COPY run.py .

# Директория для хранения базы данных SQLite и аватарок пользователей
RUN mkdir -p /app/data/avatars
VOLUME ["/app/data"]

EXPOSE 8000

CMD ["python", "run.py"]
