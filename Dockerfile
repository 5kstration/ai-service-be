FROM public.ecr.aws/docker/library/python:3.11-slim
WORKDIR /app

COPY requirements.txt .

# 1. torch CPU 버전 먼저 설치
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# 2. 나머지 패키지 설치
RUN pip config set global.timeout 120 && \
    pip install --no-cache-dir --timeout=120 --retries=5 -r requirements.txt

COPY . .

EXPOSE 8000
ENTRYPOINT ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]