FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Europe/Berlin \
    SATELLIT_ROOT=/app

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

VOLUME ["/app/state"]

ENTRYPOINT ["python", "-m", "satellit"]
CMD ["serve"]
