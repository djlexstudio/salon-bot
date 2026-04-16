FROM python:3.10-slim

WORKDIR /app

# Копируем зависимости и устанавливаем их
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь код
COPY . .

# Переменная порта для Render
ENV PORT=10000

# Команда запуска
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "10000"]
