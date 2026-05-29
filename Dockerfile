FROM python:3.9.23-slim
WORKDIR /app

# 의존성 먼저 복사 (캐시 활용)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스코드 복사
COPY . .

EXPOSE 8000

ENTRYPOINT ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]