# The ORB bot as Railway (or any container host) runs it: one long-running process, no web port.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TRADER_STORAGE=/data

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY config ./config
COPY day-trader-skill ./day-trader-skill

# /data is the persistent volume (trade log, pause setting, signal folders, logs)
CMD ["python", "-m", "app", "run"]
