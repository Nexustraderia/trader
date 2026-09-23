FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY README.md .

ENV PYTHONUNBUFFERED=1

CMD ["python", "app/main.py"]
