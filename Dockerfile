# Base image pinned by digest; Dependabot proposes digest updates.
FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928

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
