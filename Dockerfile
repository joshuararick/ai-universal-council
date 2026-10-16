# Base image pinned by digest; Dependabot proposes digest updates.
FROM python:3.11-slim@sha256:e88e9763f943ec1834f992a4b51e0f24500486803e8bc534e5767af9ea65f6ce

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --require-hashes -r requirements.txt

COPY core/ core/
COPY config/ config/

# Run as an unprivileged user; app files stay root-owned and read-only to it.
RUN useradd --system --uid 10001 --no-create-home council
USER 10001

ENTRYPOINT ["python", "core/council.py"]
