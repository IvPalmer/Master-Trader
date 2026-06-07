FROM python:3.13-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    fastapi==0.115.5 \
    "uvicorn[standard]"==0.32.1 \
    aiohttp==3.11.10 \
    pydantic==2.10.3

COPY app /app/app

VOLUME ["/var/lib/killers"]

RUN useradd -u 1000 -m -s /sbin/nologin receiver
USER receiver

ENV PYTHONUNBUFFERED=1

EXPOSE 8089

ENTRYPOINT ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8089", "--log-level", "info"]
