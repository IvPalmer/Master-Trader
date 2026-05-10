FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir fastapi==0.115.2 uvicorn[standard]==0.32.0 httpx==0.27.2

COPY app.py /app/app.py

EXPOSE 8088

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8088/healthz', timeout=3).read()" || exit 1

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8088", "--workers", "1"]
