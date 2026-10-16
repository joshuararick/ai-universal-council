# Base image pinned by digest; Dependabot proposes digest updates.
FROM python:3.14-slim@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --require-hashes -r requirements.txt

COPY council.toml .
COPY council/ council/

# Run as an unprivileged user; app files stay root-owned and read-only to it.
RUN useradd --system --uid 10001 --no-create-home council
USER 10001

# Anything after the image name becomes the question / flags.
ENTRYPOINT ["python", "-m", "council"]
