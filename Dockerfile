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

ENV PLI_DB=/data/pli.db \
    PLI_KEYS_DIR=/data/keys

EXPOSE 8000

# --no-access-log is not cosmetic: a timestamped access log correlated
# with a reveal is a partial crush graph. Do not re-enable it.
CMD ["uvicorn", "pli.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
