FROM python:3.9.23-slim
WORKDIR /app

COPY requirements.txt .

# 1. torch CPU 버전 먼저 설치 (sentence-transformers가 GPU 버전 끌어오는 거 방지)
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# 2. 나머지 패키지 설치 (torch 이미 있으므로 GPU 버전 설치 안 함)
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000
ENTRYPOINT ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]