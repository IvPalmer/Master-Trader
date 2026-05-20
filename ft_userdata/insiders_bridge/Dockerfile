# ft-insiders-listener — Telethon listener for the Insiders Scalp Telegram
# group. Multi-deployment design: same image runs for our deployment and
# Eduardo's own copy bot later, differentiated entirely by env vars.
#
# Build:
#   docker build -t ft-insiders-listener:latest .
#
# Run (compose handles the env + volume mounts):
#   see ../docker-compose.prod.yml service `insiders-listener`

FROM python:3.13-slim

# Minimal deps — Telethon, aiohttp for receiver POSTs, no scientific stack
# (the classifier runs separately in the receiver container).
RUN pip install --no-cache-dir telethon==1.36.0 aiohttp==3.11.10

WORKDIR /app

# Copy ONLY the listener + its sibling modules (no Eduardo data, no classifiers
# — those live in other components / the receiver image).
COPY listener.py /app/insiders_bridge/listener.py
COPY __init__.py /app/insiders_bridge/__init__.py

# Sessions and event store mount as volumes; never bake into image layers.
VOLUME ["/var/lib/insiders"]

# Default to non-root user (UID 1000 — matches Freqtrade pattern).
RUN useradd -u 1000 -m -s /sbin/nologin listener
USER listener

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

ENTRYPOINT ["python3", "-m", "insiders_bridge.listener"]
