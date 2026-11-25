# Daily 10 backend: the API, and (same image, other commands) the Telegram worker and MCP server.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY daily10 ./daily10
RUN useradd --system --uid 10001 app
USER app

EXPOSE 8000
CMD ["uvicorn", "daily10.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
