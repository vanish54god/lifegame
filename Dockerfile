FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY web ./web
COPY main.py .
# не запускаем от root
RUN useradd -m -u 1000 game && mkdir -p /data && chown game /data
USER game
CMD ["python", "main.py"]
