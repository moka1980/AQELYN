# Multi-arch friendly (linux/amd64 + linux/arm64) per ADR-0001.
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

COPY pyproject.toml BUILDING.md ./
COPY src ./src
RUN pip install .

CMD ["python", "-m", "aqelyn"]
