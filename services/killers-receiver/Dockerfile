FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app /app/app
# Open-risk monitor (#105); host cron runs it in this container.
COPY warden /app/warden

# The state directory must exist, owned by the runtime user, BEFORE it is
# declared a volume (#112). Docker seeds a new, empty named volume from the
# image's directory, ownership included, so a fresh killers_receiver_state /
# insiders_receiver_state is writable by uid 1000. Without this the mount
# point came up root:root 755 and init_db crash-looped on "unable to open
# database file". A volume that already holds data is not touched.
RUN useradd -u 1000 -m -s /sbin/nologin receiver \
    && mkdir -p /var/lib/killers \
    && chown receiver:receiver /var/lib/killers

VOLUME ["/var/lib/killers"]

USER receiver

ENV PYTHONUNBUFFERED=1

EXPOSE 8089

ENTRYPOINT ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8089", "--log-level", "info"]
