FROM python:3.9.23-slim
WORKDIR /app
RUN addgroup --system app && adduser --system --ingroup app app && chown -R app:app /app
 
# 의존성 먼저 복사 (캐시 활용)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
 
# 소스코드 복사
COPY --chown=app:app . .
 
EXPOSE 8000
USER app
 
ENTRYPOINT ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
