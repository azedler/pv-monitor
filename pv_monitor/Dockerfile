FROM python:3.12-alpine

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PVMON_DB=/data/pvmonitor.sqlite
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ .

EXPOSE 8099
CMD ["python", "-m", "uvicorn", "pvmonitor.server:app", "--host", "0.0.0.0", "--port", "8099"]
