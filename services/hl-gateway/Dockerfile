FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY app /app/app
# The budget history volume (#252). Docker seeds a new, empty named volume from
# this directory, ownership included, so uid 1000 can write it.
RUN mkdir -p /state && chown 1000:1000 /state
USER 1000:1000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
