FROM python:3.12-slim AS build

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /build

COPY pyproject.toml ./
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip \
 && /opt/venv/bin/pip install .


FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

RUN groupadd --system --gid 65532 arcadia \
 && useradd --system --uid 65532 --gid arcadia --no-create-home arcadia

COPY --from=build /opt/venv /opt/venv

WORKDIR /srv
COPY app ./app
COPY migrations ./migrations

USER 65532:65532

ARG VERSION=dev
ENV SERVICE_VERSION=${VERSION}

EXPOSE 8091


HEALTHCHECK --interval=15s --timeout=5s --start-period=40s --retries=3 \
  CMD ["python", "-c", "import os,urllib.request,sys; port=os.environ.get('HTTP_PORT','8091'); sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{port}/readyz', timeout=3).status==200 else 1)"]

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${HTTP_PORT:-8091} --no-access-log"]
