# killers-bot — observer-only Telethon listener + Claude classifier + paper sim
FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY __init__.py /app/killers_bot/__init__.py
COPY classifier.py /app/killers_bot/classifier.py
COPY simulator.py /app/killers_bot/simulator.py
COPY observer.py /app/killers_bot/observer.py
COPY schema.sql /app/killers_bot/schema.sql

VOLUME ["/var/lib/killers"]

RUN useradd -u 1000 -m -s /sbin/nologin killers
USER killers

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

ENTRYPOINT ["python3", "-m", "killers_bot.observer"]
