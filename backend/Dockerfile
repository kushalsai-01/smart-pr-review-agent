FROM python:3.11-slim AS base

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

ARG USER_UID=10001
ARG USER_GID=10001

RUN apt-get update \
  && apt-get install -y --no-install-recommends git build-essential gcc \
  && rm -rf /var/lib/apt/lists/*

RUN python -m venv /venv
ENV PATH="/venv/bin:$PATH"

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY backend /app/backend

RUN groupadd -g "${USER_GID}" appuser \
  && useradd -m -u "${USER_UID}" -g "${USER_GID}" appuser \
  && chown -R "${USER_UID}":"${USER_GID}" /app

USER ${USER_UID}:${USER_GID}

EXPOSE 8000
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]

