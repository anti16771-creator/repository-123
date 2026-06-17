FROM python:3.11-slim

WORKDIR /app

# 시스템 패키지 (numpy/tensorflow 빌드용)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 의존성 먼저 설치 (캐시 활용)
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스 복사
COPY backend/ ./backend/
COPY frontend/ ./frontend/

WORKDIR /app/backend

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
