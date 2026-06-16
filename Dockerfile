# claude-agent-runner — webhook receiver + Claude Agent SDK sandbox agent (one image, two entrypoints)
FROM python:3.12-slim AS base
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/home/agent

RUN apt-get update && apt-get install -y --no-install-recommends \
        git ca-certificates openssh-client tini \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -u 1000 -m -d /home/agent agent

WORKDIR /app

COPY pyproject.toml uv.lock /app/
RUN pip install uv && \
    uv sync --frozen --no-dev --system && \
    rm -rf ~/.cache

# Allow the app package to be importable from any cwd
ENV PYTHONPATH=/app

COPY app/    /app/app/

EXPOSE 8080
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "app.receiver:app", "--host", "0.0.0.0", "--port", "8080"]
