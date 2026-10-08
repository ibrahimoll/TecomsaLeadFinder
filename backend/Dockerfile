FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# INSTALL_DEV=true adds pytest/httpx (used by the development compose file).
ARG INSTALL_DEV=false
COPY requirements.txt requirements-dev.txt ./
RUN pip install -r requirements.txt \
    && if [ "$INSTALL_DEV" = "true" ]; then pip install -r requirements-dev.txt; fi

COPY . .

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p storage/imports storage/discovery && chown -R appuser storage
USER appuser

EXPOSE 8000

# Apply pending migrations, then serve.
# Proxy headers are trusted only from private networks (the Next.js server and the TLS reverse proxy):
# the client address used for login rate limiting cannot be forged with X-Forwarded-For.
ENV FORWARDED_ALLOW_IPS="127.0.0.1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips=\"$FORWARDED_ALLOW_IPS\""]
