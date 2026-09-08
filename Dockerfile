FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /srv/radio
COPY pyproject.toml requirements.lock ./
COPY app ./app
RUN pip install --no-cache-dir -c requirements.lock .
COPY catalog ./catalog
COPY scripts ./scripts
RUN mkdir -p /data/audio
ENV DATA_DIR=/data PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000"]
