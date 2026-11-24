FROM python:3.12-alpine

# the supervisor passes the add-on version; the card's resource URL carries it
ARG BUILD_VERSION=dev

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PVMON_DB=/data/pvmonitor.sqlite PVMON_VERSION=$BUILD_VERSION
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ .

EXPOSE 8099
CMD ["python", "-m", "uvicorn", "pvmonitor.server:app", "--host", "0.0.0.0", "--port", "8099"]
