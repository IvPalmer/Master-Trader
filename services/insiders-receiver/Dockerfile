FROM python:3.13-slim

RUN pip install --no-cache-dir \
    fastapi==0.115.0 \
    uvicorn[standard]==0.32.0 \
    aiohttp==3.11.10 \
    pydantic==2.10.0

WORKDIR /app

# Receiver app
COPY app/ /app/app/

# Reuse the rule classifier from the master-trader insiders_bridge package.
# Mounted as /app/insiders_bridge at runtime (read-only) so we don't
# bake another copy here.
VOLUME ["/var/lib/insiders"]

RUN useradd -u 1000 -m -s /sbin/nologin receiver
USER receiver

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

EXPOSE 8089

ENTRYPOINT ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8089"]
