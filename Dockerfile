FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY stockfind ./stockfind
COPY eval ./eval

EXPOSE 8000

# Factory mode so app construction (JWT-secret validation) runs at startup.
# STOCKFIND_SEED_ON_START=1 seeds the catalog on boot (see docker-compose.yml).
CMD ["uvicorn", "--factory", "stockfind.api.app:create_app", \
     "--host", "0.0.0.0", "--port", "8000"]
