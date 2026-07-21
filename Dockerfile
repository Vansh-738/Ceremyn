FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Layer-cache dependencies separately from source
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY pyproject.toml README.md ./
COPY src/ src/
RUN pip install --no-deps -e .

# Run as non-root
RUN useradd --create-home appuser
USER appuser

EXPOSE 8000
CMD ["uvicorn", "ceremyn.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
