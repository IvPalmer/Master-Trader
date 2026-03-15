FROM python:3.11-slim

WORKDIR /app
RUN pip install --no-cache-dir prometheus_client requests
COPY metrics_exporter.py .

CMD ["python", "-u", "metrics_exporter.py"]
