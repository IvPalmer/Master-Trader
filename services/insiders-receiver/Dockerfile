FROM python:3.13-slim

# System deps: Node.js (for the `claude` CLI npm package) + curl
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    npm install -g @anthropic-ai/claude-code && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

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

# Stay root so Claude can write to /root/.claude (the mounted auth volume).
# elder-brain-bot uses the same pattern.

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

EXPOSE 8089

ENTRYPOINT ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8089"]
