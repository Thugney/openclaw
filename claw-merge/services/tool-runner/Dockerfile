FROM python:3.12-slim

WORKDIR /app

COPY ../../shared /shared
RUN pip install --no-cache-dir /shared

COPY ../../plugins /plugins
COPY . /app
RUN pip install --no-cache-dir /app

EXPOSE 8003

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8003"]
