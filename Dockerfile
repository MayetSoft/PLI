FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY pli ./pli

RUN useradd --create-home --uid 10001 pli \
 && mkdir -p /data && chown -R pli:pli /data
USER pli

# Reproducible-build attestation: bake the commit in at build time
# (docker build --build-arg BUILD_COMMIT=$(git rev-parse HEAD) …) and set
# PLI_IMAGE_DIGEST at deploy time once the pushed digest is known.
ARG BUILD_COMMIT=""
ENV PLI_BUILD_COMMIT=${BUILD_COMMIT} \
    PLI_DB=/data/pli.db \
    PLI_KEYS_DIR=/data/keys

EXPOSE 8000

# --no-access-log is not cosmetic: a timestamped access log correlated
# with a reveal is a partial crush graph. Do not re-enable it.
CMD ["uvicorn", "pli.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
